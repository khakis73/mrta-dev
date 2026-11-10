"""Routing ソルバ固有のテスト(ADR-0009)。

保証しないこと: 最適性、貪欲法より悪くならないこと。だから、シード単位ではなく
(1) モデルとシミュレータの一致、(2) CP-SAT の最適値以上、(3) 手作りシナリオ、(4) 平均、で確かめる。
"""

from statistics import mean

import pytest
from hypothesis import given, settings

from mrta.catalog import SCENARIOS
from mrta.model import CARRY, MANIPULATE, Scenario, validate_plan
from mrta.scenario import GeneratorConfig, generate
from mrta.sim import simulate
from mrta.solvers import SOLVERS, RoutingConfig, RoutingSolver, solve_cpsat, solve_routing
from mrta.solvers.base import UnsolvableError
from tests.builders import robot, scenario, task
from tests.strategies import seeds, small_scenarios


class TestModelAgreesWithSimulator:
    @settings(max_examples=40)
    @given(s=small_scenarios(max_robots_per_kind=3, max_tasks=8))
    def test_reported_values_match_simulation(self, s: Scenario) -> None:
        """モデルの値とシミュレータの値が一致する。
        コールバックの例外が費用 0 になる不具合(ADR-0009)は、ここで検出される。"""
        result = solve_routing(s)
        validate_plan(s, result.plan)
        metrics = simulate(s, result.plan).metrics
        assert result.makespan == metrics.makespan
        assert result.total_time == metrics.busy_total  # 弧の費用 = 移動 + 作業

    def test_costs_are_not_zero(self) -> None:
        """費用 0 の再発を直接検出する(目的関数・累積時間が 0 と報告されていた)。"""
        s = scenario((robot("r0", speed=1),), (task("t0", location=(3, 4), service_time=2),))
        result = solve_routing(s)
        assert result.makespan == 9  # 7 + 2
        assert result.total_time == 9


class TestOracle:
    @settings(max_examples=40)
    @given(s=small_scenarios(max_robots_per_kind=2, max_tasks=6))
    def test_never_better_than_the_proven_optimum(self, s: Scenario) -> None:
        """CP-SAT が最適性を証明したとき、Routing の makespan はそれ以上。"""
        optimum = solve_cpsat(s)
        assert optimum.status == "optimal"
        assert solve_routing(s).makespan >= optimum.makespan


@pytest.mark.parametrize(("name", "makespan"), [("greedy-trap", 6), ("skill-trap", 3)])
def test_handmade_scenarios_reach_the_optimum(name: str, makespan: int) -> None:
    assert solve_routing(SCENARIOS[name]()).makespan == makespan


def test_beats_greedy_on_average_over_fixed_seeds() -> None:
    """保証ではなく期待: 4台・10タスクのシード 0〜9 で、平均が貪欲法より小さい。"""
    routing, greedy = [], []
    for seed in range(10):
        s = generate(seed)
        routing.append(simulate(s, SOLVERS["routing"]().solve(s)).metrics.makespan)
        greedy.append(simulate(s, SOLVERS["greedy"]().solve(s)).metrics.makespan)
    assert mean(routing) < mean(greedy)


class TestTermination:
    def test_terminates_when_only_one_robot_can_do_the_task(self) -> None:
        """適格なロボットが1台だけだと、探索空間が極端に小さい。解の数の上限には届かず、
        分岐数の上限(branch_limit)が無いと探索が終わらない(ADR-0009)。"""
        both = frozenset({CARRY, MANIPULATE})
        s = scenario(
            (robot("r0"), robot("r1", skills=both, capacity=3)),
            (task("t0", required_skill=MANIPULATE),),
        )
        result = solve_routing(s)
        assert dict(result.plan.routes) == {"r0": (), "r1": ("t0",)}

    @settings(max_examples=40)
    @given(seed=seeds)
    def test_terminates_with_a_single_eligible_robot_per_task(self, seed: int) -> None:
        s = generate(
            seed,
            GeneratorConfig(n_amr=1, n_mobile_manipulators=1, n_tasks=2, manipulate_percent=100),
        )
        validate_plan(s, solve_routing(s).plan)


class TestEdges:
    def test_no_tasks(self) -> None:
        result = solve_routing(scenario((robot("r0"), robot("r1")), ()))
        assert dict(result.plan.routes) == {"r0": (), "r1": ()}
        assert (result.makespan, result.total_time) == (0, 0)

    def test_robot_without_eligible_tasks_gets_an_empty_route(self) -> None:
        s = scenario((robot("r0"), robot("r1", capacity=1)), (task("t0", demand=5),))
        assert solve_routing(s).plan.routes["r1"] == ()

    def test_unservable_task_raises(self) -> None:
        s = scenario((robot("r0"),), (task("t0", demand=6),))
        with pytest.raises(UnsolvableError, match="t0"):
            solve_routing(s)

    @settings(max_examples=40)
    @given(seed=seeds)
    def test_ignores_task_order(self, seed: int) -> None:
        s = generate(seed, GeneratorConfig(n_tasks=6))
        reversed_tasks = Scenario(
            seed=s.seed, width=s.width, height=s.height, robots=s.robots, tasks=s.tasks[::-1]
        )
        assert solve_routing(reversed_tasks) == solve_routing(s)


class TestConfig:
    def test_log_config_is_explicit(self) -> None:
        assert RoutingSolver().config == {
            "first_solution": "path_cheapest_arc",
            "metaheuristic": "guided_local_search",
            "solution_limit": 300,
            "branch_limit": 20000,
            "span_cost_coefficient": 100,
        }

    @pytest.mark.parametrize("field", ["solution_limit", "branch_limit", "span_cost_coefficient"])
    @pytest.mark.parametrize("bad", [0, -1, True, 1.5])
    def test_rejects_invalid_values(self, field: str, bad: object) -> None:
        with pytest.raises(ValueError, match=field):
            RoutingConfig(**{field: bad})  # type: ignore[arg-type]
