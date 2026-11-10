"""ベンチマークのテスト(ADR-0008)。CI で回すのは `tiny` だけ。"""

import json
from fractions import Fraction
from pathlib import Path

import pytest

from mrta.bench import (
    BASELINE,
    PRESETS,
    BenchError,
    BenchResult,
    SeedRecord,
    SolverRow,
    _row,
    format_fixed,
    mean,
    median,
    percentile,
    proven_count,
    render_json,
    render_markdown,
    run,
    summarize,
)
from mrta.bounds import BoundViolationError
from mrta.cli import main
from mrta.scenario import generate
from mrta.solvers import SOLVERS, GreedySolver


def row(makespan: int, distance: int = 10, busy: int = 8, available: int = 16) -> SolverRow:
    return SolverRow(makespan, distance, busy, available)


class TestStatistics:
    def test_mean_is_exact(self) -> None:
        assert mean([1, 2, 2]) == Fraction(5, 3)

    @pytest.mark.parametrize(
        ("values", "expected"),
        [([3], 3), ([5, 1, 3], 3), ([4, 1, 3, 2], Fraction(5, 2))],
    )
    def test_median(self, values: list[int], expected: Fraction) -> None:
        assert median(values) == expected

    @pytest.mark.parametrize(
        ("percent", "expected"),
        [(50, 5), (90, 9), (100, 10), (10, 1)],
    )
    def test_percentile_is_nearest_rank(self, percent: int, expected: int) -> None:
        # 1..10 の n=10: 90パーセンタイルは ceil(0.9 × 10) = 9 番目。
        assert percentile(list(range(10, 0, -1)), percent) == expected

    def test_percentile_of_one_value(self) -> None:
        assert percentile([7], 90) == 7

    @pytest.mark.parametrize(
        ("value", "digits", "expected"),
        [
            (Fraction(1, 3), 1, "0.3"),
            (Fraction(1, 2), 0, "1"),  # 0.5 は切り上げ
            (Fraction(9, 4), 1, "2.3"),  # 2.25 → 2.3
            (Fraction(5, 100), 1, "0.1"),
            (Fraction(0), 1, "0.0"),
            (Fraction(1234, 10), 1, "123.4"),
        ],
    )
    def test_format_fixed(self, value: Fraction, digits: int, expected: str) -> None:
        assert format_fixed(value, digits) == expected

    def test_format_fixed_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="非負"):
            format_fixed(Fraction(-1, 2))


def hand_made_result() -> BenchResult:
    """手計算できる3シード。下界は 10, 20, 0。"""
    preset = PRESETS["tiny"]
    records = (
        SeedRecord(0, 10, True, {"greedy": row(15), "hungarian": row(12), "cpsat": row(10)}),
        SeedRecord(1, 20, False, {"greedy": row(20), "hungarian": row(30), "cpsat": row(22)}),
        SeedRecord(
            2,
            0,
            True,
            {
                "greedy": row(0, available=0),
                "hungarian": row(0, available=0),
                "cpsat": row(0, available=0),
            },
        ),
    )
    return BenchResult(
        preset=preset,
        seeds=(0, 1, 2),
        solver_configs={name: {} for name in ("greedy", "hungarian", "cpsat")},
        records=records,
        environment={"ortools": "x", "python": "y"},
    )


class TestSummarize:
    def test_greedy_against_itself(self) -> None:
        s = summarize(hand_made_result(), "greedy")
        assert s.n == 3
        assert s.makespan_mean == Fraction(35, 3)
        assert s.makespan_median == 15
        assert s.makespan_max == 20
        # ギャップ: seed0 = 5/10、seed1 = 0、seed2 は下界 0 で未定義。
        assert s.gap_n == 2
        assert s.gap_mean == Fraction(1, 4)
        assert s.gap_median == Fraction(1, 4)
        assert s.gap_max == Fraction(1, 2)
        assert s.at_bound == 2  # seed1 (20=20) と seed2 (0=0)

    def test_win_tie_loss_against_the_baseline(self) -> None:
        s = summarize(hand_made_result(), "hungarian")
        # seed0: 12 < 15 勝ち、seed1: 30 > 20 負け、seed2: 0 = 0 同点。
        assert (s.wins, s.ties, s.losses) == (1, 1, 1)
        c = summarize(hand_made_result(), "cpsat")
        assert (c.wins, c.ties, c.losses) == (1, 1, 1)  # 10<15 勝ち、22>20 負け、0=0 同点

    def test_utilization_skips_undefined_seeds(self) -> None:
        s = summarize(hand_made_result(), "greedy")
        assert s.utilization_mean == Fraction(1, 2)  # 8/16 を2件。available=0 の seed2 は除く

    def test_proven_count(self) -> None:
        assert proven_count(hand_made_result()) == 2

    def test_markdown_reports_n_range_and_proven_share(self) -> None:
        md = render_markdown(hand_made_result())
        assert "シード: 0..2(3件)" in md
        assert "最適性を証明できたシード: 2/3 (66.7%)" in md
        assert f"| {BASELINE} |" in md


@pytest.fixture(scope="module")
def result() -> BenchResult:
    return run(PRESETS["tiny"])


class TestRun:
    def test_one_record_per_seed_with_every_solver(self, result: BenchResult) -> None:
        assert [r.seed for r in result.records] == [0, 1, 2]
        for rec in result.records:
            assert set(rec.rows) == set(SOLVERS)

    def test_bound_is_below_every_solver_and_tight_when_proven(self, result: BenchResult) -> None:
        for rec in result.records:
            assert all(r.makespan >= rec.lower_bound for r in rec.rows.values())
            if rec.bound_proven:
                assert rec.rows["cpsat"].makespan == rec.lower_bound

    def test_cpsat_is_never_worse_than_the_heuristics_when_proven(
        self, result: BenchResult
    ) -> None:
        for rec in result.records:
            if rec.bound_proven:
                assert rec.rows["cpsat"].makespan <= min(
                    rec.rows["greedy"].makespan, rec.rows["hungarian"].makespan
                )

    def test_seeds_option_takes_the_first_n(self) -> None:
        assert [r.seed for r in run(PRESETS["tiny"], seeds=2).records] == [0, 1]

    def test_rejects_invalid_arguments(self) -> None:
        with pytest.raises(BenchError, match="seeds"):
            run(PRESETS["tiny"], seeds=0)
        with pytest.raises(BenchError, match="jobs"):
            run(PRESETS["tiny"], jobs=0)

    def test_progress_callback_counts_up(self) -> None:
        done: list[int] = []
        run(PRESETS["tiny"], on_done=done.append)
        assert done == [1, 2, 3]


def without_environment(text: str) -> object:
    obj = json.loads(text)
    del obj["environment"]
    return obj


class TestOutputs:
    def test_json_is_deterministic_apart_from_the_environment(self) -> None:
        first, second = run(PRESETS["tiny"]), run(PRESETS["tiny"])
        assert without_environment(render_json(first)) == without_environment(render_json(second))

    def test_json_does_not_depend_on_jobs(self) -> None:
        assert render_json(run(PRESETS["tiny"], jobs=2)) == render_json(
            run(PRESETS["tiny"], jobs=1)
        )

    def test_json_has_integers_only(self) -> None:
        def reject_float(token: str) -> object:
            raise AssertionError(f"浮動小数点がある: {token}")

        obj = json.loads(render_json(run(PRESETS["tiny"])), parse_float=reject_float)
        assert obj["bench_version"] == 1
        assert obj["preset"]["seeds"] == [0, 3]
        assert set(obj["solvers"]) == set(SOLVERS)
        assert obj["solvers"]["cpsat"]["det_time_limit_ms"] == 5000

    def test_json_has_no_wall_clock_fields(self) -> None:
        text = render_json(run(PRESETS["tiny"]))
        assert "elapsed" not in text and "wall" not in text and "duration" not in text


class TestCli:
    def test_writes_json_and_markdown_and_prints_the_table(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "bench"
        assert main(["bench", "--preset", "tiny", "--seeds", "2", "--out", str(out)]) == 0
        captured = capsys.readouterr()
        assert (out / "bench.md").read_text(encoding="utf-8") == captured.out
        assert json.loads((out / "bench.json").read_text(encoding="utf-8"))["preset"]["seeds"] == [
            0,
            2,
        ]
        assert "最適性を証明できたシード" in captured.out
        assert "2/2" in captured.err  # 進捗は標準エラー

    def test_invalid_seeds_exits_with_an_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["bench", "--preset", "tiny", "--seeds", "0"]) == 2
        assert "エラー" in capsys.readouterr().err


def test_presets_are_consistent() -> None:
    for name, preset in PRESETS.items():
        assert preset.name == name
        assert preset.seeds >= 1
    assert PRESETS["large"].cpsat.det_time_limit_ms > PRESETS["small"].cpsat.det_time_limit_ms


def test_a_makespan_below_the_bound_stops_the_benchmark() -> None:
    """下界を下回る makespan は、下界かソルバの誤り。黙って集計せず、止める。"""
    s = generate(0)
    with pytest.raises(BoundViolationError, match="下回った"):
        _row(s, GreedySolver().solve(s), bound=10**6)
