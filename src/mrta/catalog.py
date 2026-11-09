"""名前つきの手作りシナリオ(ADR-0005)。

ソルバの違いが**手計算で追える**ように、小さく作った固定のシナリオ。
**ソルバの弱点を狙って作った「見せるための例」**であり、典型的な性能の代表ではない。
結論は複数シードの統計と下界で確かめる(CLAUDE.md)。

シードを持たないので `Scenario.seed` は 0 とする(ログの `scenario.seed` も 0)。
各シナリオの期待値(どのソルバが何ティックか)は、`tests/test_catalog.py` で固定している。
"""

from collections.abc import Callable, Mapping

from mrta.model import CARRY, MANIPULATE, Robot, RobotKind, Scenario, Task


def greedy_trap() -> Scenario:
    """貪欲法の罠: 先に処理するタスクを近いロボットに取られ、もう一方が遠回りになる。

    r0=(0,0)、r1=(8,0)(どちらも速度1)。t0=(3,0)、t1=(0,3)。作業時間は1。
    - 貪欲法(t0, t1 の順): t0 は r0(4)が r1(6)より早い → r0。
      t1 は r0 が (3,0) から距離6で 4+6+1=11、r1 は 11+1=12 → r0。完了時間 11、r1 は遊ぶ。
    - ハンガリアン法: 2タスクを同時に見る。r0→t1(4) + r1→t0(6) = 10 が、
      r0→t0(4) + r1→t1(12) = 16 より小さい。完了時間 6(これが最適)。
    """
    robots = (
        _robot("r0", RobotKind.AMR, (0, 0), speed=1, capacity=5, skills={CARRY}),
        _robot("r1", RobotKind.AMR, (8, 0), speed=1, capacity=5, skills={CARRY}),
    )
    tasks = (
        Task(id="t0", location=(3, 0), required_skill=CARRY, demand=1, service_time=1),
        Task(id="t1", location=(0, 3), required_skill=CARRY, demand=1, service_time=1),
    )
    return Scenario(seed=0, width=10, height=10, robots=robots, tasks=tasks)


def skill_trap() -> Scenario:
    """スキルの罠: 運搬タスクを近いマニピュレーターが取り、操作タスクを待たせる。

    AMR a=(0,0) 速度3 / マニピュレーター m=(6,0) 速度1。
    t0=(5,0) 運搬、t1=(7,0) 操作(m だけが可能)。作業時間は1。
    - 貪欲法(t0, t1 の順): t0 は m(1+1=2)が a(ceil(5/3)+1=3)より早い → m。
      t1 は m だけが可能で、(5,0) から 2+2+1=5。完了時間 5。
    - ハンガリアン法: m→t1(2) + a→t0(3) = 5 が、m→t0(2) + a→t1(不可) より優先。完了時間 3。
    """
    robots = (
        _robot("r0", RobotKind.AMR, (0, 0), speed=3, capacity=5, skills={CARRY}),
        _robot(
            "r1", RobotKind.MOBILE_MANIPULATOR, (6, 0), speed=1, capacity=3,
            skills={CARRY, MANIPULATE},
        ),
    )  # fmt: skip
    tasks = (
        Task(id="t0", location=(5, 0), required_skill=CARRY, demand=1, service_time=1),
        Task(id="t1", location=(7, 0), required_skill=MANIPULATE, demand=1, service_time=1),
    )
    return Scenario(seed=0, width=10, height=10, robots=robots, tasks=tasks)


def _robot(
    id_: str,
    kind: RobotKind,
    start: tuple[int, int],
    *,
    speed: int,
    capacity: int,
    skills: set[str],
) -> Robot:
    return Robot(
        id=id_, kind=kind, start=start, speed=speed, capacity=capacity, skills=frozenset(skills)
    )


# 名前 → シナリオの生成。CLI の `--scenario` と、テストの対象になる。
SCENARIOS: Mapping[str, Callable[[], Scenario]] = {
    "greedy-trap": greedy_trap,
    "skill-trap": skill_trap,
}
