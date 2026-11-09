"""ドメインモデル(ADR-0003)。

位置・時間・距離は全て整数。エンティティは不変で、不正な値は構築時に例外にする。
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

type Point = tuple[int, int]

CARRY = "carry"
MANIPULATE = "manipulate"


class ModelError(ValueError):
    """モデルの不変条件に反する値。"""


class InvalidPlanError(ModelError):
    """シナリオに対して不正な Plan。"""


class RobotKind(StrEnum):
    AMR = "amr"
    MOBILE_MANIPULATOR = "mobile_manipulator"


def require_int(name: str, value: object, *, minimum: int) -> None:
    # bool は int の部分型だが、整数として扱わない(ログに true/false が混ざるため)。
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelError(f"{name} は整数でなければならない: {value!r}")
    if value < minimum:
        raise ModelError(f"{name} は {minimum} 以上でなければならない: {value}")


def _id(name: str, value: object) -> None:
    if not isinstance(value, str) or value == "":
        raise ModelError(f"{name} は空でない文字列でなければならない: {value!r}")


def _point(name: str, value: object) -> None:
    if not (isinstance(value, tuple) and len(value) == 2):
        raise ModelError(f"{name} は (x, y) でなければならない: {value!r}")
    require_int(f"{name}.x", value[0], minimum=0)
    require_int(f"{name}.y", value[1], minimum=0)


@dataclass(frozen=True, slots=True)
class Robot:
    id: str
    kind: RobotKind
    start: Point
    speed: int  # 1ティックに進める格子数
    capacity: int  # 1タスクあたりの扱える demand の上限
    skills: frozenset[str]

    def __post_init__(self) -> None:
        _id("Robot.id", self.id)
        _point(f"Robot[{self.id}].start", self.start)
        require_int(f"Robot[{self.id}].speed", self.speed, minimum=1)
        require_int(f"Robot[{self.id}].capacity", self.capacity, minimum=1)
        object.__setattr__(self, "skills", frozenset(self.skills))
        if not self.skills or any(not isinstance(s, str) or s == "" for s in self.skills):
            raise ModelError(f"Robot[{self.id}].skills は空でない文字列の集合でなければならない")


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    location: Point
    required_skill: str
    demand: int
    service_time: int  # 作業にかかるティック数(0 を許す)

    def __post_init__(self) -> None:
        _id("Task.id", self.id)
        _point(f"Task[{self.id}].location", self.location)
        _id(f"Task[{self.id}].required_skill", self.required_skill)
        require_int(f"Task[{self.id}].demand", self.demand, minimum=1)
        require_int(f"Task[{self.id}].service_time", self.service_time, minimum=0)


def is_eligible(robot: Robot, task: Task) -> bool:
    """スキル制約と容量制約(タスクごとの可否)を満たすか。ロボットの kind は見ない。"""
    return task.required_skill in robot.skills and task.demand <= robot.capacity


@dataclass(frozen=True, slots=True)
class Scenario:
    seed: int
    width: int
    height: int
    robots: tuple[Robot, ...]
    tasks: tuple[Task, ...]

    def __post_init__(self) -> None:
        require_int("Scenario.seed", self.seed, minimum=-(2**63))
        require_int("Scenario.width", self.width, minimum=1)
        require_int("Scenario.height", self.height, minimum=1)
        object.__setattr__(self, "robots", tuple(self.robots))
        object.__setattr__(self, "tasks", tuple(self.tasks))
        if not self.robots:
            raise ModelError("Scenario.robots は1台以上必要")
        _unique("ロボット", (r.id for r in self.robots))
        _unique("タスク", (t.id for t in self.tasks))
        for robot in self.robots:
            self._check_bounds(f"Robot[{robot.id}].start", robot.start)
        for task in self.tasks:
            self._check_bounds(f"Task[{task.id}].location", task.location)

    def _check_bounds(self, name: str, point: Point) -> None:
        x, y = point
        if x >= self.width or y >= self.height:
            raise ModelError(f"{name}={point} が格子 {self.width}x{self.height} の外にある")

    def eligible_robots(self, task: Task) -> tuple[Robot, ...]:
        return tuple(r for r in self.robots if is_eligible(r, task))

    def unservable_tasks(self) -> tuple[Task, ...]:
        """適格なロボットが1台もいないタスク。ソルバはこれがあれば例外にする。"""
        return tuple(t for t in self.tasks if not self.eligible_robots(t))


def _unique(label: str, ids: Iterable[str]) -> None:
    seen: set[str] = set()
    for id_ in ids:
        if id_ in seen:
            raise ModelError(f"{label}ID が重複している: {id_}")
        seen.add(id_)


@dataclass(frozen=True, slots=True)
class Plan:
    """ソルバの出力。全ロボットIDをキーに持ち、値は実行順のタスクID。"""

    routes: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        frozen = {robot_id: tuple(task_ids) for robot_id, task_ids in self.routes.items()}
        object.__setattr__(self, "routes", MappingProxyType(frozen))


def manhattan(a: Point, b: Point) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def travel_ticks(distance: int, speed: int) -> int:
    """移動時間 = ceil(距離 / 速度)。整数だけで計算する。"""
    require_int("distance", distance, minimum=0)
    require_int("speed", speed, minimum=1)
    return -(-distance // speed)


def validate_plan(scenario: Scenario, plan: Plan) -> None:
    """Plan がシナリオに対して正しいことを検証する。不正なら InvalidPlanError。

    - キーは全ロボットIDと一致する(欠落・余分は不正)
    - 全タスクがちょうど1回割り当てられる(重複・欠落・未知のタスクは不正)
    - 割り当てられたロボットが、タスクのスキル・容量制約を満たす
    """
    robots = {r.id: r for r in scenario.robots}
    tasks = {t.id: t for t in scenario.tasks}

    missing_keys = sorted(robots.keys() - plan.routes.keys())
    extra_keys = sorted(plan.routes.keys() - robots.keys())
    if missing_keys or extra_keys:
        raise InvalidPlanError(
            f"Plan のキーがロボットIDと一致しない(欠落: {missing_keys}, 余分: {extra_keys})"
        )

    assigned: dict[str, str] = {}
    for robot_id, task_ids in plan.routes.items():
        for task_id in task_ids:
            if task_id not in tasks:
                raise InvalidPlanError(f"未知のタスクID: {task_id}(ロボット {robot_id})")
            if task_id in assigned:
                raise InvalidPlanError(
                    f"タスク {task_id} が重複して割り当てられている"
                    f"({assigned[task_id]}, {robot_id})"
                )
            assigned[task_id] = robot_id
            if not is_eligible(robots[robot_id], tasks[task_id]):
                raise InvalidPlanError(
                    f"ロボット {robot_id} はタスク {task_id} のスキル・容量制約を満たさない"
                )

    unassigned = sorted(tasks.keys() - assigned.keys())
    if unassigned:
        raise InvalidPlanError(f"割り当てられていないタスクがある: {unassigned}")
