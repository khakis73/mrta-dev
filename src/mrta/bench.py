"""ベンチマーク: 複数シードの統計と下界ギャップ(ADR-0008)。

- 測定は整数だけで記録する(`bench.json`)。集計は `Fraction` で厳密に行い、表示のときだけ小数に直す。
- **壁時計の時間は結果に含めない**(決定性)。同じ入力なら `environment` 以外は同じバイト列。
- CP-SAT は下界のために必ず走らせる(ADR-0008)。
- 結論は「この生成器・この設定」に対するもの。最適性を証明できたシードの割合を必ず併記する。
- **動的なプリセット**(到着の窓 > 0。ADR-0012)では、ローリングホライズン版も回し、
  「静的(到着を無視)」と「ローリング」を区別して並べる。静的ソルバの CP-SAT の「最適」は、
  動的な最適ではない。厳密なオフライン最適は、小さな規模だけ全探索で出す(`mrta.exact`)。
"""

import json
import platform
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, fields, replace
from fractions import Fraction
from importlib.metadata import version
from types import MappingProxyType

from mrta.bounds import gap, lower_bound
from mrta.exact import offline_optimum
from mrta.model import ModelError, Plan, Scenario
from mrta.scenario import GeneratorConfig, generate
from mrta.sim import simulate
from mrta.solvers import (
    SOLVERS,
    ConfigValue,
    CpSatConfig,
    CpSatSolver,
    RollingSolver,
    Solver,
    solve_cpsat,
)

BENCH_VERSION = 1
BASELINE = "greedy"  # 勝敗の基準(ADR-0008)
ROLLING_PREFIX = "rolling-"


class BenchError(ModelError):
    """ベンチマーク中の不整合(モデルとシミュレータの不一致など)。"""


@dataclass(frozen=True, slots=True)
class Preset:
    name: str
    generator: GeneratorConfig
    seeds: int  # シードは 0 .. seeds-1
    cpsat: CpSatConfig
    exact: bool = False  # 全探索でオフライン最適を出し、下界にする(小さな規模だけ。ADR-0012)

    @property
    def dynamic(self) -> bool:
        """到着の窓が正なら動的。ローリング版も回す。"""
        return self.generator.arrival_window > 0


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
            # 動的(ADR-0012)。到着の窓 20 は、静的な makespan(約 25)の約 8 割。
            Preset(
                "dynamic-small",
                GeneratorConfig(arrival_window=20),
                40,
                CpSatConfig(det_time_limit_ms=5000),
            ),
            # 小さな規模。全探索のオフライン最適を下界(= 最適値)にして、競争比を測る。
            Preset(
                "dynamic-tiny",
                GeneratorConfig(n_amr=1, n_mobile_manipulators=2, n_tasks=5, arrival_window=20),
                60,
                CpSatConfig(det_time_limit_ms=5000),
                exact=True,
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
    # 下界がこの問題の最適値に一致すると証明されたか。静的: CP-SAT が証明した。
    # 動的: 全探索のオフライン最適のときだけ真(静的ソルバの CP-SAT は動的な最適を証明しない)。
    bound_proven: bool
    rows: Mapping[str, SolverRow]  # ソルバ名 → 測定


@dataclass(frozen=True, slots=True)
class BenchResult:
    preset: Preset
    seeds: tuple[int, ...]
    solver_configs: Mapping[str, Mapping[str, ConfigValue]]
    records: tuple[SeedRecord, ...]
    environment: Mapping[str, str]


def solver_names(preset: Preset) -> list[str]:
    """回すソルバ。動的なプリセットでは、ローリング版も回す(ADR-0012)。"""
    names = sorted(SOLVERS)
    if preset.dynamic:
        names += [f"{ROLLING_PREFIX}{name}" for name in sorted(SOLVERS)]
    return names


def _make(name: str, preset: Preset) -> Solver:
    """プリセットの設定(CP-SAT の上限)を反映したソルバ。"""
    if name.startswith(ROLLING_PREFIX):
        return RollingSolver(_make(name.removeprefix(ROLLING_PREFIX), preset))
    return CpSatSolver(preset.cpsat) if name == "cpsat" else SOLVERS[name]()


def run_seed(preset: Preset, seed: int) -> SeedRecord:
    scenario = generate(seed, preset.generator)
    cpsat = solve_cpsat(scenario, preset.cpsat)
    # 静的ソルバの CP-SAT の下界は、動的でも有効な下界(動的な最適は静的な最適以上。ADR-0011)。
    bound = lower_bound(scenario, cpsat.makespan_bound)
    proven = cpsat.status == "optimal"
    if preset.dynamic:
        proven = False  # 静的な最適の証明は、動的な最適を意味しない
    if preset.exact:
        # 全探索の厳密なオフライン最適。下界より強く、最適値そのもの。
        bound = max(bound, offline_optimum(scenario))
        proven = True

    rows: dict[str, SolverRow] = {}
    for name in solver_names(preset):
        # CP-SAT は下界のために既に解いた結果を使う(同じ設定・同じ入力で、結果は同一)。
        plan = cpsat.plan if name == "cpsat" else _make(name, preset).solve(scenario)
        rows[name] = _row(scenario, plan, bound)
    # モデルの値とシミュレータの値が食い違えば、モデルが誤っている(ADR-0007)。
    # 静的ソルバのモデルは到着時刻を見ないので、動的なシナリオでは一致しない(ADR-0011)。
    if not preset.dynamic and rows["cpsat"].makespan != cpsat.makespan:
        raise BenchError(
            f"seed={seed}: CP-SAT の makespan {cpsat.makespan} がシミュレータの "
            f"{rows['cpsat'].makespan} と一致しない"
        )
    return SeedRecord(seed=seed, lower_bound=bound, bound_proven=proven, rows=rows)


def _row(scenario: Scenario, plan: Plan, bound: int) -> SolverRow:
    m = simulate(scenario, plan).metrics
    gap(m.makespan, bound)  # makespan < 下界ならバグ。ここで止める。
    return SolverRow(m.makespan, m.total_distance, m.busy_total, m.available_total)


def _run_seed_args(args: tuple[Preset, int]) -> SeedRecord:
    return run_seed(*args)


def with_window(preset: Preset, window: int) -> Preset:
    """到着の窓を上書きしたプリセット(結果に窓が併記される)。"""
    if window < 0:
        raise BenchError(f"window は0以上: {window}")
    return replace(preset, generator=replace(preset.generator, arrival_window=window))


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

    solver_configs = {name: _make(name, preset).config for name in solver_names(preset)}
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


@dataclass(frozen=True, slots=True)
class RollingVsStatic:
    """ローリング版と、同じ基底の静的ソルバ(到着を無視)の対比(ADR-0012)。"""

    base: str
    static_mean: Fraction
    rolling_mean: Fraction
    wins: int  # ローリングのほうが makespan が小さい
    ties: int
    losses: int
    static_distance_mean: Fraction
    rolling_distance_mean: Fraction


def rolling_vs_static(result: BenchResult, base: str) -> RollingVsStatic:
    pairs = [(rec.rows[base], rec.rows[f"{ROLLING_PREFIX}{base}"]) for rec in result.records]
    return RollingVsStatic(
        base=base,
        static_mean=mean([a.makespan for a, _ in pairs]),
        rolling_mean=mean([b.makespan for _, b in pairs]),
        wins=sum(b.makespan < a.makespan for a, b in pairs),
        ties=sum(b.makespan == a.makespan for a, b in pairs),
        losses=sum(b.makespan > a.makespan for a, b in pairs),
        static_distance_mean=mean([a.total_distance for a, _ in pairs]),
        rolling_distance_mean=mean([b.total_distance for _, b in pairs]),
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
            "dynamic": preset.dynamic,
            "exact": preset.exact,
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


def _kind(name: str) -> str:
    return "ローリング" if name.startswith(ROLLING_PREFIX) else "静的(到着を無視)"


def render_markdown(result: BenchResult) -> str:
    preset = result.preset
    n = len(result.records)
    proven = proven_count(result)
    g = preset.generator
    dynamic = preset.dynamic
    lines = [
        f"## ベンチマーク: {preset.name}",
        "",
        f"- シード: {result.seeds[0]}..{result.seeds[-1]}({n}件)",
        f"- 生成器: {g.n_amr} AMR + {g.n_mobile_manipulators} マニピュレーター、"
        f"タスク {g.n_tasks}、格子 {g.width}x{g.height}、操作スキル {g.manipulate_percent}%"
        + (f"、**到着の窓 {g.arrival_window}**" if dynamic else ""),
        f"- CP-SAT: 各段階の決定的時間の上限 {preset.cpsat.det_time_limit_ms} ms",
        f"- 環境: OR-Tools {result.environment['ortools']} / Python {result.environment['python']}",
    ]
    if preset.exact:
        lines.append(
            "- **下界 = 全探索のオフライン最適**(全タスクを事前に知る場合の厳密な最適値。"
            f"{proven}/{n} 件で得た)"
        )
    elif dynamic:
        lines.append(
            "- **下界は参考値**(静的な CP-SAT の下界と到着時刻から作った弱い下界)。"
            "動的なオフライン最適は分からない"
        )
    else:
        lines.append(
            f"- **最適性を証明できたシード: {proven}/{n} ({_percent(Fraction(proven, n))}%)**"
        )
    lines += [
        "",
        "| ソルバ | " + ("種別 | " if dynamic else "") + "完了時間 平均 | 中央値 | p90 | 最大 "
        "| 下界ギャップ 平均(%) | 中央値(%) | 最大(%) "
        f"| 下界に一致 | 総移動距離 平均 | 稼働率 平均(%) | {BASELINE}に 勝/同/負 |",
        "|---|" + ("---|" if dynamic else "") + "---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in sorted(result.solver_configs):
        s = summarize(result, name)
        versus = "—" if name == BASELINE else f"{s.wins}/{s.ties}/{s.losses}"
        lines.append(
            f"| {name} | "
            + (f"{_kind(name)} | " if dynamic else "")
            + f"{format_fixed(s.makespan_mean)} | {format_fixed(s.makespan_median)} "
            f"| {format_fixed(s.makespan_p90)} | {s.makespan_max} "
            f"| {_percent(s.gap_mean)} | {_percent(s.gap_median)} | {_percent(s.gap_max)} "
            f"| {s.at_bound}/{s.n} | {format_fixed(s.distance_mean)} "
            f"| {_percent(s.utilization_mean)} | {versus} |"
        )
    if dynamic:
        lines += [
            "",
            "ローリング(オンライン)と、同じ基底の静的ソルバ(到着を無視)の対比:",
            "",
            "| 基底 | 静的 完了時間 平均 | ローリング 完了時間 平均 | 改善(%) "
            "| ローリングの 勝/同/負 | 総移動距離 平均 静的 → ローリング |",
            "|---|---|---|---|---|---|",
        ]
        for base in sorted(SOLVERS):
            c = rolling_vs_static(result, base)
            improvement = (c.static_mean - c.rolling_mean) / c.static_mean
            sign = "" if improvement >= 0 else "−"
            lines.append(
                f"| {base} | {format_fixed(c.static_mean)} | {format_fixed(c.rolling_mean)} "
                f"| {sign}{format_fixed(abs(improvement) * 100)} "
                f"| {c.wins}/{c.ties}/{c.losses} "
                f"| {format_fixed(c.static_distance_mean)} → "
                f"{format_fixed(c.rolling_distance_mean)} |"
            )
    lines += [
        "",
        "読み方:",
        "",
        "- 下界ギャップ = (完了時間 − 下界) / 下界。下界は最適値以下なので、"
        "**最適からの距離の上限**になる。",
    ]
    if preset.exact:
        lines.append(
            "- 下界は全探索のオフライン最適(最適値そのもの)なので、ギャップは"
            "**オフライン最適に対する比 − 1**(競争比)になる。"
        )
    elif dynamic:
        lines.append(
            "- 動的では下界が弱く、ギャップは大きく出る(最適からの距離を言えない)。"
            "ソルバ同士・静的との**相対比較**に使う。"
        )
    else:
        lines.append(
            "- 最適性を証明できたシードでは下界 = 最適値で、ギャップは真の最適からの距離。"
            "証明できなかったシードでは下界が緩く、ギャップは過大になる。"
        )
    lines.append(
        "- 勝/同/負は、完了時間が小さいほうが勝ち。1シナリオの勝ち負けではなく、件数で見る。"
    )
    if dynamic:
        lines += [
            "- **「静的(到着を無視)」の行はオンラインの基準ではない。** 静的ソルバは到着時刻を"
            "見ないが、未来のタスクの存在と場所を時刻0で知っている(ADR-0011)。"
            "ローリングは未来を知らない。",
            "- 到着の窓が短いと、未来を知る静的が有利で、ローリングが劣ることがある。"
            "窓が長いと、ソルバ間の差が潰れる(makespan が最後の到着に支配される)。",
        ]
    lines += [
        "- この生成器・この設定に対する結果であり、一般化しない。有意性の検定はしていない。",
        "",
    ]
    return "\n".join(lines)
