"""全探索のオフライン最適(ADR-0012)のテスト。

正しさの根拠は、ソルバの外にある独立した検証: 静的なシナリオでは CP-SAT の最適値と一致し、
動的では「全ての Plan の makespan の最小」と一致する(テストのオラクル `tests/oracles.py`)。
"""

from dataclasses import replace

import pytest
from hypothesis import given, settings

from mrta.exact import MAX_PLANS, TooLargeError, offline_optimum, plan_count_upper_bound
from mrta.model import Scenario
from mrta.scenario import GeneratorConfig, generate
from mrta.sim import simulate
from mrta.solvers import solve_cpsat
from tests.builders import robot, scenario, task
from tests.oracles import all_plans
from tests.strategies import small_scenarios


class TestAgreesWithIndependentChecks:
    @given(s=small_scenarios(max_robots_per_kind=2, max_tasks=5))
    @settings(max_examples=40)
    def test_static_optimum_equals_the_proven_cpsat_optimum(self, s: Scenario) -> None:
        result = solve_cpsat(s)
        assert result.status == "optimal"
        assert offline_optimum(s) == result.makespan

    @given(
        s=small_scenarios(
            max_robots_per_kind=2, max_tasks=5, max_arrival_window=30, max_ready_at=20
        )
    )
    @settings(max_examples=40)
    def test_equals_the_minimum_over_all_plans_with_arrivals_and_ready_at(
        self, s: Scenario
    ) -> None:
        expected = min(simulate(s, p).metrics.makespan for p in all_plans(s))
        assert offline_optimum(s) == expected

    @given(s=small_scenarios(max_robots_per_kind=2, max_tasks=5, max_arrival_window=30))
    @settings(max_examples=40)
    def test_is_never_below_the_static_optimum(self, s: Scenario) -> None:
        """到着は出発を遅らせるだけなので、動的な最適は静的な最適以上(ADR-0011)。"""
        relaxed = replace(s, tasks=tuple(replace(t, release_time=0) for t in s.tasks))
        assert offline_optimum(s) >= offline_optimum(relaxed)


class TestWorkedExamples:
    def test_waiting_for_a_release_is_part_of_the_optimum(self) -> None:
        # 1台。t0 は到着 10、(3,4) 速度2 作業2: 10 + 4 + 2 = 16。
        s = scenario(
            (robot("r0", speed=2),),
            (task("t0", location=(3, 4), service_time=2, release_time=10),),
        )
        assert offline_optimum(s) == 16

    def test_the_optimum_splits_work_across_robots(self) -> None:
        # 2台。同じ位置の2タスク(作業3ずつ): 1台に寄せると 6、2台に分けると 3。
        s = scenario(
            (robot("r0", speed=1), robot("r1", speed=1)),
            (
                task("t0", location=(0, 0), service_time=3),
                task("t1", location=(0, 0), service_time=3),
            ),
        )
        assert offline_optimum(s) == 3

    def test_no_tasks_is_zero(self) -> None:
        assert offline_optimum(scenario((robot("r0"),), ())) == 0


class TestSizeGuard:
    def test_plan_count_formula(self) -> None:
        # n 個のタスクを R 台に振り分け、台ごとに並べる = (n+R-1)! / (R-1)!
        assert plan_count_upper_bound(5, 3) == 2520
        assert plan_count_upper_bound(3, 1) == 6  # 1台なら n!
        assert plan_count_upper_bound(0, 4) == 1

    def test_the_formula_is_exact_without_eligibility_restrictions(self) -> None:
        s = generate(
            0, GeneratorConfig(n_amr=2, n_mobile_manipulators=0, n_tasks=4, manipulate_percent=0)
        )
        assert len(all_plans(s)) == plan_count_upper_bound(4, 2)

    def test_too_large_raises_instead_of_running_forever(self) -> None:
        s = generate(0, GeneratorConfig(n_amr=2, n_mobile_manipulators=2, n_tasks=10))
        with pytest.raises(TooLargeError, match="大きすぎる"):
            offline_optimum(s)

    def test_the_limit_is_configurable(self) -> None:
        s = generate(0, GeneratorConfig(n_amr=1, n_mobile_manipulators=1, n_tasks=4))
        with pytest.raises(TooLargeError):
            offline_optimum(s, max_plans=10)
        assert MAX_PLANS >= plan_count_upper_bound(6, 3)
