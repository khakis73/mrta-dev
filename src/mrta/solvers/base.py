"""ソルバの共通インターフェース(ADR-0003)。

ソルバは `Scenario -> Plan` の純関数。シミュレータもログも知らない。
ロボットの `kind` は見ず、スキルと容量(`is_eligible`)だけを見る。
"""

from collections.abc import Mapping
from typing import Protocol

from mrta.model import ModelError, Plan, Scenario

# solver 行の config に書ける値(ADR-0004: 整数・文字列・真偽値のみ。時間は整数ミリ秒)。
type ConfigValue = int | str | bool


class UnsolvableError(ModelError):
    """適格なロボットがいないタスクがあり、割り当てられない。"""


class Solver(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def config(self) -> Mapping[str, ConfigValue]:
        """結果を左右する設定。ログの solver 行に残し、再現に使う。"""
        ...

    def solve(self, scenario: Scenario) -> Plan: ...


def require_solvable(scenario: Scenario) -> None:
    """適格なロボットがいないタスクがあれば、黙って捨てずに例外にする。"""
    unservable = scenario.unservable_tasks()
    if unservable:
        ids = [t.id for t in unservable]
        raise UnsolvableError(f"適格なロボットがいないタスクがある: {ids}")
