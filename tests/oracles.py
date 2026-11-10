"""テストのオラクル(全探索)。ソルバの外にある独立した検証に使う。"""

from itertools import permutations, product

from mrta.model import Plan, Scenario
from mrta.sim import simulate


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
