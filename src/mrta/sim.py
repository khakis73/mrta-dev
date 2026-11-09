"""シミュレータと指標(ADR-0003 の実行の意味、ADR-0004 の segment の規則)。

実行の意味は**ここだけが持つ**。ビューアは、ここが出す時間区間(segment)を読んで描くだけで、
移動時間などを再計算しない。

- ロボットは `start` から出発し、`Plan` の順に「移動 → 作業」を行う。最後のタスクの後は帰還しない。
- ロボット同士は干渉しない(待ちなし)。完了時刻は自分の経路だけで決まる。
- 移動時間は `ceil(距離 / 速度)` ティック。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from types import MappingProxyType

from mrta.model import Plan, Point, Scenario, manhattan, travel_ticks, validate_plan


class SegmentKind(StrEnum):
    MOVE = "move"
    SERVICE = "service"


@dataclass(frozen=True, slots=True)
class Segment:
    """あるロボットの時間区間 [t0, t1]。長さ0の区間は作らない。作業中は src == dst。"""

    robot: str
    kind: SegmentKind
    task: str
    src: Point
    dst: Point
    t0: int
    t1: int


@dataclass(frozen=True, slots=True)
class RobotMetrics:
    finish: int  # 完了時刻
    distance: int  # 移動距離(マンハッタン)
    busy: int  # 稼働時間 = 移動(ceil 後のティック数)+ 作業


@dataclass(frozen=True, slots=True)
class Metrics:
    makespan: int
    total_distance: int
    busy_total: int
    available_total: int  # ロボット数 × makespan
    per_robot: Mapping[str, RobotMetrics]

    def __post_init__(self) -> None:
        object.__setattr__(self, "per_robot", MappingProxyType(dict(self.per_robot)))

    @property
    def utilization(self) -> Fraction | None:
        """稼働率。割り算した浮動小数点ではなく、厳密な分数で持つ。完了時間が0なら未定義。"""
        if self.available_total == 0:
            return None
        return Fraction(self.busy_total, self.available_total)


@dataclass(frozen=True, slots=True)
class SimulationResult:
    segments: tuple[Segment, ...]
    metrics: Metrics


def simulate(scenario: Scenario, plan: Plan) -> SimulationResult:
    """Plan を実行し、時間区間と指標を返す。Plan が不正なら InvalidPlanError。"""
    validate_plan(scenario, plan)
    robots = {r.id: r for r in scenario.robots}
    tasks = {t.id: t for t in scenario.tasks}

    segments: list[Segment] = []
    per_robot: dict[str, RobotMetrics] = {}

    for robot_id, task_ids in plan.routes.items():
        robot = robots[robot_id]
        position = robot.start
        now = 0
        distance = 0
        busy = 0
        for task_id in task_ids:
            task = tasks[task_id]

            move_distance = manhattan(position, task.location)
            move_ticks = travel_ticks(move_distance, robot.speed)
            if move_ticks > 0:
                segments.append(
                    Segment(
                        robot_id,
                        SegmentKind.MOVE,
                        task_id,
                        position,
                        task.location,
                        now,
                        now + move_ticks,
                    )
                )
            distance += move_distance
            now += move_ticks

            if task.service_time > 0:
                segments.append(
                    Segment(
                        robot_id,
                        SegmentKind.SERVICE,
                        task_id,
                        task.location,
                        task.location,
                        now,
                        now + task.service_time,
                    )
                )
            now += task.service_time

            busy += move_ticks + task.service_time
            position = task.location

        per_robot[robot_id] = RobotMetrics(finish=now, distance=distance, busy=busy)

    makespan = max(m.finish for m in per_robot.values())
    metrics = Metrics(
        makespan=makespan,
        total_distance=sum(m.distance for m in per_robot.values()),
        busy_total=sum(m.busy for m in per_robot.values()),
        available_total=len(scenario.robots) * makespan,
        per_robot=per_robot,
    )
    return SimulationResult(segments=tuple(sorted(segments, key=_order)), metrics=metrics)


def _order(segment: Segment) -> tuple[int, str, int]:
    """ADR-0004 の並び: t0、ロボットID(辞書順)、kind(move が先)。"""
    kind_rank = 0 if segment.kind is SegmentKind.MOVE else 1
    return (segment.t0, segment.robot, kind_rank)
