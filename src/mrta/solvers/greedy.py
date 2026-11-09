"""貪欲法: タスクを順に、完了時刻が最も早くなるロボットへ割り当てる。

- タスクは `Scenario.tasks` の順に処理する(**順序に依存する**のが、貪欲法の弱点)。
- 各タスクについて、適格なロボットのうち「そのタスクを経路の末尾に足したときの
  完了時刻」が最小のものを選ぶ。同点はロボットIDの辞書順(決定性)。
- 完了時刻の計算は、ADR-0003 の実行の意味(移動 → 作業、帰還なし)に従う。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from mrta.model import Plan, Point, Scenario, manhattan, travel_ticks
from mrta.solvers.base import ConfigValue, require_solvable


@dataclass(slots=True)
class _RobotState:
    position: Point
    finish: int


class GreedySolver:
    name = "greedy"
    config: Mapping[str, ConfigValue] = MappingProxyType({})

    def solve(self, scenario: Scenario) -> Plan:
        require_solvable(scenario)

        states = {r.id: _RobotState(position=r.start, finish=0) for r in scenario.robots}
        routes: dict[str, list[str]] = {r.id: [] for r in scenario.robots}

        for task in scenario.tasks:
            best_finish, best_id = min(
                (
                    states[r.id].finish
                    + travel_ticks(manhattan(states[r.id].position, task.location), r.speed)
                    + task.service_time,
                    r.id,
                )
                for r in scenario.eligible_robots(task)
            )
            states[best_id] = _RobotState(position=task.location, finish=best_finish)
            routes[best_id].append(task.id)

        return Plan({robot_id: tuple(ids) for robot_id, ids in routes.items()})
