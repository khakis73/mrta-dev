"""CP-SAT ソルバ: makespan を最小化し、その中で総移動距離を最小化する(ADR-0007)。

- ロボットごとに、開始位置と適格なタスクを結ぶ**開いた経路**を `AddCircuit` で表す。
  アークの費用は「移動 + 作業」。待ちがない(ADR-0003)ので、完了時刻はアーク費用の和になる。
  `ready_at`(ADR-0012)は、開始位置から出る弧の費用に足す。使わないロボットは弧を通らないので、
  完了時刻は 0 のままになる(追加の変数は要らない)。到着時刻 `release_time` は見ない(ADR-0011)。
- 段階1で makespan を最小化し(貪欲法の解をヒントにする)、段階2で
  `makespan ≤ 段階1の値` の下で総移動距離を最小化する。
- 決定性: ロボットとタスクを ID の辞書順に並べ、`num_workers=1`、`random_seed=0`、
  打ち切りは壁時計ではなく**決定的時間**(`max_deterministic_time`)で行う。
- ソルバはシミュレータを知らない(ADR-0003)。モデルの値とシミュレータの一致は、テストで確かめる。
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from ortools.sat.python import cp_model

from mrta.model import (
    Plan,
    Robot,
    Scenario,
    Task,
    is_eligible,
    manhattan,
    require_int,
    travel_ticks,
)
from mrta.solvers.base import ConfigValue, require_solvable
from mrta.solvers.greedy import GreedySolver

NUM_WORKERS = 1
RANDOM_SEED = 0


@dataclass(frozen=True, slots=True)
class CpSatConfig:
    """結果を左右する設定。ログの solver 行に残る(ADR-0004)。

    `det_time_limit_ms` は**各段階**の打ち切り。値は「決定的時間の秒 × 1000」であり、
    壁時計のミリ秒ではない(マシンの速さ・負荷に依存しない作業量の単位)。
    """

    det_time_limit_ms: int = 5000

    def __post_init__(self) -> None:
        require_int("det_time_limit_ms", self.det_time_limit_ms, minimum=1)

    def as_log_config(self) -> Mapping[str, ConfigValue]:
        return {
            "num_workers": NUM_WORKERS,
            "random_seed": RANDOM_SEED,
            "det_time_limit_ms": self.det_time_limit_ms,
        }


@dataclass(frozen=True, slots=True)
class CpSatResult:
    plan: Plan
    status: Literal["optimal", "feasible"]  # optimal ⇔ makespan == makespan_bound
    makespan: int  # plan の完了時間(段階2の解。モデルの値で、テストがシミュレータと突き合わせる)
    makespan_bound: int  # 段階1が証明した下界
    total_distance: int  # plan の総移動距離(モデルの値)


@dataclass(frozen=True, slots=True)
class _RobotModel:
    robot: Robot
    tasks: tuple[Task, ...]  # 適格なタスク(ID順)。ノード j (1始まり) が tasks[j-1]
    arcs: Mapping[tuple[int, int], cp_model.IntVar]  # (i, j) → リテラル。(i, 0) は終端


def solve_cpsat(scenario: Scenario, config: CpSatConfig | None = None) -> CpSatResult:
    config = config or CpSatConfig()
    require_solvable(scenario)

    # 入力の正規化: Scenario の並びに依存しない(ヒントの貪欲法にも正規化後を渡す)。
    canonical = replace(
        scenario,
        robots=tuple(sorted(scenario.robots, key=lambda r: r.id)),
        tasks=tuple(sorted(scenario.tasks, key=lambda t: t.id)),
    )
    greedy = GreedySolver().solve(canonical)
    upper = _makespan_of(canonical, greedy)

    model = cp_model.CpModel()
    robot_models: list[_RobotModel] = []
    visits: dict[tuple[str, str], cp_model.IntVar] = {}  # (ロボットID, タスクID) → 訪問
    finishes: list[cp_model.IntVar] = []
    distance_terms: list[cp_model.LinearExpr] = []

    for robot in canonical.robots:
        tasks = tuple(t for t in canonical.tasks if is_eligible(robot, t))
        arcs = _add_circuit(model, robot, tasks, visits, finishes, distance_terms, upper)
        robot_models.append(_RobotModel(robot, tasks, arcs))
    for task in canonical.tasks:
        model.add_exactly_one(v for (_, task_id), v in visits.items() if task_id == task.id)

    makespan = model.new_int_var(0, upper, "makespan")
    model.add_max_equality(makespan, finishes)
    total_distance = sum(distance_terms)

    # 段階1: makespan の最小化。貪欲法の解をヒントにする(打ち切られても実行可能解が残る)。
    _hint(model, robot_models, visits, greedy)
    model.minimize(makespan)
    solver1 = _solver(config)
    status1 = solver1.solve(model)
    plan1 = greedy
    makespan1 = upper
    if status1 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        plan1 = _extract(solver1, robot_models)
        makespan1 = round(solver1.value(makespan))
    raw_bound = solver1.best_objective_bound
    bound = min(makespan1, max(0, math.ceil(raw_bound - 1e-6))) if math.isfinite(raw_bound) else 0

    # 段階2: makespan を上限に固定して、総移動距離を最小化する。
    model.clear_hints()  # type: ignore[no-untyped-call]  # ortools の型注釈が未整備
    _hint(model, robot_models, visits, plan1)
    model.add(makespan <= makespan1)
    model.minimize(total_distance)
    solver2 = _solver(config)
    status2 = solver2.solve(model)
    if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        plan = _extract(solver2, robot_models)
        final_makespan = round(solver2.value(makespan))
        final_distance = round(solver2.value(total_distance))
    else:
        # 予算が前処理で尽きたときなど。段階1の解(なければ貪欲法の解)を、値を計算し直して返す。
        plan = plan1
        final_makespan = _makespan_of(canonical, plan)
        final_distance = _distance_of(canonical, plan)

    return CpSatResult(
        plan=plan,
        status="optimal" if final_makespan == bound else "feasible",
        makespan=final_makespan,
        makespan_bound=bound,
        total_distance=final_distance,
    )


class CpSatSolver:
    name = "cpsat"

    def __init__(self, config: CpSatConfig | None = None) -> None:
        self._config = config or CpSatConfig()

    @property
    def config(self) -> Mapping[str, ConfigValue]:
        return self._config.as_log_config()

    def solve(self, scenario: Scenario) -> Plan:
        return solve_cpsat(scenario, self._config).plan


def _solver(config: CpSatConfig) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = NUM_WORKERS
    solver.parameters.random_seed = RANDOM_SEED
    solver.parameters.max_deterministic_time = config.det_time_limit_ms / 1000
    return solver


def _add_circuit(
    model: cp_model.CpModel,
    robot: Robot,
    tasks: tuple[Task, ...],
    visits: dict[tuple[str, str], cp_model.IntVar],
    finishes: list[cp_model.IntVar],
    distance_terms: list[cp_model.LinearExpr],
    upper: int,
) -> Mapping[tuple[int, int], cp_model.IntVar]:
    """1台ぶんの開いた経路。ノード0が開始位置、ノード j (≥1) が tasks[j-1]。"""

    def location(node: int) -> tuple[int, int]:
        return robot.start if node == 0 else tasks[node - 1].location

    n = len(tasks)
    literals: dict[tuple[int, int], cp_model.IntVar] = {}
    circuit: list[tuple[int, int, cp_model.LiteralT]] = []
    time_terms: list[cp_model.LinearExpr] = []

    for i in range(n + 1):
        for j in range(1, n + 1):
            if i == j:
                continue
            lit = model.new_bool_var(f"x_{robot.id}_{i}_{j}")
            literals[(i, j)] = lit
            circuit.append((i, j, lit))
            distance = manhattan(location(i), location(j))
            wait = robot.ready_at if i == 0 else 0  # 出発できるまで待つ(最初の弧にだけ足す)
            time_terms.append(
                lit * (wait + travel_ticks(distance, robot.speed) + tasks[j - 1].service_time)
            )
            distance_terms.append(lit * distance)
        # i → 0: i が最後のタスクなら経路の終端(費用0)。i=0 なら、ノード0の自己ループ
        # (何も訪問しないロボット)。自己ループを別に足してはいけない。
        end = model.new_bool_var(f"x_{robot.id}_{i}_0")
        literals[(i, 0)] = end
        circuit.append((i, 0, end))

    for j in range(1, n + 1):
        visit = model.new_bool_var(f"v_{robot.id}_{tasks[j - 1].id}")
        visits[(robot.id, tasks[j - 1].id)] = visit
        circuit.append((j, j, visit.negated()))  # 訪問しないなら自己ループ
        # AddCircuit は、ノード0の自己ループが真でも、ノード0を通らない別の閉路を許す。
        # 未使用のロボットがタスクを巡れてしまう(緩和)ので、禁じる。
        model.add_implication(visit, literals[(0, 0)].negated())
    model.add_circuit(circuit)

    finish = model.new_int_var(0, upper, f"finish_{robot.id}")
    model.add(finish == sum(time_terms))
    finishes.append(finish)
    return literals


def _hint(
    model: cp_model.CpModel,
    robot_models: list[_RobotModel],
    visits: dict[tuple[str, str], cp_model.IntVar],
    plan: Plan,
) -> None:
    for rm in robot_models:
        node = {t.id: j + 1 for j, t in enumerate(rm.tasks)}
        route = [node[task_id] for task_id in plan.routes[rm.robot.id]]
        used = set(zip([0, *route], [*route, 0], strict=True))
        for key, lit in rm.arcs.items():
            model.add_hint(lit, int(key in used))
        for task in rm.tasks:
            model.add_hint(visits[(rm.robot.id, task.id)], int(node[task.id] in route))


def _extract(solver: cp_model.CpSolver, robot_models: list[_RobotModel]) -> Plan:
    routes: dict[str, tuple[str, ...]] = {}
    for rm in robot_models:
        successor = {i: j for (i, j), lit in rm.arcs.items() if solver.boolean_value(lit)}
        ids: list[str] = []
        node = successor[0]
        while node != 0:
            ids.append(rm.tasks[node - 1].id)
            node = successor[node]
        routes[rm.robot.id] = tuple(ids)
    return Plan(routes)


def _finish_times(scenario: Scenario, plan: Plan) -> dict[str, int]:
    """貪欲法の Plan の各ロボットの完了時刻(変数の上限を決めるためだけに使う)。"""
    robots = {r.id: r for r in scenario.robots}
    tasks = {t.id: t for t in scenario.tasks}
    finishes: dict[str, int] = {}
    for robot_id, task_ids in plan.routes.items():
        robot = robots[robot_id]
        position, now = robot.start, (robot.ready_at if task_ids else 0)
        for task_id in task_ids:
            task = tasks[task_id]
            now += travel_ticks(manhattan(position, task.location), robot.speed)
            now += task.service_time
            position = task.location
        finishes[robot_id] = now
    return finishes


def _makespan_of(scenario: Scenario, plan: Plan) -> int:
    """変数の上限に使う、実行可能解(貪欲法の Plan)の完了時間。"""
    return max(_finish_times(scenario, plan).values())


def _distance_of(scenario: Scenario, plan: Plan) -> int:
    """Plan の総移動距離(マンハッタン距離の和)。フォールバックの値の計算にだけ使う。"""
    robots = {r.id: r for r in scenario.robots}
    tasks = {t.id: t for t in scenario.tasks}
    total = 0
    for robot_id, task_ids in plan.routes.items():
        position = robots[robot_id].start
        for task_id in task_ids:
            total += manhattan(position, tasks[task_id].location)
            position = tasks[task_id].location
    return total
