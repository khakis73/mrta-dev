"""動的ベンチマーク(ADR-0012)のテスト。CI で回すのは小さなシード数だけ。"""

import json
from fractions import Fraction
from pathlib import Path

import pytest

from mrta.bench import (
    PRESETS,
    BenchError,
    BenchResult,
    SeedRecord,
    SolverRow,
    _make,
    render_json,
    render_markdown,
    rolling_vs_static,
    run,
    solver_names,
    with_window,
)
from mrta.cli import main
from mrta.exact import offline_optimum
from mrta.scenario import generate
from mrta.sim import simulate
from mrta.solvers import ONLINE_SOLVERS, SOLVERS

TINY = PRESETS["dynamic-tiny"]
SMALL = PRESETS["dynamic-small"]


@pytest.fixture(scope="module")
def tiny_result() -> BenchResult:
    return run(TINY, seeds=4)


class TestPresets:
    def test_dynamic_presets_have_a_positive_window(self) -> None:
        assert SMALL.dynamic and TINY.dynamic
        assert SMALL.generator.arrival_window == 20 == TINY.generator.arrival_window

    def test_static_presets_stay_static_and_do_not_run_rolling_solvers(self) -> None:
        for name in ("small", "medium", "large", "tiny"):
            preset = PRESETS[name]
            assert not preset.dynamic and not preset.exact
            assert solver_names(preset) == sorted(SOLVERS)  # 静的な表に基底と同じ行を増やさない

    def test_dynamic_presets_run_static_and_rolling_solvers(self) -> None:
        expected = sorted(SOLVERS) + [f"rolling-{n}" for n in sorted(SOLVERS)]
        assert solver_names(SMALL) == expected
        assert set(ONLINE_SOLVERS) <= set(solver_names(SMALL))

    def test_only_the_tiny_dynamic_preset_uses_the_exhaustive_optimum(self) -> None:
        assert TINY.exact and not SMALL.exact


class TestExactBound:
    def test_the_bound_is_the_offline_optimum_and_proven(self, tiny_result: BenchResult) -> None:
        for rec in tiny_result.records:
            s = generate(rec.seed, TINY.generator)
            assert rec.lower_bound == offline_optimum(s)
            assert rec.bound_proven  # 厳密な最適値なので、証明済み

    def test_no_solver_beats_the_offline_optimum(self, tiny_result: BenchResult) -> None:
        for rec in tiny_result.records:
            assert all(r.makespan >= rec.lower_bound for r in rec.rows.values())

    def test_the_gap_is_the_competitive_ratio_minus_one(self, tiny_result: BenchResult) -> None:
        rec = tiny_result.records[0]
        for row in rec.rows.values():
            assert Fraction(row.makespan - rec.lower_bound, rec.lower_bound) >= 0


class TestWeakBoundOnLargerDynamicScenarios:
    def test_the_bound_is_not_claimed_to_be_proven(self) -> None:
        """静的な CP-SAT が最適性を証明しても、動的な最適を証明したことにはならない。"""
        result = run(SMALL, seeds=3)
        assert not any(rec.bound_proven for rec in result.records)
        for rec in result.records:
            assert all(r.makespan >= rec.lower_bound for r in rec.rows.values())

    def test_the_bound_is_valid_for_every_solver_including_rolling(self) -> None:
        for rec in run(SMALL, seeds=3).records:
            assert all(r.makespan >= rec.lower_bound for r in rec.rows.values())


class TestOutputs:
    def test_markdown_separates_static_and_rolling_rows(self, tiny_result: BenchResult) -> None:
        md = render_markdown(tiny_result)
        assert "| 種別 |" in md
        assert md.count("静的(到着を無視)") >= len(SOLVERS)  # 表の行
        assert md.count("| ローリング |") == len(SOLVERS)
        assert "対比" in md
        assert "オンラインの基準ではない" in md  # 静的の行の注記
        assert "到着の窓 20" in md

    def test_markdown_states_what_the_bound_is(self, tiny_result: BenchResult) -> None:
        assert "全探索のオフライン最適" in render_markdown(tiny_result)
        assert "下界は参考値" in render_markdown(run(SMALL, seeds=2))

    def test_static_markdown_is_unchanged_in_shape(self) -> None:
        md = render_markdown(run(PRESETS["tiny"]))
        assert "種別" not in md and "対比" not in md and "到着の窓" not in md
        assert "最適性を証明できたシード" in md

    def test_json_records_the_window_and_the_kind_of_run(self, tiny_result: BenchResult) -> None:
        obj = json.loads(render_json(tiny_result))
        assert obj["preset"]["generator"]["arrival_window"] == 20
        assert obj["preset"]["dynamic"] is True and obj["preset"]["exact"] is True
        assert set(obj["solvers"]) == set(solver_names(TINY))
        assert obj["solvers"]["rolling-greedy"] == {"base": "greedy"}

    def test_json_is_deterministic_and_does_not_depend_on_jobs(self) -> None:
        a, b = run(TINY, seeds=3, jobs=1), run(TINY, seeds=3, jobs=2)
        assert render_json(a) == render_json(b)


class TestRollingVsStatic:
    def make(self) -> BenchResult:
        def row(makespan: int, distance: int) -> SolverRow:
            return SolverRow(makespan, distance, 8, 16)

        # 勝ち 2・同点 1・負け 1 と非対称にする(勝ちと負けを取り違える変異を検出するため)。
        records = (
            SeedRecord(0, 5, False, {"greedy": row(20, 30), "rolling-greedy": row(15, 40)}),
            SeedRecord(1, 5, False, {"greedy": row(20, 30), "rolling-greedy": row(20, 30)}),
            SeedRecord(2, 5, False, {"greedy": row(10, 20), "rolling-greedy": row(14, 26)}),
            SeedRecord(3, 5, False, {"greedy": row(30, 50), "rolling-greedy": row(22, 44)}),
        )
        return BenchResult(
            preset=SMALL,
            seeds=(0, 1, 2, 3),
            solver_configs={"greedy": {}, "rolling-greedy": {"base": "greedy"}},
            records=records,
            environment={"ortools": "x", "python": "y"},
        )

    def test_wins_ties_losses_and_means(self) -> None:
        c = rolling_vs_static(self.make(), "greedy")
        assert (c.wins, c.ties, c.losses) == (2, 1, 1)
        assert c.static_mean == Fraction(80, 4)  # (20 + 20 + 10 + 30) / 4
        assert c.rolling_mean == Fraction(71, 4)  # (15 + 20 + 14 + 22) / 4
        assert c.static_distance_mean == Fraction(130, 4)  # (30 + 30 + 20 + 50) / 4
        assert c.rolling_distance_mean == Fraction(140, 4)  # (40 + 30 + 26 + 44) / 4


class TestWindowOverride:
    def test_window_changes_the_generator_and_the_kind_of_run(self) -> None:
        static = with_window(SMALL, 0)
        assert not static.dynamic
        assert solver_names(static) == sorted(SOLVERS)
        assert with_window(PRESETS["small"], 15).dynamic

    def test_negative_window_is_rejected(self) -> None:
        with pytest.raises(BenchError, match="window"):
            with_window(SMALL, -1)

    def test_a_static_preset_with_a_window_is_dynamic_and_not_claimed_proven(self) -> None:
        result = run(with_window(PRESETS["tiny"], 20), seeds=2)
        assert not any(rec.bound_proven for rec in result.records)
        assert "rolling-greedy" in result.records[0].rows

    def test_cli_accepts_window(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        out = tmp_path / "b"
        assert (
            main(["bench", "--preset", "tiny", "--seeds", "2", "--window", "20", "--out", str(out)])
            == 0
        )
        text = capsys.readouterr().out
        assert "到着の窓 20" in text and "ローリング" in text
        assert (
            json.loads((out / "bench.json").read_text(encoding="utf-8"))["preset"]["generator"][
                "arrival_window"
            ]
            == 20
        )

    def test_cli_rejects_a_negative_window(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["bench", "--preset", "tiny", "--window", "-1"]) == 2
        assert "エラー" in capsys.readouterr().err


def test_every_solver_row_is_consistent_with_the_simulator() -> None:
    """記録した makespan は、同じ設定のソルバの Plan をシミュレータで測った値に一致する。"""
    rec = run(TINY, seeds=1).records[0]
    s = generate(0, TINY.generator)
    for name, row in rec.rows.items():
        solver = _make(name, TINY)  # プリセットの設定(CP-SAT の上限)を反映したソルバ
        assert simulate(s, solver.solve(s)).metrics.makespan == row.makespan, name
