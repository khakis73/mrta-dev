"""貪欲法に固有のテスト(共通の契約は test_solver_contract.py)。

期待値は、ADR-0003 の実行の意味(移動 = ceil(距離/速度)、作業 = service_time、帰還なし)から
手計算した。コードの出力をそのまま写したものではない。
"""

from mrta.model import CARRY, MANIPULATE, Robot, RobotKind, Task
from mrta.solvers import GreedySolver
from tests.builders import robot, scenario, task


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
