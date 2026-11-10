"""makespan の下界と下界ギャップ(ADR-0008)。

モデル(ADR-0003)だけに依存し、ソルバを知らない。CP-SAT が証明した下界との合成は呼び出し側で行う。
"""

from fractions import Fraction

from mrta.model import ModelError, Scenario, manhattan, travel_ticks


class BoundViolationError(ModelError):
    """makespan が下界を下回った。下界かソルバのどちらかが誤っている(バグ)。"""


def task_lower_bound(scenario: Scenario) -> int:
    """ソルバ不要の下界: 各タスクを適格なロボットが開始位置から直行して終える最短時刻の最大値。

    どの Plan でも、タスク `t` は適格なロボット `r` が実行し、`r` の完了時刻は `t` の完了時刻以上。
    経由すると移動時間は直行より短くならない(`ceil(a/v) + ceil(b/v) ≥ ceil((a+b)/v)` と
    三角不等式)ので、`t` の完了は直行の時刻以上になる。タスクが0件なら 0。
    適格なロボットがいないタスクは、下界を定義できないので `ValueError`。
    """
    bound = 0
    for task in scenario.tasks:
        eligible = scenario.eligible_robots(task)
        if not eligible:
            raise ValueError(f"適格なロボットがいないタスク: {task.id}")
        earliest = min(
            travel_ticks(manhattan(r.start, task.location), r.speed) + task.service_time
            for r in eligible
        )
        bound = max(bound, earliest)
    return bound


def lower_bound(scenario: Scenario, solver_bound: int) -> int:
    """`max(タスク別の下界, ソルバが証明した下界)`。"""
    return max(task_lower_bound(scenario), solver_bound)


def gap(makespan: int, bound: int) -> Fraction | None:
    """下界ギャップ `(makespan − bound) / bound`。厳密な分数。下界が0なら未定義(`None`)。

    `makespan < bound` はバグなので `BoundViolationError`。
    """
    if makespan < bound:
        raise BoundViolationError(f"makespan={makespan} が下界 {bound} を下回った")
    if bound == 0:
        return None
    return Fraction(makespan - bound, bound)
