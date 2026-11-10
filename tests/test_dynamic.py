"""動的なタスク到着(ADR-0011)のテスト。

- 実行の意味(出発前の待機のみ)は、手計算の例と性質で確かめる。
- 静的なシナリオ(全タスクの release_time が 0)の結果・ログは変わらない(回帰)。
"""

from dataclasses import replace
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mrta.bounds import task_lower_bound
from mrta.cli import main
from mrta.logio import render_log
from mrta.model import ModelError, Plan, Scenario
from mrta.scenario import GeneratorConfig, generate
from mrta.sim import Segment, SegmentKind, simulate
from mrta.solvers import GreedySolver
from tests.builders import robot, scenario, task
from tests.strategies import scenarios, scenarios_with_plans, seeds

MOVE, SERVICE = SegmentKind.MOVE, SegmentKind.SERVICE


def make_static(s: Scenario) -> Scenario:
    return replace(s, tasks=tuple(replace(t, release_time=0) for t in s.tasks))


class TestExecutionSemantics:
    def test_robot_waits_before_departing_until_the_task_is_released(self) -> None:
        # r0: 速度2、(0,0) 発。t0=(3,4) 作業2、到着 10。距離7 → ceil(7/2)=4。
        # 10 まで待ち、移動 [10,14]、作業 [14,16]。完了 16。待機は稼働に含めない: busy=6。
        s = scenario(
            (robot("r0", speed=2),),
            (task("t0", location=(3, 4), service_time=2, release_time=10),),
        )
        result = simulate(s, Plan({"r0": ("t0",)}))
        assert result.segments == (
            Segment("r0", MOVE, "t0", (0, 0), (3, 4), 10, 14),
            Segment("r0", SERVICE, "t0", (3, 4), (3, 4), 14, 16),
        )
        m = result.metrics
        assert (m.makespan, m.total_distance, m.busy_total, m.available_total) == (16, 7, 6, 16)
        assert m.per_robot["r0"].finish == 16
        assert m.per_robot["r0"].busy == 6
        assert m.utilization == Fraction(6, 16)  # 待機のぶん、静的(1)より下がる

    def test_no_waiting_when_the_robot_is_still_busy_at_the_release_time(self) -> None:
        # t0 (到着 0): 移動 [0,4]、作業 [4,6]。
        # t1 (到着 3 < 6) は同じ位置なので、待たずに作業のみ [6,7]。
        s = scenario(
            (robot("r0", speed=2),),
            (
                task("t0", location=(3, 4), service_time=2),
                task("t1", location=(3, 4), service_time=1, release_time=3),
            ),
        )
        segments = simulate(s, Plan({"r0": ("t0", "t1")})).segments
        assert [(g.task, g.kind, g.t0, g.t1) for g in segments] == [
            ("t0", MOVE, 0, 4),
            ("t0", SERVICE, 4, 6),
            ("t1", SERVICE, 6, 7),
        ]

    def test_waits_between_tasks_when_the_next_one_is_not_yet_released(self) -> None:
        # t0 は 6 で完了。t1 (到着 20) は同じ位置: 20 まで待って、作業 [20,21]。完了 21。
        s = scenario(
            (robot("r0", speed=2),),
            (
                task("t0", location=(3, 4), service_time=2),
                task("t1", location=(3, 4), service_time=1, release_time=20),
            ),
        )
        result = simulate(s, Plan({"r0": ("t0", "t1")}))
        assert [(g.task, g.kind, g.t0, g.t1) for g in result.segments][-1] == (
            "t1",
            SERVICE,
            20,
            21,
        )
        m = result.metrics
        assert (m.makespan, m.busy_total, m.total_distance) == (21, 7, 7)

    def test_zero_travel_task_starts_service_at_the_release_time(self) -> None:
        s = scenario(
            (robot("r0", start=(3, 4)),),
            (task("t0", location=(3, 4), service_time=2, release_time=5),),
        )
        segments = simulate(s, Plan({"r0": ("t0",)})).segments
        assert segments == (Segment("r0", SERVICE, "t0", (3, 4), (3, 4), 5, 7),)

    def test_release_time_does_not_affect_other_robots(self) -> None:
        # ロボットは干渉しない: r1 の到着が遅くても、r0 の完了時刻は変わらない。
        s = scenario(
            (robot("r0", speed=1), robot("r1", start=(9, 9), speed=1)),
            (
                task("t0", location=(2, 0), service_time=1),
                task("t1", location=(9, 3), release_time=30),
            ),
        )
        m = simulate(s, Plan({"r0": ("t0",), "r1": ("t1",)})).metrics
        assert m.per_robot["r0"].finish == 3
        assert m.per_robot["r1"].finish == 30 + 6 + 2  # 到着 30 + 移動 6 + 作業 2


class TestProperties:
    @given(sp=scenarios_with_plans())
    def test_static_scenarios_are_unchanged(self, sp: tuple[Scenario, Plan]) -> None:
        """全タスクの release_time が 0 なら、待機は生じない(従来の結果と同じ)。"""
        s, plan = sp
        static = make_static(s)
        result = simulate(static, plan)
        assert all(x.busy == x.finish for x in result.metrics.per_robot.values())

    @given(sp=scenarios_with_plans())
    def test_release_times_only_delay_and_never_change_work_or_distance(
        self, sp: tuple[Scenario, Plan]
    ) -> None:
        """到着時刻は出発を遅らせるだけ。移動距離と稼働時間は変えず、完了時刻は短くならない。"""
        s, plan = sp
        dynamic, static = simulate(s, plan).metrics, simulate(make_static(s), plan).metrics
        assert dynamic.total_distance == static.total_distance
        assert dynamic.busy_total == static.busy_total
        assert dynamic.makespan >= static.makespan
        for robot_id, x in dynamic.per_robot.items():
            assert x.finish >= static.per_robot[robot_id].finish

    @given(sp=scenarios_with_plans())
    def test_a_robot_finishes_no_earlier_than_any_of_its_tasks_release_plus_work(
        self, sp: tuple[Scenario, Plan]
    ) -> None:
        s, plan = sp
        tasks = {t.id: t for t in s.tasks}
        finish = simulate(s, plan).metrics.per_robot
        for robot_id, ids in plan.routes.items():
            for task_id in ids:
                t = tasks[task_id]
                assert finish[robot_id].finish >= t.release_time + t.service_time


class TestGenerator:
    base = dict(width=10, height=10, n_amr=1, n_mobile_manipulators=1, n_tasks=3)

    def test_default_is_static(self) -> None:
        assert all(t.release_time == 0 for t in generate(0, GeneratorConfig(**self.base)).tasks)

    def test_pinned_snapshot_detects_rng_drift(self) -> None:
        """動的な到着の抽選は、既存の抽選の後に引く(ADR-0011)。値の固定で、順序の変更を検出する。"""
        s = generate(0, GeneratorConfig(**self.base, arrival_window=8))
        assert [(t.id, t.release_time) for t in s.tasks] == [("t0", 4), ("t1", 8), ("t2", 2)]

    @given(seed=seeds, window=st.integers(1, 40))
    def test_a_window_changes_nothing_but_the_release_times(self, seed: int, window: int) -> None:
        """静的なシナリオと、release_time 以外が同じ(乱数列を変えない)。"""
        config = GeneratorConfig(n_tasks=8)
        static, dynamic = (
            generate(seed, config),
            generate(seed, replace(config, arrival_window=window)),
        )
        assert dynamic.robots == static.robots
        assert make_static(dynamic) == static
        assert all(0 <= t.release_time <= window for t in dynamic.tasks)

    @pytest.mark.parametrize("window", [-1, 1.5, True])
    def test_rejects_an_invalid_window(self, window: object) -> None:
        with pytest.raises(ModelError, match="arrival_window"):
            GeneratorConfig(arrival_window=window)  # type: ignore[arg-type]


class TestLog:
    def test_release_time_is_omitted_when_zero_so_static_logs_do_not_change(self) -> None:
        s = generate(1, GeneratorConfig())
        assert "release_time" not in render_log(s, GreedySolver())

    def test_release_time_is_written_when_positive(self) -> None:
        s = scenario((robot("r0"),), (task("t0", release_time=7), task("t1")))
        text = render_log(s, GreedySolver())
        scenario_line = text.splitlines()[1]
        assert '"release_time":7' in scenario_line
        assert scenario_line.count("release_time") == 1  # t1 (0) には書かない

    @given(s=scenarios())
    def test_static_copy_of_any_scenario_has_no_release_time_in_the_log(self, s: Scenario) -> None:
        assert "release_time" not in render_log(make_static(s), GreedySolver())


class TestBound:
    def test_release_plus_service_is_a_floor(self) -> None:
        # 直行なら 6 だが、到着 10 + 作業 3 = 13 が床になる。
        s = scenario(
            (robot("r0"),), (task("t0", location=(3, 4), service_time=3, release_time=10),)
        )
        assert task_lower_bound(s) == 13

    def test_a_static_scenario_keeps_the_same_bound(self) -> None:
        s = scenario((robot("r0"),), (task("t0", location=(3, 4), service_time=3),))
        assert task_lower_bound(s) == 7  # ceil(7/2)=4 + 3

    @given(s=scenarios())
    def test_the_bound_never_decreases_with_release_times(self, s: Scenario) -> None:
        assert task_lower_bound(s) >= task_lower_bound(make_static(s))


class TestCli:
    def test_arrival_window_is_passed_through(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = [
            *("run", "--seed", "0", "--solver", "greedy", "--width", "10", "--height", "10"),
            *("--amr", "1", "--manipulators", "1", "--tasks", "3", "--arrival-window", "8"),
        ]
        assert main(args) == 0
        config = GeneratorConfig(**TestGenerator.base, arrival_window=8)
        assert capsys.readouterr().out == render_log(generate(0, config), GreedySolver())
