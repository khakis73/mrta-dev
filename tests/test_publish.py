"""公開物(`mrta publish`)のテスト(ADR-0006・0013)。

公開ログは、ビルドのたびに生成する。CP-SAT の Plan は、OR-Tools の版・OS で変わりうる
(ADR-0007)ので、**公開ログ全体のバイト一致は検査しない**。代わりに、構造・シナリオの一致・指標の値を見る。
(決定的な greedy・hungarian の手作りシナリオだけ、golden とのバイト一致を残す。)
"""

import json
from pathlib import Path
from typing import TypedDict

import pytest

from mrta.cli import main
from mrta.logio import check_log_structure
from mrta.model import Plan
from mrta.publish import DEMO_NAME, MANIFEST_NAME, MANIFEST_VERSION, examples
from mrta.sim import simulate
from mrta.solvers import ALL_SOLVERS, ONLINE_SOLVERS, SOLVER_SUMMARIES, SOLVERS
from tests.golden_cases import GOLDEN_DIR


class LogEntry(TypedDict):
    file: str
    solver: str


class Default(TypedDict):
    a: str
    b: str


class ManifestExample(TypedDict):
    id: str
    title: str
    dynamic: bool
    default: Default
    description: str
    logs: list[LogEntry]


class Manifest(TypedDict):
    manifest_version: int
    solvers: dict[str, str]
    examples: list[ManifestExample]


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("published") / "data"
    assert main(["publish", "--out", str(path)]) == 0
    return path


@pytest.fixture(scope="module")
def manifest(out: Path) -> Manifest:
    loaded: Manifest = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    return loaded


def log_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def line_of(path: Path, kind: str) -> dict[str, object]:
    return next(o for o in log_lines(path) if o["type"] == kind)


class TestManifest:
    def test_is_version_2_with_examples(self, manifest: Manifest) -> None:
        assert manifest["manifest_version"] == MANIFEST_VERSION == 2
        assert manifest["examples"]

    def test_is_written_deterministically(self, out: Path, tmp_path: Path) -> None:
        """マニフェストは(ログと違い)ソルバの結果に依らないので、バイト一致する。"""
        assert main(["publish", "--out", str(tmp_path / "again")]) == 0
        assert (out / MANIFEST_NAME).read_bytes() == (
            tmp_path / "again" / MANIFEST_NAME
        ).read_bytes()

    def test_every_example_has_two_or_more_logs_with_unique_solvers(
        self, manifest: Manifest
    ) -> None:
        for example in manifest["examples"]:
            solvers = [log["solver"] for log in example["logs"]]
            assert len(solvers) >= 2
            assert len(set(solvers)) == len(solvers), example["id"]

    def test_dynamic_flag_matches_the_example(self, manifest: Manifest) -> None:
        """マニフェストの dynamic は、例の実際の性質(到着があり、ローリング版を含む)と一致する。"""
        by_id = {e.id: e for e in examples()}
        for example in manifest["examples"]:
            has_rolling = any(log["solver"].startswith("rolling-") for log in example["logs"])
            assert example["dynamic"] == by_id[example["id"]].dynamic == has_rolling, example["id"]

    def test_solver_summaries_cover_exactly_the_published_solvers(self, manifest: Manifest) -> None:
        """画面に出すソルバの説明。公開するソルバの分だけ、元(mrta.solvers.info)と同じ文面で出す。"""
        published = {log["solver"] for e in manifest["examples"] for log in e["logs"]}
        assert set(manifest["solvers"]) == published
        for name, summary in manifest["solvers"].items():
            assert summary == SOLVER_SUMMARIES[name], name

    def test_every_example_has_a_description_for_the_screen(self, manifest: Manifest) -> None:
        """画面に出る説明。id だけが並ぶと、何を見ればよいか分からない(ADR-0013)。"""
        by_id = {e.id: e for e in examples()}
        for example in manifest["examples"]:
            assert example["description"].strip(), example["id"]
            assert example["description"] == by_id[example["id"]].note, example["id"]

    def test_the_default_pair_names_two_distinct_published_solvers(
        self, manifest: Manifest
    ) -> None:
        for example in manifest["examples"]:
            names = {log["solver"] for log in example["logs"]}
            a, b = example["default"]["a"], example["default"]["b"]
            assert a != b and a in names and b in names, example["id"]


class TestComposition:
    def test_five_static_and_three_dynamic_examples(self) -> None:
        items = examples()
        assert [e.dynamic for e in items].count(False) == 5
        assert [e.dynamic for e in items].count(True) == 3
        assert len({e.id for e in items}) == len(items)  # id は重複しない

    def test_static_examples_publish_every_static_solver_and_no_rolling_solver(self) -> None:
        """静的なシナリオでは、ローリングは基底と同じ結果(ADR-0012)。同じ行を増やさない。"""
        for e in examples():
            if not e.dynamic:
                assert e.solver_names() == sorted(SOLVERS), e.id

    def test_dynamic_examples_add_the_rolling_solvers_after_the_static_ones(self) -> None:
        for e in examples():
            if e.dynamic:
                assert e.solver_names() == sorted(SOLVERS) + sorted(ONLINE_SOLVERS), e.id

    def test_dynamic_examples_really_have_arrivals_and_static_ones_do_not(self) -> None:
        for e in examples():
            released_later = any(t.release_time > 0 for t in e.scenario.tasks)
            assert released_later == e.dynamic, e.id

    def test_every_registered_solver_is_published_somewhere(self) -> None:
        """ソルバを登録すれば、公開物に出る(静的は全ての例、ローリングは動的な例)。"""
        published = {s for e in examples() for s in e.solver_names()}
        assert published == set(ALL_SOLVERS)

    def test_the_default_pair_is_published_for_each_example(self) -> None:
        for e in examples():
            assert set(e.default) <= set(e.solver_names()), e.id
            assert e.default[0] != e.default[1], e.id


class TestLogs:
    def test_every_manifest_log_exists_and_is_valid(self, out: Path, manifest: Manifest) -> None:
        for example in manifest["examples"]:
            for log in example["logs"]:
                check_log_structure((out / log["file"]).read_text(encoding="utf-8"))

    def test_the_manifest_solver_is_the_solver_name_in_the_log(
        self, out: Path, manifest: Manifest
    ) -> None:
        for example in manifest["examples"]:
            for log in example["logs"]:
                solver_line = line_of(out / log["file"], "solver")
                assert solver_line["name"] == log["solver"], log["file"]

    def test_logs_of_an_example_share_the_same_scenario(
        self, out: Path, manifest: Manifest
    ) -> None:
        """比較の前提(ADR-0004): 同じ例のログは scenario 行が一致する(どの2本でも比較できる)。"""
        for example in manifest["examples"]:
            lines = {
                json.dumps(line_of(out / log["file"], "scenario"), sort_keys=True)
                for log in example["logs"]
            }
            assert len(lines) == 1, example["id"]

    def test_recorded_metrics_equal_a_fresh_simulation(self, out: Path, manifest: Manifest) -> None:
        """バイト一致の代わり: ログの makespan と総移動距離は、測り直した値に一致する。"""
        by_id = {e.id: e for e in examples()}
        for example in manifest["examples"]:
            scenario = by_id[example["id"]].scenario
            for log in example["logs"]:
                routes = line_of(out / log["file"], "plan")["routes"]
                assert isinstance(routes, dict)
                metrics = line_of(out / log["file"], "metrics")
                fresh = simulate(scenario, Plan({k: tuple(v) for k, v in routes.items()})).metrics
                assert metrics["makespan"] == fresh.makespan, log["file"]
                assert metrics["total_distance"] == fresh.total_distance, log["file"]

    def test_the_static_scenarios_logs_of_deterministic_solvers_are_the_golden_files(
        self, out: Path
    ) -> None:
        """greedy・hungarian は決定的なので、手作りシナリオの公開ログは golden とバイト一致する。"""
        for solver in ("greedy", "hungarian"):
            name = f"greedy-trap-{solver}.jsonl"
            assert (out / name).read_bytes() == (GOLDEN_DIR / name).read_bytes()


def makespan(out: Path, example_id: str, solver: str) -> int:
    value = line_of(out / f"{example_id}-{solver}.jsonl", "metrics")["makespan"]
    assert isinstance(value, int)
    return value


class TestExamplesShowWhatTheyClaim:
    """各例の「ねらい」(note)が、公開ログで成り立つ。成り立たなくなったら、例を選び直す。

    決定的なソルバ(greedy・hungarian・ローリングのそれら)と、静的な最適値(CP-SAT)は値で固定する。
    動的なシナリオでの静的 CP-SAT は、到着を見ないので、静的な最適の中のどれが選ばれるかで
    動的な makespan が変わりうる(版・OS で変わりうる)。その行は、大小関係だけを固定する。
    """

    def test_examples_are_what_their_ids_say(self) -> None:
        by_id = {e.id: e for e in examples()}
        assert by_id["seed1"].scenario.seed == 1
        assert by_id["static-spread"].scenario.seed == 11
        assert by_id["static-15tasks"].scenario.seed == 1
        assert len(by_id["static-15tasks"].scenario.tasks) == 15
        assert by_id["dynamic-rolling-wins"].scenario.seed == 11
        assert by_id["dynamic-rolling-loses"].scenario.seed == 3
        assert len(by_id["dynamic-tiny"].scenario.robots) == 3
        assert len(by_id["dynamic-tiny"].scenario.tasks) == 5

    def test_static_spread_has_the_largest_gap(self, out: Path) -> None:
        got = {s: makespan(out, "static-spread", s) for s in ("greedy", "hungarian", "cpsat")}
        assert got == {"greedy": 47, "hungarian": 25, "cpsat": 20}
        assert makespan(out, "static-spread", "routing") <= got["hungarian"]

    def test_static_15tasks(self, out: Path) -> None:
        got = {s: makespan(out, "static-15tasks", s) for s in ("greedy", "hungarian", "cpsat")}
        assert got == {"greedy": 61, "hungarian": 57, "cpsat": 40}

    def test_rolling_wins_big(self, out: Path) -> None:
        wins = "dynamic-rolling-wins"
        assert makespan(out, wins, "greedy") == 65
        assert makespan(out, wins, "rolling-greedy") == 30
        # 静的な CP-SAT(到着を無視した「最適」)を、ローリング CP-SAT が大きく下回る。
        assert makespan(out, wins, "rolling-cpsat") < makespan(out, wins, "cpsat")

    def test_rolling_loses_whatever_the_base_is(self, out: Path) -> None:
        loses = "dynamic-rolling-loses"
        assert makespan(out, loses, "greedy") == 41
        assert makespan(out, loses, "rolling-greedy") == 46
        assert makespan(out, loses, "rolling-cpsat") > makespan(out, loses, "cpsat")

    def test_dynamic_tiny(self, out: Path) -> None:
        assert makespan(out, "dynamic-tiny", "greedy") == 40
        assert makespan(out, "dynamic-tiny", "rolling-greedy") == 33


class TestDescriptionsStateTrueNumbers:
    """説明(画面に出る)に書いた数値は、公開ログの値と一致する。ずれたら、説明か例を直す。

    動的な例の静的 CP-SAT の値(38)は、静的な最適の中のどれが選ばれるかで変わりうる(版・OS)。
    説明に数値を書いた行は、その値で固定する(ずれたら気づくため)。
    """

    @pytest.mark.parametrize(
        ("example_id", "numbers"),
        [
            ("static-spread", {"greedy": 47, "hungarian": 25, "routing": 20, "cpsat": 20}),
            ("static-15tasks", {"greedy": 61, "hungarian": 57, "routing": 40, "cpsat": 40}),
            ("dynamic-rolling-wins", {"cpsat": 38, "rolling-cpsat": 25}),
            (
                "dynamic-rolling-loses",
                {"greedy": 41, "rolling-greedy": 46, "cpsat": 41, "rolling-cpsat": 46},
            ),
            ("dynamic-tiny", {"greedy": 40, "rolling-greedy": 33}),
        ],
    )
    def test_numbers_in_the_description_match_the_logs(
        self, out: Path, manifest: Manifest, example_id: str, numbers: dict[str, int]
    ) -> None:
        description = next(e["description"] for e in manifest["examples"] if e["id"] == example_id)
        for solver, value in numbers.items():
            assert makespan(out, example_id, solver) == value, (example_id, solver)
            assert str(value) in description, (example_id, solver, value)


def test_demo_log_is_kept_for_the_viewer_default(out: Path) -> None:
    check_log_structure((out / DEMO_NAME).read_text(encoding="utf-8"))


def test_deterministic_solvers_publish_the_same_bytes_every_time(tmp_path: Path) -> None:
    """greedy・hungarian とそのローリング版は決定的。CP-SAT・Routing は版・OS で変わりうる。"""
    assert main(["publish", "--out", str(tmp_path / "a")]) == 0
    assert main(["publish", "--out", str(tmp_path / "b")]) == 0
    for e in examples():
        for solver in ("greedy", "hungarian", "rolling-greedy", "rolling-hungarian"):
            if solver in e.solver_names():
                name = e.log_name(solver)
                assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
