"""CP-SAT ソルバ固有のテスト(ADR-0007)。

正しさの根拠は3つ。どれもソルバの外にある独立した検証:
- 全探索の最適解との一致(シミュレータで評価する)
- モデルが報告した値とシミュレータの値の一致(モデルの誤りの検出器)
- 他のソルバより悪くならない
"""

from itertools import permutations, product

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mrta.catalog import SCENARIOS
from mrta.model import Plan, Scenario, validate_plan
from mrta.scenario import GeneratorConfig, generate
from mrta.sim import simulate
from mrta.solvers import SOLVERS, CpSatConfig, CpSatSolver, solve_cpsat
from mrta.solvers.base import UnsolvableError
from tests.builders import robot, scenario, task
from tests.strategies import seeds, small_scenarios


def objective(s: Scenario, plan: Plan) -> tuple[int, int]:
    """(makespan, 総移動距離)。シミュレータで評価する。"""
    m = simulate(s, plan).metrics
    return (m.makespan, m.total_distance)


def all_plans(s: Scenario) -> list[Plan]:
    """全ての有効な Plan(割当 × 実行順)。小さなシナリオ専用。"""
    robots = [r.id for r in s.robots]
    options = [[r.id for r in s.eligible_robots(t)] for t in s.tasks]
    plans: list[Plan] = []
    for assignment in product(*options):
        groups: dict[str, list[str]] = {robot_id: [] for robot_id in robots}
        for t, robot_id in zip(s.tasks, assignment, strict=True):
            groups[robot_id].append(t.id)
        per_robot = [list(permutations(groups[robot_id])) for robot_id in robots]
        for orders in product(*per_robot):
            plans.append(Plan(dict(zip(robots, orders, strict=True))))
    return plans


class TestMatchesBruteForce:
    @given(s=small_scenarios(max_robots_per_kind=2, max_tasks=5))
    def test_lexicographic_optimum(self, s: Scenario) -> None:
        """全探索の最小の (makespan, 総移動距離) と一致する。最適性も証明される。"""
        result = solve_cpsat(s)
        expected = min(objective(s, plan) for plan in all_plans(s))
        assert objective(s, result.plan) == expected
        assert result.status == "optimal"
        assert result.makespan_bound == result.makespan == expected[0]


class TestModelAgreesWithSimulator:
    @given(s=small_scenarios(max_robots_per_kind=3, max_tasks=8))
    def test_reported_values_match_simulation(self, s: Scenario) -> None:
        """モデルの値とシミュレータの値が一致する。一致しなければモデルが誤っている
        (例: 未使用ロボットの閉路を禁じ忘れると、不正な Plan と小さすぎる目的値が出る)。"""
        result = solve_cpsat(s)
        validate_plan(s, result.plan)
        assert objective(s, result.plan) == (result.makespan, result.total_distance)

    @given(s=small_scenarios(max_robots_per_kind=2, max_tasks=6))
    def test_bound_never_exceeds_makespan(self, s: Scenario) -> None:
        result = solve_cpsat(s)
        assert 0 <= result.makespan_bound <= result.makespan
        assert (result.status == "optimal") == (result.makespan_bound == result.makespan)


class TestOracle:
    @given(
        s=small_scenarios(max_robots_per_kind=3, max_tasks=8),
        other=st.sampled_from(["greedy", "hungarian"]),
    )
    def test_never_worse_than_other_solvers(self, s: Scenario, other: str) -> None:
        """最適性が証明できたとき、他のソルバの makespan は CP-SAT 以上。"""
        result = solve_cpsat(s)
        assert result.status == "optimal"
        assert objective(s, SOLVERS[other]().solve(s))[0] >= result.makespan


@pytest.mark.parametrize(("name", "makespan"), [("greedy-trap", 6), ("skill-trap", 3)])
def test_handmade_scenarios_reach_the_optimum(name: str, makespan: int) -> None:
    result = solve_cpsat(SCENARIOS[name]())
    assert result.status == "optimal"
    assert result.makespan == makespan


def test_default_generated_scenario_is_solved_to_optimality() -> None:
    """既定の生成シナリオ(4台・10タスク)。最適値はソルバの版が変わっても同じ(Plan は問わない)。"""
    s = generate(0)
    result = solve_cpsat(s)
    assert result.status == "optimal"
    assert result.makespan == 30
    assert result.total_distance == 88
    assert objective(s, result.plan) == (30, 88)


class TestTimeLimit:
    big = generate(3, GeneratorConfig(n_amr=3, n_mobile_manipulators=3, n_tasks=20))

    @pytest.mark.parametrize("limit_ms", [1, 50, 500])
    def test_always_returns_a_valid_plan_no_worse_than_greedy(self, limit_ms: int) -> None:
        """打ち切られても、有効な Plan が返り、貪欲法より悪くならない(ヒントとフォールバック)。"""
        s = self.big
        result = solve_cpsat(s, CpSatConfig(det_time_limit_ms=limit_ms))
        validate_plan(s, result.plan)
        assert objective(s, result.plan) == (result.makespan, result.total_distance)
        greedy_makespan = objective(s, SOLVERS["greedy"]().solve(s))[0]
        assert result.makespan <= greedy_makespan
        assert 0 <= result.makespan_bound <= result.makespan

    def test_is_reproducible_when_cut_off(self) -> None:
        """決定的時間の打ち切りは、同じ入力から同じ結果になる(壁時計ではない)。"""
        config = CpSatConfig(det_time_limit_ms=200)
        first = solve_cpsat(self.big, config)
        assert solve_cpsat(self.big, config) == first


class TestEdges:
    def test_no_tasks(self) -> None:
        result = solve_cpsat(scenario((robot("r0"), robot("r1")), ()))
        assert dict(result.plan.routes) == {"r0": (), "r1": ()}
        assert (result.status, result.makespan, result.makespan_bound) == ("optimal", 0, 0)
        assert result.total_distance == 0

    def test_robot_without_eligible_tasks_gets_an_empty_route(self) -> None:
        # r1 は容量が足りず、どのタスクも担当できない。
        s = scenario((robot("r0"), robot("r1", capacity=1)), (task("t0", demand=5),))
        plan = solve_cpsat(s).plan
        assert plan.routes["r0"] == ("t0",)
        assert plan.routes["r1"] == ()

    def test_unservable_task_raises(self) -> None:
        s = scenario((robot("r0"),), (task("t0", demand=6),))
        with pytest.raises(UnsolvableError, match="t0"):
            solve_cpsat(s)

    @given(seed=seeds)
    def test_ignores_task_order(self, seed: int) -> None:
        """タスクの並びに依存しない(貪欲法と違い、入力を ID 順に正規化する)。"""
        s = generate(seed, GeneratorConfig(n_tasks=6))
        reversed_tasks = Scenario(
            seed=s.seed, width=s.width, height=s.height, robots=s.robots, tasks=s.tasks[::-1]
        )
        assert solve_cpsat(reversed_tasks) == solve_cpsat(s)


class TestConfig:
    def test_log_config_is_explicit(self) -> None:
        assert CpSatSolver().config == {
            "num_workers": 1,
            "random_seed": 0,
            "det_time_limit_ms": 5000,
        }
        assert CpSatSolver(CpSatConfig(det_time_limit_ms=100)).config["det_time_limit_ms"] == 100

    @pytest.mark.parametrize("bad", [0, -1, True, 1.5])
    def test_rejects_invalid_limit(self, bad: object) -> None:
        with pytest.raises(ValueError, match="det_time_limit_ms"):
            CpSatConfig(det_time_limit_ms=bad)  # type: ignore[arg-type]
