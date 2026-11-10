"""ローリングホライズン(ADR-0012)のテスト。

保証すること: 有効な Plan、決定性、駆動役の内部時刻とシミュレータの一致、静的では基底と同じ結果。
保証しないこと: 静的ソルバより良いこと(窓が短いと劣りうる)。それは統計(ベンチマーク)で見る。
"""

from dataclasses import replace

import pytest
from hypothesis import given, settings

from mrta.model import Plan, Scenario, validate_plan
from mrta.scenario import GeneratorConfig, generate
from mrta.sim import simulate
from mrta.solvers import (
    ALL_SOLVERS,
    ONLINE_SOLVERS,
    SOLVERS,
    GreedySolver,
    HungarianSolver,
    RollingSolver,
    solve_rolling,
)
from mrta.solvers.base import UnsolvableError
from tests.builders import robot, scenario, task
from tests.strategies import scenarios, seeds, small_scenarios

# 基底。速い2つ(貪欲法・ハンガリアン法)は広く、遅い2つ(CP-SAT・Routing)は小さな規模で確かめる。
FAST = (GreedySolver, HungarianSolver)


def static_copy(s: Scenario) -> Scenario:
    return replace(s, tasks=tuple(replace(t, release_time=0) for t in s.tasks))


def sorted_by_id(s: Scenario) -> Scenario:
    return replace(s, tasks=tuple(sorted(s.tasks, key=lambda t: t.id)))


class TestRegistry:
    def test_online_solvers_wrap_every_static_solver(self) -> None:
        assert set(ONLINE_SOLVERS) == {f"rolling-{n}" for n in SOLVERS}
        assert set(ALL_SOLVERS) == set(SOLVERS) | set(ONLINE_SOLVERS)

    def test_static_registry_is_unchanged(self) -> None:
        """静的なプリセットの表に、基底と同じ結果の行を増やさない(ADR-0012)。"""
        assert not any(name.startswith("rolling-") for name in SOLVERS)

    def test_name_and_config_name_the_base(self) -> None:
        solver = RollingSolver(GreedySolver())
        assert solver.name == "rolling-greedy"
        assert dict(solver.config) == {"base": "greedy"}
        cpsat = ONLINE_SOLVERS["rolling-cpsat"]()
        assert cpsat.config["base"] == "cpsat"
        assert cpsat.config["det_time_limit_ms"] == 5000  # 基底の設定を残す


class TestInternalTimelineMatchesTheSimulator:
    """駆動役は実行の式を二重に持つ。そのずれを検出する(ADR-0003・0012)。"""

    @pytest.mark.parametrize("base", FAST)
    @given(s=scenarios(max_ready_at=30))
    @settings(max_examples=60)
    def test_finish_times_equal_the_simulated_ones(self, base: type, s: Scenario) -> None:
        result = solve_rolling(s, base())
        validate_plan(s, result.plan)
        simulated = {k: v.finish for k, v in simulate(s, result.plan).metrics.per_robot.items()}
        assert dict(result.finish_times) == simulated

    @given(s=small_scenarios(max_robots_per_kind=2, max_tasks=5, max_arrival_window=30))
    @settings(max_examples=25)
    def test_holds_for_the_slow_solvers_too(self, s: Scenario) -> None:
        for name in ("cpsat", "routing"):
            result = solve_rolling(s, SOLVERS[name]())
            simulated = {k: v.finish for k, v in simulate(s, result.plan).metrics.per_robot.items()}
            assert dict(result.finish_times) == simulated


class TestReducesToTheBaseWhenStatic:
    @pytest.mark.parametrize("base", FAST)
    @given(s=scenarios(max_ready_at=30))
    @settings(max_examples=60)
    def test_one_epoch_gives_the_base_plan(self, base: type, s: Scenario) -> None:
        """全タスクの到着が 0 なら、エポックは1つで、基底のソルバと同じ結果になる。"""
        static = sorted_by_id(static_copy(s))  # 駆動役はタスクを ID 順(到着が同じなら)で渡す
        result = solve_rolling(static, base())
        assert result.solves == (1 if static.tasks else 0)
        assert result.plan == base().solve(static)

    @pytest.mark.parametrize("name", ["cpsat", "routing"])
    @given(s=small_scenarios(max_robots_per_kind=2, max_tasks=5, max_ready_at=20))
    @settings(max_examples=15)
    def test_slow_solvers_too(self, name: str, s: Scenario) -> None:
        static = sorted_by_id(s)
        assert solve_rolling(static, SOLVERS[name]()).plan == SOLVERS[name]().solve(static)


class TestEpochs:
    def test_one_solve_per_distinct_release_time(self) -> None:
        s = scenario(
            (robot("r0"), robot("r1", start=(9, 9))),
            (
                task("t0", release_time=0),
                task("t1", release_time=0),  # t0 と同時: 1回にまとめる
                task("t2", release_time=5),
                task("t3", release_time=9),
            ),
        )
        assert solve_rolling(s, GreedySolver()).solves == 3

    def test_no_tasks_means_no_solves_and_empty_routes(self) -> None:
        result = solve_rolling(scenario((robot("r0"), robot("r1")), ()), GreedySolver())
        assert result.solves == 0
        assert dict(result.plan.routes) == {"r0": (), "r1": ()}
        assert dict(result.finish_times) == {"r0": 0, "r1": 0}

    def test_a_task_that_departs_before_the_epoch_is_committed_not_reassigned(self) -> None:
        """r0 は t0 (到着 0) に向かって出発済み。後から来た t1 の解き直しで t0 を奪われない。"""
        s = scenario(
            (robot("r0", speed=1), robot("r1", speed=1, start=(9, 0))),
            (
                task("t0", location=(2, 0), service_time=1, release_time=0),
                task("t1", location=(3, 0), service_time=1, release_time=1),
            ),
        )
        plan = solve_rolling(s, GreedySolver()).plan
        assert plan.routes["r0"][0] == "t0"  # t0 は最初のエポックで r0 に決まり、確定される

    def test_a_task_departing_exactly_at_the_epoch_is_replanned_not_committed(self) -> None:
        """出発が T ちょうどのタスクは確定しない('<')。T の時点の新しい情報で解き直せる(ADR-0012)。

        4台・6タスクの生成シナリオ(シード 11、窓 10)。ハンガリアン法を基底にすると、
        '<' なら makespan 17、'<=' (T ちょうどに出発するタスクも確定する)なら 20 になる。
        貪欲法を基底にすると差は出ない(60シードで 0 件)ので、ハンガリアン法を使う。
        """
        config = GeneratorConfig(
            n_amr=2, n_mobile_manipulators=2, n_tasks=6, width=10, height=10, arrival_window=10
        )
        s = generate(11, config)
        result = solve_rolling(s, HungarianSolver())
        assert simulate(s, result.plan).metrics.makespan == 17
        assert dict(result.plan.routes) == {
            "r0": ("t2", "t5"),
            "r1": ("t0", "t3"),
            "r2": (),
            "r3": ("t4", "t1"),
        }


class TestTaskOrderPassedToTheBase:
    def test_the_base_receives_pending_tasks_in_arrival_order_not_id_order(self) -> None:
        """基底(貪欲法)はタスクの渡し順に依存する。駆動役は到着順(同時刻は ID 順)で渡す(ADR-0012)。

        1 AMR + 1 マニピュレーター・5タスクの生成シナリオ(シード 2、窓 10)。到着順なら makespan 23、
        ID 順だけで渡すと 29 になる(300シードのうち約4割で Plan が変わる)。
        """
        config = GeneratorConfig(
            n_amr=1, n_mobile_manipulators=1, n_tasks=5, width=10, height=10, arrival_window=10
        )
        s = generate(2, config)
        result = solve_rolling(s, GreedySolver())
        assert dict(result.plan.routes) == {"r0": ("t0", "t2", "t4"), "r1": ("t3", "t1")}
        assert simulate(s, result.plan).metrics.makespan == 23


class TestContractProperties:
    @pytest.mark.parametrize("base", FAST)
    @given(seed=seeds)
    def test_ignores_the_order_of_tasks_in_the_scenario(self, base: type, seed: int) -> None:
        """タスクの並びに依存しない(到着順、同時刻は ID 順で基底に渡す)。"""
        s = generate(seed, GeneratorConfig(n_tasks=8, arrival_window=20))
        reversed_tasks = replace(s, tasks=s.tasks[::-1])
        assert solve_rolling(reversed_tasks, base()).plan == solve_rolling(s, base()).plan

    def test_unservable_task_raises(self) -> None:
        s = scenario((robot("r0"),), (task("t0", demand=6),))
        with pytest.raises(UnsolvableError, match="t0"):
            solve_rolling(s, GreedySolver())

    def test_the_input_scenario_is_not_modified(self) -> None:
        s = generate(0, GeneratorConfig(arrival_window=20))
        before = replace(s)
        solve_rolling(s, GreedySolver())
        assert s == before


class TestDynamicBehaviour:
    """予備測定(ADR-0012)の要点を、固定シードの平均で確かめる(保証ではなく期待)。"""

    def test_rolling_beats_the_static_plan_on_average_when_arrivals_are_spread(self) -> None:
        static, rolling = [], []
        for seed in range(15):
            s = generate(seed, GeneratorConfig(arrival_window=20))
            static.append(simulate(s, GreedySolver().solve(s)).metrics.makespan)
            rolling.append(
                simulate(s, ONLINE_SOLVERS["rolling-greedy"]().solve(s)).metrics.makespan
            )
        assert sum(rolling) < sum(static)


def test_returns_a_plan_type() -> None:
    s = generate(0, GeneratorConfig(arrival_window=20))
    assert isinstance(solve_rolling(s, GreedySolver()).plan, Plan)


@given(s=scenarios(max_ready_at=30))
@settings(max_examples=30)
def test_rolling_with_distinct_bases_all_serve_every_task(s: Scenario) -> None:
    for base in FAST:
        validate_plan(s, solve_rolling(s, base()).plan)
