"""貪欲法に固有のテスト(共通の契約は test_solver_contract.py)。

期待値は、ADR-0003 の実行の意味(移動 = ceil(距離/速度)、作業 = service_time、帰還なし)から
手計算した。コードの出力をそのまま写したものではない。
"""

from dataclasses import replace

from hypothesis import given

from mrta.model import CARRY, MANIPULATE, Plan, Robot, RobotKind, Scenario, Task
from mrta.sim import simulate
from mrta.solvers import GreedySolver
from tests.builders import robot, scenario, task
from tests.strategies import scenarios


def routes(robots: tuple[Robot, ...], tasks: tuple[Task, ...]) -> dict[str, list[str]]:
    plan = GreedySolver().solve(scenario(robots, tasks))
    return {k: list(v) for k, v in plan.routes.items()}


def test_single_robot_gets_every_task_in_scenario_order() -> None:
    result = routes(
        (robot("r0"),),
        (task("t0", location=(3, 4)), task("t1", location=(1, 1)), task("t2", location=(9, 9))),
    )
    assert result == {"r0": ["t0", "t1", "t2"]}


def test_chooses_the_robot_that_finishes_earlier() -> None:
    # t0 (1,0), 作業1。 r0: 距離1/速度1=1 → 1+1=2。 r1: 距離17/速度5=ceil 4 → 4+1=5。 → r0
    # t1 (9,8), 作業1。 r0 は (1,0) から距離16 → 2+16+1=19。 r1: 距離1/速度5=1 → 1+1=2。 → r1
    result = routes(
        (
            robot("r0", start=(0, 0), speed=1),
            robot("r1", start=(9, 9), speed=5),
        ),
        (
            task("t0", location=(1, 0), service_time=1),
            task("t1", location=(9, 8), service_time=1),
        ),
    )
    assert result == {"r0": ["t0"], "r1": ["t1"]}


def test_balances_load_between_identical_robots() -> None:
    # 同じ場所の2台と、同じ場所の2タスク。2つ目を同じロボットに積むと作業時間ぶん遅れる。
    result = routes(
        (robot("r0"), robot("r1")),
        (task("t0", service_time=3), task("t1", service_time=3)),
    )
    assert result == {"r0": ["t0"], "r1": ["t1"]}


def test_ties_are_broken_by_lexicographic_robot_id() -> None:
    # 同条件のロボットなら、IDの辞書順で小さいほう。"r10" < "r2"(数値順ではない: ADR-0004)
    result = routes((robot("r2"), robot("r10")), (task("t0"),))
    assert result == {"r10": ["t0"], "r2": []}


def test_skill_and_capacity_restrict_the_choice() -> None:
    manipulator = robot(
        "r1",
        kind=RobotKind.MOBILE_MANIPULATOR,
        start=(9, 9),
        speed=1,
        capacity=2,
        skills=frozenset({CARRY, MANIPULATE}),
    )
    fast_amr = robot("r0", start=(3, 4), speed=5, capacity=9)  # 目の前にいて速いが、操作できない
    result = routes(
        (fast_amr, manipulator),
        (
            task("t0", location=(3, 4), required_skill=MANIPULATE, demand=2),
            task("t1", location=(3, 4), demand=3),  # 容量2のマニピュレーターでは運べない
        ),
    )
    assert result == {"r0": ["t1"], "r1": ["t0"]}


@given(s=scenarios())
def test_every_choice_minimizes_the_simulated_finish_time(s: Scenario) -> None:
    """貪欲法の内部の見積もりと、シミュレータの結果が一致していることの検証。

    貪欲法の選択を1つずつ再現し、各タスクについて「適格な各ロボットの経路の末尾に足したときの
    完了時刻」を**シミュレータで**測る。貪欲法が選んだロボットが、その最小(同点はID順)であること。
    完了時刻の計算を二重実装している(ADR-0003)ため、両者のずれをここで検出する。
    貪欲法は到着時刻を見ない静的なソルバ(ADR-0011)なので、静的なシナリオ(到着 0)で確かめる。
    """
    s = replace(s, tasks=tuple(replace(t, release_time=0) for t in s.tasks))
    plan = GreedySolver().solve(s)
    owner = {tid: rid for rid, tids in plan.routes.items() for tid in tids}

    routes: dict[str, tuple[str, ...]] = {r.id: () for r in s.robots}
    done: tuple[Task, ...] = ()
    for t in s.tasks:
        sub = replace(s, tasks=(*done, t))

        def finish_if_appended(r: Robot, t: Task = t, sub: Scenario = sub) -> int:
            candidate = {**routes, r.id: (*routes[r.id], t.id)}
            return simulate(sub, Plan(candidate)).metrics.per_robot[r.id].finish

        _, expected_id = min((finish_if_appended(r), r.id) for r in s.eligible_robots(t))
        assert owner[t.id] == expected_id
        routes[owner[t.id]] = (*routes[owner[t.id]], t.id)
        done = (*done, t)
