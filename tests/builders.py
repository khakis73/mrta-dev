"""テスト用のエンティティ・ビルダー。既定値を持ち、上書きしたい項目だけ渡す。"""

from typing import Any

from mrta.model import CARRY, Robot, RobotKind, Scenario, Task


def robot(id_: str = "r0", **overrides: Any) -> Robot:
    params: dict[str, Any] = {
        "id": id_,
        "kind": RobotKind.AMR,
        "start": (0, 0),
        "speed": 2,
        "capacity": 5,
        "skills": frozenset({CARRY}),
    }
    return Robot(**{**params, **overrides})


def task(id_: str = "t0", **overrides: Any) -> Task:
    params: dict[str, Any] = {
        "id": id_,
        "location": (3, 4),
        "required_skill": CARRY,
        "demand": 1,
        "service_time": 2,
    }
    return Task(**{**params, **overrides})


def scenario(robots: tuple[Robot, ...], tasks: tuple[Task, ...]) -> Scenario:
    return Scenario(seed=0, width=10, height=10, robots=robots, tasks=tasks)
