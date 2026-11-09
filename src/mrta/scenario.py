"""シナリオ生成器。シードを固定すれば、同じシナリオを返す(決定性)。

乱数は `random.Random(seed)` だけを使い、グローバルの乱数には触れない。
**乱数を引く順序は契約**であり、変えるとシードごとのシナリオが変わる
(固定シードの golden file や統計の比較が壊れる)。順序を変えるときは明示的に扱う。
"""

import random
from dataclasses import dataclass

from mrta.model import (
    CARRY,
    MANIPULATE,
    ModelError,
    Robot,
    RobotKind,
    Scenario,
    Task,
    require_int,
)


@dataclass(frozen=True, slots=True)
class GeneratorConfig:
    """生成の設定。AMR は速く大容量、モバイルマニピュレーターは遅く小容量で操作もできる。"""

    width: int = 20
    height: int = 20
    n_amr: int = 2
    n_mobile_manipulators: int = 2
    n_tasks: int = 10
    manipulate_percent: int = 30  # 操作スキルを要するタスクの割合(整数%。浮動小数点を避ける)
    amr_speed: int = 3
    amr_capacity: int = 10
    mm_speed: int = 1
    mm_capacity: int = 3
    max_service_time: int = 5

    def __post_init__(self) -> None:
        require_int("width", self.width, minimum=1)
        require_int("height", self.height, minimum=1)
        require_int("n_amr", self.n_amr, minimum=0)
        require_int("n_mobile_manipulators", self.n_mobile_manipulators, minimum=0)
        require_int("n_tasks", self.n_tasks, minimum=0)
        require_int("manipulate_percent", self.manipulate_percent, minimum=0)
        require_int("amr_speed", self.amr_speed, minimum=1)
        require_int("amr_capacity", self.amr_capacity, minimum=1)
        require_int("mm_speed", self.mm_speed, minimum=1)
        require_int("mm_capacity", self.mm_capacity, minimum=1)
        require_int("max_service_time", self.max_service_time, minimum=1)
        if self.manipulate_percent > 100:
            raise ModelError(f"manipulate_percent は 100 以下: {self.manipulate_percent}")
        if self.n_amr + self.n_mobile_manipulators < 1:
            raise ModelError("ロボットは1台以上必要")
        if self.manipulate_percent > 0 and self.n_mobile_manipulators == 0:
            raise ModelError("操作スキルのタスクを作るにはモバイルマニピュレーターが必要")


def generate(seed: int, config: GeneratorConfig | None = None) -> Scenario:
    """シナリオを生成する。全タスクに適格なロボットが1台以上いることを、構築で保証する。

    - 操作スキルのタスクの demand は、モバイルマニピュレーターの容量以下
    - 運搬スキルのタスクの demand は、運搬できるロボットの最大容量以下
    """
    cfg = config or GeneratorConfig()
    rng = random.Random(seed)

    robots: list[Robot] = []
    for _ in range(cfg.n_amr):
        robots.append(
            Robot(
                id=f"r{len(robots)}",
                kind=RobotKind.AMR,
                start=(rng.randrange(cfg.width), rng.randrange(cfg.height)),
                speed=cfg.amr_speed,
                capacity=cfg.amr_capacity,
                skills=frozenset({CARRY}),
            )
        )
    for _ in range(cfg.n_mobile_manipulators):
        robots.append(
            Robot(
                id=f"r{len(robots)}",
                kind=RobotKind.MOBILE_MANIPULATOR,
                start=(rng.randrange(cfg.width), rng.randrange(cfg.height)),
                speed=cfg.mm_speed,
                capacity=cfg.mm_capacity,
                skills=frozenset({CARRY, MANIPULATE}),
            )
        )

    max_demand = {
        CARRY: max(r.capacity for r in robots if CARRY in r.skills),
        MANIPULATE: cfg.mm_capacity,
    }

    tasks: list[Task] = []
    for i in range(cfg.n_tasks):
        location = (rng.randrange(cfg.width), rng.randrange(cfg.height))
        skill = MANIPULATE if rng.randrange(100) < cfg.manipulate_percent else CARRY
        tasks.append(
            Task(
                id=f"t{i}",
                location=location,
                required_skill=skill,
                demand=rng.randint(1, max_demand[skill]),
                service_time=rng.randint(1, cfg.max_service_time),
            )
        )

    return Scenario(
        seed=seed,
        width=cfg.width,
        height=cfg.height,
        robots=tuple(robots),
        tasks=tuple(tasks),
    )
