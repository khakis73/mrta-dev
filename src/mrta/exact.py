"""小さなシナリオの厳密なオフライン最適(全探索。ADR-0012)。

全ての割当 × 実行順を `simulate` で評価した、最小の makespan。到着時刻 `release_time` と
ロボットの `ready_at` を含む実行の意味(ADR-0003・0011・0012)で評価するので、
**動的な問題の、全タスクを事前に知るオフラインの最適**になる。

動的なベンチマークの小さな規模で、下界(= 最適値)として使う。大きな規模では組み合わせが
爆発するので、計算量の上限を超えたら例外にする(到着時刻つきの CP-SAT は作らない。ADR-0012)。
"""

from itertools import permutations, product
from math import factorial

from mrta.model import ModelError, Plan, Scenario
from mrta.sim import simulate

MAX_PLANS = 100_000


class TooLargeError(ModelError):
    """全探索の対象が大きすぎる。"""


def plan_count_upper_bound(n_tasks: int, n_robots: int) -> int:
    """適格性を無視した、Plan の数(タスクを台に振り分け、台ごとに並べる) = (n+R-1)! / (R-1)!。"""
    return factorial(n_tasks + n_robots - 1) // factorial(n_robots - 1)


def offline_optimum(scenario: Scenario, *, max_plans: int = MAX_PLANS) -> int:
    """全タスクを事前に知るオフラインの、最小の makespan。タスクが無ければ 0。"""
    bound = plan_count_upper_bound(len(scenario.tasks), len(scenario.robots))
    if bound > max_plans:
        raise TooLargeError(
            f"全探索の対象が大きすぎる: タスク {len(scenario.tasks)} 件・ロボット "
            f"{len(scenario.robots)} 台で最大 {bound} 通り(上限 {max_plans})"
        )
    robots = [r.id for r in sorted(scenario.robots, key=lambda r: r.id)]
    options = [[r.id for r in scenario.eligible_robots(t)] for t in scenario.tasks]
    best: int | None = None
    for assignment in product(*options):
        groups: dict[str, list[str]] = {robot_id: [] for robot_id in robots}
        for task, robot_id in zip(scenario.tasks, assignment, strict=True):
            groups[robot_id].append(task.id)
        for orders in product(*(permutations(groups[robot_id]) for robot_id in robots)):
            plan = Plan(dict(zip(robots, orders, strict=True)))
            makespan = simulate(scenario, plan).metrics.makespan
            if best is None or makespan < best:
                best = makespan
    return 0 if best is None else best
