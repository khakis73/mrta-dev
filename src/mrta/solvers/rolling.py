"""ローリングホライズン: 到着のたびに、既知で未確定のタスクを静的ソルバで解き直す(ADR-0012)。

- **エポック** = タスクの到着時刻(重複を除いて昇順)。
- エポック `T` で、まず**確定**する: 各ロボットの待ち行列の先頭から、出発時刻が `T` **より前**の
  タスクを確定する(出発 = `max(ロボットが空く時刻, 到着)`)。確定したタスクは変えない
  (移動の途中で行き先を変えない)。`T` ちょうどに出発するタスクは確定せず、`T` の情報で解き直せる。
- 次に**解き直す**: 未確定のタスク(待ち行列にあるもの + `T` までに到着したもの)を、基底の
  静的ソルバに渡す。
  入力は、ロボットの `start` = 確定したタスクの終点、`ready_at` = `max(空く時刻, T)` のシナリオ。
  得た `Plan` で待ち行列を置き換える。
- 最後のエポックの後、残りの待ち行列を全て確定する。結果の `Plan` = 確定した順序。

実行の式(出発・移動・作業)を、ここでも持つ(貪欲法と同じ二重実装。ADR-0003)。
結果の `Plan` を `simulate` したときの各ロボットの完了時刻が、ここで追う時刻と一致することを、
テストで確かめている。ソルバはシミュレータを知らない(ADR-0003)。
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType

from mrta.model import Plan, Point, Scenario, manhattan, travel_ticks
from mrta.solvers.base import ConfigValue, Solver, require_solvable


@dataclass(slots=True)
class _State:
    position: Point
    free_at: int  # 確定した仕事が終わる時刻(出発できる最も早い時刻)
    committed: list[str]  # 確定したタスク(実行順)
    queue: list[str]  # 未確定のタスク(直近の解き直しで決まった実行順)


@dataclass(frozen=True, slots=True)
class RollingResult:
    plan: Plan
    solves: int  # 基底のソルバを呼んだ回数(= エポックの数)
    # ロボットの完了時刻(モデルの値)。タスクが無いロボットは 0。テストがシミュレータと突き合わせる。
    finish_times: Mapping[str, int]


def solve_rolling(scenario: Scenario, base: Solver) -> RollingResult:
    require_solvable(scenario)

    robots = sorted(scenario.robots, key=lambda r: r.id)
    tasks = {t.id: t for t in scenario.tasks}
    speed = {r.id: r.speed for r in robots}
    # ロボットは `ready_at` までは出発できない(元のシナリオの値。ADR-0012)。
    state = {r.id: _State(r.start, r.ready_at, [], []) for r in robots}

    def depart(robot_id: str, task_id: str) -> int:
        return max(state[robot_id].free_at, tasks[task_id].release_time)

    def commit_before(limit: int | None) -> None:
        """出発が `limit` より前のタスクを確定する(`None` なら全て)。"""
        for r in robots:
            st = state[r.id]
            while st.queue and (limit is None or depart(r.id, st.queue[0]) < limit):
                task_id = st.queue.pop(0)
                task = tasks[task_id]
                start = depart(r.id, task_id)
                st.free_at = (
                    start
                    + travel_ticks(manhattan(st.position, task.location), speed[r.id])
                    + task.service_time
                )
                st.position = task.location
                st.committed.append(task_id)

    solves = 0
    for epoch in sorted({t.release_time for t in scenario.tasks}):
        commit_before(epoch)
        committed = {task_id for st in state.values() for task_id in st.committed}
        # 未確定のタスクを到着順(同時刻は ID 順)に渡す。Scenario の並びに依存しない。
        pending = sorted(
            (t for t in scenario.tasks if t.release_time <= epoch and t.id not in committed),
            key=lambda t: (t.release_time, t.id),
        )
        sub = replace(
            scenario,
            robots=tuple(
                replace(r, start=state[r.id].position, ready_at=max(state[r.id].free_at, epoch))
                for r in robots
            ),
            tasks=tuple(replace(t, release_time=0) for t in pending),  # 全て既知
        )
        plan = base.solve(sub)
        solves += 1
        for r in robots:
            state[r.id].queue = list(plan.routes[r.id])
    commit_before(None)

    return RollingResult(
        plan=Plan({r.id: tuple(state[r.id].committed) for r in robots}),
        solves=solves,
        # タスクが無いロボットの完了時刻は 0(ready_at は完了時刻にならない。ADR-0012)。
        finish_times={r.id: state[r.id].free_at if state[r.id].committed else 0 for r in robots},
    )


class RollingSolver:
    """基底の静的ソルバを、ローリングホライズンで使う `Solver`(`Scenario → Plan` の純関数)。"""

    def __init__(self, base: Solver) -> None:
        self._base = base
        self.name = f"rolling-{base.name}"

    @property
    def config(self) -> Mapping[str, ConfigValue]:
        # 基底の設定に、基底の名前を足す(整数・文字列のみ。ADR-0004)。
        return MappingProxyType({**self._base.config, "base": self._base.name})

    def solve(self, scenario: Scenario) -> Plan:
        return solve_rolling(scenario, self._base).plan


def rolling_of(factory: Callable[[], Solver]) -> Callable[[], Solver]:
    """基底のソルバの生成関数から、ローリング版の生成関数を作る。"""

    def make() -> Solver:
        return RollingSolver(factory())

    return make
