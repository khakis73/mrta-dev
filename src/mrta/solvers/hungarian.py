"""ハンガリアン法: ラウンドごとに「ロボット ↔ タスク」の最小費用割当を解く(ADR-0005)。

- 各ラウンドで、費用 = 「そのタスクを経路の末尾に足したときのロボットの完了時刻」とし、
  その総和を最小にする。割当可能(スキル・容量を満たす)なペアの数は最大にする。
  選ばれたペアを確定し、残りで繰り返す。
- ラウンドの内側は最適だが、ラウンド間は貪欲。また目的は完了時刻の総和で、評価指標の
  完了時間(makespan)とは別物。全体の最適は保証しない。
- ロボットとタスクを ID の辞書順に並べてから解く。`Scenario` の並び順に依存しない。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from mrta.model import Plan, Point, Robot, Scenario, Task, is_eligible, manhattan, travel_ticks
from mrta.solvers.assignment import solve_assignment
from mrta.solvers.base import ConfigValue, require_solvable


@dataclass(slots=True)
class _RobotState:
    position: Point
    finish: int


def _finish_if_added(robot: Robot, state: _RobotState, task: Task) -> int:
    return (
        state.finish
        + travel_ticks(manhattan(state.position, task.location), robot.speed)
        + task.service_time
    )


class HungarianSolver:
    name = "hungarian"
    config: Mapping[str, ConfigValue] = MappingProxyType({})

    def solve(self, scenario: Scenario) -> Plan:
        require_solvable(scenario)

        robots = sorted(scenario.robots, key=lambda r: r.id)
        remaining = sorted(scenario.tasks, key=lambda t: t.id)
        states = {r.id: _RobotState(position=r.start, finish=0) for r in robots}
        routes: dict[str, list[str]] = {r.id: [] for r in robots}

        while remaining:
            for robot, task in self._round(robots, remaining, states):
                states[robot.id] = _RobotState(
                    position=task.location, finish=_finish_if_added(robot, states[robot.id], task)
                )
                routes[robot.id].append(task.id)
                remaining.remove(task)

        return Plan({robot_id: tuple(ids) for robot_id, ids in routes.items()})

    def _round(
        self,
        robots: list[Robot],
        tasks: list[Task],
        states: dict[str, _RobotState],
    ) -> list[tuple[Robot, Task]]:
        """1ラウンド分の確定する (ロボット, タスク) を返す。"""
        costs: list[list[int | None]] = [
            [_finish_if_added(r, states[r.id], t) if is_eligible(r, t) else None for t in tasks]
            for r in robots
        ]
        finite = [c for row in costs for c in row if c is not None]
        # 割当可能なペアだけの任意の割当の総和より大きくする(割当可能なペアの数を最大にするため)。
        big = min(len(robots), len(tasks)) * (max(finite) + 1) + 1
        matrix = [[big if c is None else c for c in row] for row in costs]

        if len(robots) <= len(tasks):
            pairs = [(i, j) for i, j in enumerate(solve_assignment(matrix))]
        else:
            transposed = [list(col) for col in zip(*matrix, strict=True)]
            pairs = [(i, j) for j, i in enumerate(solve_assignment(transposed))]

        chosen = [(robots[i], tasks[j]) for i, j in pairs if costs[i][j] is not None]
        # 各ラウンドで進む: 残りのタスクには適格なロボットがいる(require_solvable)ので、
        # 割当可能なペアが1つ以上ある。
        assert chosen, "ラウンドが進まない"
        return chosen
