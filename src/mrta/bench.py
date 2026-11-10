"""ベンチマーク: 複数シードの統計と下界ギャップ(ADR-0008)。

- 測定は整数だけで記録する(`bench.json`)。集計は `Fraction` で厳密に行い、表示のときだけ小数に直す。
- **壁時計の時間は結果に含めない**(決定性)。同じ入力なら `environment` 以外は同じバイト列。
- CP-SAT は下界のために必ず走らせる(ADR-0008)。
- 結論は「この生成器・この設定」に対するもの。最適性を証明できたシードの割合を必ず併記する。
"""

import json
import platform
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, fields
from fractions import Fraction
from importlib.metadata import version
from types import MappingProxyType

from mrta.bounds import gap, lower_bound
from mrta.model import ModelError, Plan, Scenario
from mrta.scenario import GeneratorConfig, generate
from mrta.sim import simulate
from mrta.solvers import SOLVERS, ConfigValue, CpSatConfig, CpSatSolver, solve_cpsat

BENCH_VERSION = 1
BASELINE = "greedy"  # 勝敗の基準(ADR-0008)


class BenchError(ModelError):
    """ベンチマーク中の不整合(モデルとシミュレータの不一致など)。"""


@dataclass(frozen=True, slots=True)
class Preset:
    name: str
    generator: GeneratorConfig
    seeds: int  # シードは 0 .. seeds-1
    cpsat: CpSatConfig


PRESETS: Mapping[str, Preset] = MappingProxyType(
    {
        p.name: p
        for p in (
            Preset("small", GeneratorConfig(), 100, CpSatConfig(det_time_limit_ms=5000)),
            Preset("medium", GeneratorConfig(n_tasks=15), 60, CpSatConfig(det_time_limit_ms=5000)),
            Preset(
                "large",
                GeneratorConfig(n_amr=3, n_mobile_manipulators=3, n_tasks=20),
                40,
                CpSatConfig(det_time_limit_ms=20000),
            ),
            # テスト用。CI で回せる速さ。
            Preset(
                "tiny",
                GeneratorConfig(n_amr=1, n_mobile_manipulators=1, n_tasks=5),
                3,
                CpSatConfig(det_time_limit_ms=5000),
            ),
        )
    }
)


@dataclass(frozen=True, slots=True)
class SolverRow:
    """1シード × 1ソルバの測定。全て整数(稼働率は比にせず分子と分母。ADR-0004)。"""

    makespan: int
    total_distance: int
    busy_total: int
    available_total: int


@dataclass(frozen=True, slots=True)
class SeedRecord:
    seed: int
    lower_bound: int
    bound_proven: bool  # CP-SAT が makespan の最適性を証明したか
    rows: Mapping[str, SolverRow]  # ソルバ名 → 測定


@dataclass(frozen=True, slots=True)
class BenchResult:
    preset: Preset
    seeds: tuple[int, ...]
    solver_configs: Mapping[str, Mapping[str, ConfigValue]]
    records: tuple[SeedRecord, ...]
    environment: Mapping[str, str]


def run_seed(preset: Preset, seed: int) -> SeedRecord:
    scenario = generate(seed, preset.generator)
    cpsat = solve_cpsat(scenario, preset.cpsat)
    bound = lower_bound(scenario, cpsat.makespan_bound)

    rows: dict[str, SolverRow] = {}
    for name in sorted(SOLVERS):
        plan = cpsat.plan if name == "cpsat" else SOLVERS[name]().solve(scenario)
        rows[name] = _row(scenario, plan, bound)
    # モデルの値とシミュレータの値が食い違えば、モデルが誤っている(ADR-0007)。
    if rows["cpsat"].makespan != cpsat.makespan:
        raise BenchError(
            f"seed={seed}: CP-SAT の makespan {cpsat.makespan} がシミュレータの "
            f"{rows['cpsat'].makespan} と一致しない"
        )
    return SeedRecord(
        seed=seed, lower_bound=bound, bound_proven=cpsat.status == "optimal", rows=rows
    )


def _row(scenario: Scenario, plan: Plan, bound: int) -> SolverRow:
    m = simulate(scenario, plan).metrics
    gap(m.makespan, bound)  # makespan < 下界ならバグ。ここで止める。
    return SolverRow(m.makespan, m.total_distance, m.busy_total, m.available_total)


def _run_seed_args(args: tuple[Preset, int]) -> SeedRecord:
    return run_seed(*args)


def run(
    preset: Preset,
    *,
    seeds: int | None = None,
    jobs: int = 1,
    on_done: Callable[[int], None] | None = None,
) -> BenchResult:
    """プリセットを実行する。`seeds` は先頭から N 件。結果はシード順(`jobs` に依存しない)。"""
    n = preset.seeds if seeds is None else seeds
    if n < 1:
        raise BenchError(f"seeds は1以上: {n}")
    if jobs < 1:
        raise BenchError(f"jobs は1以上: {jobs}")
    seed_list = tuple(range(n))
    jobs_args = [(preset, seed) for seed in seed_list]

    records: list[SeedRecord] = []
    if jobs == 1:
        for args in jobs_args:
            records.append(_run_seed_args(args))
            if on_done:
                on_done(len(records))
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for record in pool.map(_run_seed_args, jobs_args):  # 入力順に返る
                records.append(record)
                if on_done:
                    on_done(len(records))

    solver_configs = {
        name: (CpSatSolver(preset.cpsat) if name == "cpsat" else SOLVERS[name]()).config
        for name in sorted(SOLVERS)
    }
    return BenchResult(
        preset=preset,
        seeds=seed_list,
        solver_configs=solver_configs,
        records=tuple(records),
        environment={"ortools": version("ortools"), "python": platform.python_version()},
    )


# ---- 集計(Fraction で厳密に) ----


def mean(values: Sequence[int | Fraction]) -> Fraction:
    return Fraction(sum(values, Fraction(0)), len(values))


def median(values: Sequence[int | Fraction]) -> Fraction:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return Fraction(ordered[mid])
    return (Fraction(ordered[mid - 1]) + Fraction(ordered[mid])) / 2


def percentile(values: Sequence[int | Fraction], percent: int) -> Fraction:
    """最近順位法: 小さい順に並べた `ceil(percent × n / 100)` 番目。"""
    ordered = sorted(values)
    rank = max(1, -(-percent * len(ordered) // 100))
    return Fraction(ordered[rank - 1])


@dataclass(frozen=True, slots=True)
class Summary:
    n: int
    makespan_mean: Fraction
    makespan_median: Fraction
    makespan_p90: Fraction
    makespan_max: int
    gap_n: int  # ギャップが定義できたシード数
    gap_mean: Fraction | None
    gap_median: Fraction | None
    gap_max: Fraction | None
    at_bound: int  # makespan が下界に一致したシード数
    distance_mean: Fraction
    utilization_mean: Fraction | None
    wins: int  # ベースラインより makespan が小さい
    ties: int
    losses: int


def summarize(result: BenchResult, solver: str) -> Summary:
    rows = [(rec.lower_bound, rec.rows[solver], rec.rows[BASELINE]) for rec in result.records]
    makespans = [row.makespan for _, row, _ in rows]
    gaps = [g for bound, row, _ in rows if (g := gap(row.makespan, bound)) is not None]
    utils = [
        Fraction(row.busy_total, row.available_total)
        for _, row, _ in rows
        if row.available_total > 0
    ]
    return Summary(
        n=len(rows),
        makespan_mean=mean(makespans),
        makespan_median=median(makespans),
        makespan_p90=percentile(makespans, 90),
        makespan_max=max(makespans),
        gap_n=len(gaps),
        gap_mean=mean(gaps) if gaps else None,
        gap_median=median(gaps) if gaps else None,
        gap_max=max(gaps) if gaps else None,
        at_bound=sum(row.makespan == bound for bound, row, _ in rows),
        distance_mean=mean([row.total_distance for _, row, _ in rows]),
        utilization_mean=mean(utils) if utils else None,
        wins=sum(row.makespan < base.makespan for _, row, base in rows),
        ties=sum(row.makespan == base.makespan for _, row, base in rows),
        losses=sum(row.makespan > base.makespan for _, row, base in rows),
    )


def proven_count(result: BenchResult) -> int:
    return sum(rec.bound_proven for rec in result.records)


# ---- 出力 ----


def format_fixed(value: Fraction, digits: int = 1) -> str:
    """非負の分数を、小数 `digits` 桁に四捨五入(0.5 は切り上げ)して書く。整数演算だけ。"""
    if value < 0:
        raise ValueError(f"非負のみ: {value}")
    scale = 10**digits
    scaled = (2 * value.numerator * scale + value.denominator) // (2 * value.denominator)
    whole, frac = divmod(scaled, scale)
    return f"{whole}.{frac:0{digits}d}" if digits else str(whole)


def _percent(value: Fraction | None) -> str:
    return "—" if value is None else format_fixed(value * 100)


def _opt(value: Fraction | None) -> str:
    return "—" if value is None else format_fixed(value)


def render_json(result: BenchResult) -> str:
    """測定の生データ。整数のみ、キーをソート、空白なし(ADR-0004 と同じ規則)。"""
    preset = result.preset
    obj = {
        "bench_version": BENCH_VERSION,
        "environment": dict(result.environment),
        "preset": {
            "name": preset.name,
            "generator": {
                f.name: getattr(preset.generator, f.name) for f in fields(preset.generator)
            },
            "seeds": [result.seeds[0], result.seeds[-1] + 1],  # [始点, 終点) の半開区間
        },
        "solvers": {name: dict(cfg) for name, cfg in result.solver_configs.items()},
        "records": [
            {
                "seed": rec.seed,
                "lower_bound": rec.lower_bound,
                "bound_proven": rec.bound_proven,
                "solvers": {
                    name: {
                        "makespan": row.makespan,
                        "total_distance": row.total_distance,
                        "busy_total": row.busy_total,
                        "available_total": row.available_total,
                    }
                    for name, row in rec.rows.items()
                },
            }
            for rec in result.records
        ],
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def render_markdown(result: BenchResult) -> str:
    preset = result.preset
    n = len(result.records)
    proven = proven_count(result)
    g = preset.generator
    lines = [
        f"## ベンチマーク: {preset.name}",
        "",
        f"- シード: {result.seeds[0]}..{result.seeds[-1]}({n}件)",
        f"- 生成器: {g.n_amr} AMR + {g.n_mobile_manipulators} マニピュレーター、"
        f"タスク {g.n_tasks}、格子 {g.width}x{g.height}、操作スキル {g.manipulate_percent}%",
        f"- CP-SAT: 各段階の決定的時間の上限 {preset.cpsat.det_time_limit_ms} ms",
        f"- 環境: OR-Tools {result.environment['ortools']} / Python {result.environment['python']}",
        f"- **最適性を証明できたシード: {proven}/{n} ({_percent(Fraction(proven, n))}%)**",
        "",
        "| ソルバ | 完了時間 平均 | 中央値 | p90 | 最大 "
        "| 下界ギャップ 平均(%) | 中央値(%) | 最大(%) "
        f"| 下界に一致 | 総移動距離 平均 | 稼働率 平均(%) | {BASELINE}に 勝/同/負 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in sorted(result.solver_configs):
        s = summarize(result, name)
        versus = "—" if name == BASELINE else f"{s.wins}/{s.ties}/{s.losses}"
        lines.append(
            f"| {name} | {format_fixed(s.makespan_mean)} | {format_fixed(s.makespan_median)} "
            f"| {format_fixed(s.makespan_p90)} | {s.makespan_max} "
            f"| {_percent(s.gap_mean)} | {_percent(s.gap_median)} | {_percent(s.gap_max)} "
            f"| {s.at_bound}/{s.n} | {format_fixed(s.distance_mean)} "
            f"| {_percent(s.utilization_mean)} | {versus} |"
        )
    lines += [
        "",
        "読み方:",
        "",
        "- 下界ギャップ = (完了時間 − 下界) / 下界。下界は最適値以下なので、"
        "**最適からの距離の上限**になる。",
        "- 最適性を証明できたシードでは下界 = 最適値で、ギャップは真の最適からの距離。"
        "証明できなかったシードでは下界が緩く、ギャップは過大になる。",
        "- 勝/同/負は、完了時間が小さいほうが勝ち。1シナリオの勝ち負けではなく、件数で見る。",
        "- この生成器・この設定に対する結果であり、一般化しない。有意性の検定はしていない。",
        "",
    ]
    return "\n".join(lines)
