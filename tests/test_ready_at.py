"""ロボットの空く時刻 `ready_at`(ADR-0012)のテスト。

- 実行の意味は手計算の例と性質で、4つのソルバの対応は「モデルとシミュレータの一致」と
  全探索との一致で確かめる。
- `ready_at = 0`(通常のシナリオ)の結果・ログは変わらない(既存のテストと golden が回帰)。
"""

from dataclasses import replace
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mrta.bounds import task_lower_bound
from mrta.logio import render_log
from mrta.model import ModelError, Plan, Scenario, validate_plan
from mrta.sim import Segment, SegmentKind, simulate
from mrta.solvers import SOLVERS, GreedySolver, solve_cpsat, solve_routing
from tests.builders import robot, scenario, task
from tests.oracles import all_plans, objective
from tests.strategies import scenarios, scenarios_with_plans, small_scenarios

MOVE, SERVICE = SegmentKind.MOVE, SegmentKind.SERVICE


def shifted(s: Scenario, k: int) -> Scenario:
    """全ロボットの `ready_at` を `k` だけ増やす。"""
    return replace(s, robots=tuple(replace(r, ready_at=r.ready_at + k) for r in s.robots))


class TestExecutionSemantics:
    def test_robot_departs_at_ready_at(self) -> None:
        # r0: 速度2、(0,0) 発、ready_at=10。t0=(3,4) 作業2、到着 0。移動 [10,14]、作業 [14,16]。
        s = scenario(
            (robot("r0", speed=2, ready_at=10),), (task("t0", location=(3, 4), service_time=2),)
        )
        result = simulate(s, Plan({"r0": ("t0",)}))
        assert result.segments == (
            Segment("r0", MOVE, "t0", (0, 0), (3, 4), 10, 14),
            Segment("r0", SERVICE, "t0", (3, 4), (3, 4), 14, 16),
        )
        m = result.metrics
        assert (m.makespan, m.total_distance, m.busy_total, m.available_total) == (16, 7, 6, 16)
        assert m.utilization == Fraction(6, 16)  # 待機は稼働に含めない

    def test_a_robot_without_tasks_finishes_at_zero_whatever_its_ready_at(self) -> None:
        s = scenario(
            (robot("r0", speed=2), robot("r1", ready_at=50)),
            (task("t0", location=(3, 4), service_time=2),),
        )
        m = simulate(s, Plan({"r0": ("t0",), "r1": ()})).metrics
        assert m.per_robot["r1"].finish == 0
        assert m.makespan == 6  # r1 の ready_at は makespan に効かない

    def test_the_later_of_ready_at_and_release_time_decides_the_departure(self) -> None:
        for ready_at, release, departs in [(10, 3, 10), (3, 10, 10), (5, 5, 5)]:
            s = scenario(
                (robot("r0", speed=2, ready_at=ready_at),),
                (task("t0", location=(3, 4), service_time=2, release_time=release),),
            )
            assert simulate(s, Plan({"r0": ("t0",)})).segments[0].t0 == departs

    def test_ready_at_applies_only_before_the_first_task(self) -> None:
        # 2つ目のタスクは直前の完了(6)から。ready_at(10)は最初のタスクの前だけ。
        s = scenario(
            (robot("r0", speed=2, ready_at=10),),
            (task("t0", location=(3, 4), service_time=2), task("t1", location=(3, 4))),
        )
        segments = simulate(s, Plan({"r0": ("t0", "t1")})).segments
        assert [(g.task, g.t0, g.t1) for g in segments] == [
            ("t0", 10, 14),
            ("t0", 14, 16),
            ("t1", 16, 18),
        ]

    @pytest.mark.parametrize("bad", [-1, 1.5, True])
    def test_rejects_an_invalid_ready_at(self, bad: object) -> None:
        with pytest.raises(ModelError, match="ready_at"):
            robot("r0", ready_at=bad)


class TestProperties:
    @given(sp=scenarios_with_plans())
    def test_ready_at_zero_is_the_default_and_changes_nothing(
        self, sp: tuple[Scenario, Plan]
    ) -> None:
        s, plan = sp
        assert all(r.ready_at == 0 for r in s.robots)
        assert simulate(shifted(s, 0), plan) == simulate(s, plan)

    @given(s=scenarios(max_ready_at=30))
    def test_ready_at_only_delays_and_never_changes_work_or_distance(self, s: Scenario) -> None:
        """ready_at は出発を遅らせるだけ。同じ Plan なら、移動距離と稼働時間は変わらない。"""
        ready_at_zero = replace(s, robots=tuple(replace(r, ready_at=0) for r in s.robots))
        plan = GreedySolver().solve(ready_at_zero)
        late, base = simulate(s, plan).metrics, simulate(ready_at_zero, plan).metrics
        assert late.total_distance == base.total_distance
        assert late.busy_total == base.busy_total
        assert late.makespan >= base.makespan


class TestSolversHonourReadyAt:
    """4つのソルバが `ready_at` を理解している(ADR-0012)。"""

    @given(s=scenarios(max_ready_at=30), k=st.integers(1, 30))
    @settings(max_examples=40)
    def test_uniform_shift_keeps_greedy_and_hungarian_plans(self, s: Scenario, k: int) -> None:
        """全ロボットの ready_at を一律に増やしても、比較の順序は変わらない。"""
        for name in ("greedy", "hungarian"):
            assert SOLVERS[name]().solve(shifted(s, k)) == SOLVERS[name]().solve(s)

    @given(s=small_scenarios(max_robots_per_kind=2, max_tasks=5, max_ready_at=30))
    @settings(max_examples=40)
    def test_cpsat_matches_the_brute_force_optimum_with_ready_at(self, s: Scenario) -> None:
        result = solve_cpsat(s)
        assert result.status == "optimal"
        assert objective(s, result.plan) == min(objective(s, p) for p in all_plans(s))
        assert result.makespan_bound == result.makespan

    @given(s=small_scenarios(max_robots_per_kind=3, max_tasks=8, max_ready_at=30))
    @settings(max_examples=40)
    def test_cpsat_and_routing_values_match_the_simulator(self, s: Scenario) -> None:
        """モデルの値とシミュレータの値が一致する(ready_at の足し方が正しい)。"""
        cp, rt = solve_cpsat(s), solve_routing(s)
        for plan in (cp.plan, rt.plan):
            validate_plan(s, plan)
        cp_metrics, rt_metrics = simulate(s, cp.plan).metrics, simulate(s, rt.plan).metrics
        assert (cp.makespan, cp.total_distance) == (cp_metrics.makespan, cp_metrics.total_distance)
        assert (rt.makespan, rt.total_time) == (rt_metrics.makespan, rt_metrics.busy_total)

    @given(
        s=small_scenarios(max_robots_per_kind=2, max_tasks=6, max_ready_at=0), k=st.integers(1, 30)
    )
    @settings(max_examples=40)
    def test_uniform_shift_adds_a_constant_to_the_cpsat_makespan(self, s: Scenario, k: int) -> None:
        """タスクが1件以上あれば、全ロボットの ready_at を k 増やすと最適 makespan も k 増える"""
        if not s.tasks:
            return
        assert solve_cpsat(shifted(s, k)).makespan == solve_cpsat(s).makespan + k


class TestHeterogeneousReadyAt:
    """ロボットごとに ready_at が違うと、選択が変わる(一律のずらしでは検出できない)。"""

    # 2台とも速度1、t0=(4,8) 作業1。r0 は (0,0) 発で距離12、ready_at=20 → 20 + 12 + 1 = 33。
    # r1 は (0,8) 発で距離4、ready_at=0 → 0 + 4 + 1 = 5。ready_at を見れば r1 が早い。
    # (ready_at を無視すると、距離は r1 のほうが短いので差は出ない。そこで次のケースも使う。)
    def make(self) -> Scenario:
        return scenario(
            (robot("r0", speed=1, ready_at=20), robot("r1", speed=1, start=(0, 8), ready_at=0)),
            (task("t0", location=(4, 8), service_time=1),),
        )

    @pytest.mark.parametrize("name", ["greedy", "hungarian", "cpsat", "routing"])
    def test_every_solver_prefers_the_robot_that_can_leave_earlier(self, name: str) -> None:
        plan = SOLVERS[name]().solve(self.make())
        assert dict(plan.routes) == {"r0": (), "r1": ("t0",)}

    @pytest.mark.parametrize("name", ["greedy", "hungarian"])
    def test_the_choice_flips_when_the_ready_at_of_the_other_robot_changes(self, name: str) -> None:
        # r0: ready_at 0 で 0 + 12 + 1 = 13、r1: ready_at 20 で 20 + 4 + 1 = 25 → r0 が早い。
        # (ready_at を無視すると r1 (4+1=5) が選ばれてしまう。)
        s = scenario(
            (robot("r0", speed=1, ready_at=0), robot("r1", speed=1, start=(0, 8), ready_at=20)),
            (task("t0", location=(4, 8), service_time=1),),
        )
        assert dict(SOLVERS[name]().solve(s).routes) == {"r0": ("t0",), "r1": ()}


class TestBound:
    def test_ready_at_is_added_to_the_direct_finish(self) -> None:
        s = scenario((robot("r0", ready_at=10),), (task("t0", location=(3, 4), service_time=3),))
        assert task_lower_bound(s) == 10 + 4 + 3  # ready_at + ceil(7/2) + 作業

    def test_the_faster_to_start_robot_decides_the_bound(self) -> None:
        s = scenario(
            (robot("r0", ready_at=20), robot("r1", ready_at=0, speed=1)),
            (task("t0", location=(3, 4), service_time=3),),
        )
        assert task_lower_bound(s) == min(20 + 4 + 3, 0 + 7 + 3)

    @given(s=scenarios(max_ready_at=30), solver=st.sampled_from(["greedy", "hungarian"]))
    def test_never_exceeds_the_makespan_of_any_solver(self, s: Scenario, solver: str) -> None:
        plan = SOLVERS[solver]().solve(s)
        assert task_lower_bound(s) <= simulate(s, plan).metrics.makespan


class TestLog:
    def test_ready_at_is_omitted_when_zero_and_written_when_positive(self) -> None:
        s = scenario((robot("r0"), robot("r1", ready_at=7)), (task("t0"),))
        scenario_line = render_log(s, GreedySolver()).splitlines()[1]
        assert scenario_line.count('"ready_at"') == 1
        assert '"ready_at":7' in scenario_line

    def test_a_scenario_without_ready_at_has_no_ready_at_in_the_log(self) -> None:
        s = scenario((robot("r0"), robot("r1")), (task("t0"),))
        assert "ready_at" not in render_log(s, GreedySolver())
