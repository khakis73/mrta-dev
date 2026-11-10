"""下界と下界ギャップのテスト(ADR-0008)。"""

from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mrta.bounds import BoundViolationError, gap, lower_bound, task_lower_bound
from mrta.model import MANIPULATE, Scenario
from mrta.sim import simulate
from mrta.solvers import SOLVERS, solve_cpsat
from tests.builders import robot, scenario, task
from tests.strategies import scenarios, small_scenarios


class TestTaskLowerBound:
    def test_hand_calculation(self) -> None:
        # r0: 速度2、開始 (0,0)。t0=(3,4): 距離7 → ceil(7/2)=4、作業2 → 6。t1=(1,0): 1 + 3 = 4。
        s = scenario(
            (robot("r0"),),
            (
                task("t0", location=(3, 4), service_time=2),
                task("t1", location=(1, 0), service_time=3),
            ),
        )
        assert task_lower_bound(s) == 6

    def test_uses_the_fastest_eligible_robot_per_task(self) -> None:
        # t0 は速い r1 が適格(距離6 → 2 + 作業1 = 3)。遅い r0 は 6 + 1 = 7 だが、min を取る。
        s = scenario(
            (robot("r0", speed=1), robot("r1", speed=3, start=(0, 0))),
            (task("t0", location=(6, 0), service_time=1),),
        )
        assert task_lower_bound(s) == 3

    def test_only_eligible_robots_count(self) -> None:
        # 操作は遅い r1 だけが可能。速い r0 は数えない。
        from mrta.model import CARRY

        s = scenario(
            (
                robot("r0", speed=5),
                robot("r1", speed=1, skills=frozenset({CARRY, MANIPULATE})),
            ),
            (task("t0", location=(4, 0), required_skill=MANIPULATE, service_time=1),),
        )
        assert task_lower_bound(s) == 5  # 4 + 1

    def test_no_tasks_is_zero(self) -> None:
        assert task_lower_bound(scenario((robot("r0"),), ())) == 0

    def test_unservable_task_raises(self) -> None:
        with pytest.raises(ValueError, match="t0"):
            task_lower_bound(scenario((robot("r0"),), (task("t0", demand=6),)))

    def test_lower_bound_takes_the_max_with_the_solver_bound(self) -> None:
        s = scenario((robot("r0"),), (task("t0", location=(3, 4), service_time=2),))
        assert lower_bound(s, 0) == 6  # 床
        assert lower_bound(s, 10) == 10


class TestIsValid:
    @given(s=scenarios(), solver=st.sampled_from(["greedy", "hungarian"]))
    def test_never_exceeds_a_heuristic_makespan_at_any_scale(
        self, s: Scenario, solver: str
    ) -> None:
        """大きな規模を含む任意のシナリオで、どのソルバの makespan も下回らない。"""
        plan = SOLVERS[solver]().solve(s)
        assert task_lower_bound(s) <= simulate(s, plan).metrics.makespan

    @given(s=small_scenarios(max_robots_per_kind=2, max_tasks=6))
    def test_never_exceeds_the_optimum(self, s: Scenario) -> None:
        """最適性を証明した CP-SAT(全探索と一致: tests/test_cpsat.py)の最適値を超えない。"""
        result = solve_cpsat(s)
        assert result.status == "optimal"
        assert task_lower_bound(s) <= result.makespan
        assert lower_bound(s, result.makespan_bound) == result.makespan


class TestGap:
    def test_exact_fraction(self) -> None:
        assert gap(30, 24) == Fraction(1, 4)
        assert gap(24, 24) == Fraction(0)

    def test_undefined_when_the_bound_is_zero(self) -> None:
        assert gap(0, 0) is None
        assert gap(5, 0) is None

    def test_makespan_below_the_bound_is_a_bug(self) -> None:
        with pytest.raises(BoundViolationError, match="下回った"):
            gap(23, 24)
