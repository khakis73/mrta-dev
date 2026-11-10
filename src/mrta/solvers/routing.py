"""Routing ソルバ: OR-Tools の車両経路ライブラリで、makespan を重みつきで最小化する(ADR-0009)。

- 車両 = ロボット。ノードは、タスク、各ロボットの開始位置、全車両で共通のダミー終端。
  終端への遷移の費用は 0(帰還しない、ADR-0003)。
- 遷移時間は車両ごとの**行列**で渡す。Python のコールバックは使わない。
  **コールバック内の例外は握りつぶされて費用 0 になる**(OR-Tools は、実際には通らない弧でも
  評価器を呼ぶ)。行列なら、コールバック自体が無いので、この不具合が起きない(ADR-0009)。
- 目的は `Σ(弧の費用) + K × 終端の累積時間の最大値`。開始時刻が全て 0 なので、後者は makespan。
  厳密な辞書式ではなく重みつきの和(第2項は総移動時間であり、総移動距離ではない)。
- 決定性: ID 順に正規化し、打ち切りは壁時計ではなく**解の数と分岐数**で行う。下界は返さない。
  解の数(`solution_limit`)だけでは、探索空間が極端に小さい問題(例: タスクを実行できるロボットが
  1台しかいない)で上限に達せず、探索が**終わらない**。分岐数の上限(`branch_limit`)が安全網になる。
- OR-Tools の Python バインディングの癖:
  - `SetAllowedVehiclesForIndex` は list を受け付けない → `VehicleVar().RemoveValue()` を使う。
  - モデルを閉じる前に `GetArcCostForVehicle` などを呼ぶとクラッシュする → 解いたあとにだけ読む。
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from mrta.model import Plan, Scenario, is_eligible, manhattan, require_int, travel_ticks
from mrta.solvers.base import ConfigValue, require_solvable

FIRST_SOLUTION = "path_cheapest_arc"
METAHEURISTIC = "guided_local_search"
DIMENSION = "time"


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    """結果を左右する設定。ログの solver 行に残る(ADR-0004)。"""

    solution_limit: int = 300  # 打ち切りは解の数と分岐数。壁時計は使わない(ADR-0009)
    branch_limit: int = 20000  # 通常は約 2000 分岐で終わる。小さな問題が終わらないのを防ぐ安全網
    span_cost_coefficient: int = 100

    def __post_init__(self) -> None:
        require_int("solution_limit", self.solution_limit, minimum=1)
        require_int("branch_limit", self.branch_limit, minimum=1)
        require_int("span_cost_coefficient", self.span_cost_coefficient, minimum=1)

    def as_log_config(self) -> Mapping[str, ConfigValue]:
        return MappingProxyType(
            {
                "first_solution": FIRST_SOLUTION,
                "metaheuristic": METAHEURISTIC,
                "solution_limit": self.solution_limit,
                "branch_limit": self.branch_limit,
                "span_cost_coefficient": self.span_cost_coefficient,
            }
        )


@dataclass(frozen=True, slots=True)
class RoutingResult:
    plan: Plan
    makespan: (
        int  # 時間次元の終端の累積時間の最大値(モデルの値。テストがシミュレータと突き合わせる)
    )
    total_time: int  # 弧の費用の総和(モデルの値。移動 + 作業)


def solve_routing(scenario: Scenario, config: RoutingConfig | None = None) -> RoutingResult:
    config = config or RoutingConfig()
    require_solvable(scenario)

    # 入力の正規化: Scenario の並びに依存しない。
    canonical = replace(
        scenario,
        robots=tuple(sorted(scenario.robots, key=lambda r: r.id)),
        tasks=tuple(sorted(scenario.tasks, key=lambda t: t.id)),
    )
    robots, tasks = canonical.robots, canonical.tasks
    if not tasks:
        return RoutingResult(Plan({r.id: () for r in robots}), makespan=0, total_time=0)

    n, r_count = len(tasks), len(robots)
    end = n + r_count  # 全車両で共通のダミー終端
    nodes = end + 1
    starts = list(range(n, n + r_count))  # 車両 v の開始ノードは n + v

    def location(node: int) -> tuple[int, int]:
        return tasks[node].location if node < n else robots[node - n].start

    # 遷移時間: 車両ごとの行列。終端・開始ノードが絡む遷移は 0(実際には通らない、または費用なし)。
    matrices = [
        [
            [
                travel_ticks(manhattan(location(a), location(b)), robot.speed)
                + tasks[b].service_time
                if a < end and b < n
                else 0
                for b in range(nodes)
            ]
            for a in range(nodes)
        ]
        for robot in robots
    ]

    manager = pywrapcp.RoutingIndexManager(nodes, r_count, starts, [end] * r_count)
    routing = pywrapcp.RoutingModel(manager)
    evaluators = [routing.RegisterTransitMatrix(m) for m in matrices]
    for v, evaluator in enumerate(evaluators):
        routing.SetArcCostEvaluatorOfVehicle(evaluator, v)
    routing.AddDimensionWithVehicleTransits(evaluators, 0, 10**9, True, DIMENSION)
    dimension = routing.GetDimensionOrDie(DIMENSION)
    dimension.SetGlobalSpanCostCoefficient(config.span_cost_coefficient)

    # 適格性(スキル・容量): 不適格な車両を除く。タスクは必ず訪問する(disjunction は置かない)。
    for t, task in enumerate(tasks):
        for v, robot in enumerate(robots):
            if not is_eligible(robot, task):
                routing.VehicleVar(manager.NodeToIndex(t)).RemoveValue(v)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.solution_limit = config.solution_limit
    routing.AddSearchMonitor(routing.solver().BranchesLimit(config.branch_limit))

    solution = routing.SolveWithParameters(params)
    if solution is None:
        raise RuntimeError(f"Routing が解を返さなかった(status={routing.status()})")

    routes: dict[str, tuple[str, ...]] = {}
    makespan = 0
    total_time = 0
    visited = 0
    for v, robot in enumerate(robots):
        index = routing.Start(v)
        ids: list[str] = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            next_index = solution.Value(routing.NextVar(index))
            if node < n:
                ids.append(tasks[node].id)
            total_time += matrices[v][node][manager.IndexToNode(next_index)]
            index = next_index
        makespan = max(makespan, solution.Value(dimension.CumulVar(index)))
        routes[robot.id] = tuple(ids)
        visited += len(ids)
    if visited != n:  # 通常は起きない。タスクを黙って落とさない。
        raise RuntimeError(f"Routing がタスクを落とした: {visited}/{n} 件しか訪問していない")

    return RoutingResult(Plan(routes), makespan=makespan, total_time=total_time)


class RoutingSolver:
    name = "routing"

    def __init__(self, config: RoutingConfig | None = None) -> None:
        self._config = config or RoutingConfig()

    @property
    def config(self) -> Mapping[str, ConfigValue]:
        return self._config.as_log_config()

    def solve(self, scenario: Scenario) -> Plan:
        return solve_routing(scenario, self._config).plan
