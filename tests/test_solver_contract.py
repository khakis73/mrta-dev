"""全ソルバ共通の契約テスト。

`mrta.solvers.SOLVERS` に登録されたソルバ全てに対して走る。新しいソルバは登録するだけで、
ここにある契約(ADR-0003: Scenario → Plan の純関数、kind を見ない、決定的)を満たすか検査される。
"""

from dataclasses import replace

import pytest
from hypothesis import given

from mrta.model import (
    MANIPULATE,
    Robot,
    RobotKind,
    Scenario,
    Task,
    validate_plan,
)
from mrta.solvers import SOLVERS, Solver, UnsolvableError
from tests.builders import robot, scenario, task
from tests.strategies import scenarios

solver_names = pytest.mark.parametrize("solver_name", sorted(SOLVERS))


def make(solver_name: str) -> Solver:
    return SOLVERS[solver_name]()


def swap_kind(r: Robot) -> Robot:
    other = (
        RobotKind.AMR if r.kind is RobotKind.MOBILE_MANIPULATOR else RobotKind.MOBILE_MANIPULATOR
    )
    return replace(r, kind=other)


@solver_names
class TestSolverContract:
    @given(s=scenarios())
    def test_plan_is_valid(self, solver_name: str, s: Scenario) -> None:
        """全タスクがちょうど1回割当、スキル・容量制約を満たす。"""
        validate_plan(s, make(solver_name).solve(s))

    @given(s=scenarios())
    def test_is_deterministic(self, solver_name: str, s: Scenario) -> None:
        """同じシナリオなら、呼び直しても、別のインスタンスでも同じ Plan。"""
        solver = make(solver_name)
        first = solver.solve(s)
        assert solver.solve(s) == first
        assert make(solver_name).solve(s) == first

    @given(s=scenarios())
    def test_ignores_robot_kind(self, solver_name: str, s: Scenario) -> None:
        """ソルバはスキルと容量だけを見る。kind を入れ替えても結果は変わらない。"""
        swapped = replace(s, robots=tuple(swap_kind(r) for r in s.robots))
        solver = make(solver_name)
        assert solver.solve(swapped) == solver.solve(s)

    @given(s=scenarios())
    def test_ignores_robot_order(self, solver_name: str, s: Scenario) -> None:
        """ロボットの並び順に依存しない(同点の解消はIDで決まる)。"""
        reordered = replace(s, robots=tuple(reversed(s.robots)))
        solver = make(solver_name)
        assert solver.solve(reordered) == solver.solve(s)

    def test_no_tasks_gives_empty_routes_for_every_robot(self, solver_name: str) -> None:
        s = scenario((robot("r0"), robot("r1")), ())
        plan = make(solver_name).solve(s)
        assert dict(plan.routes) == {"r0": (), "r1": ()}

    @pytest.mark.parametrize(
        "bad_task",
        [
            task("t1", required_skill=MANIPULATE),  # スキルを持つロボットがいない
            task("t1", demand=6),  # どのロボットの容量(5)も超える
        ],
    )
    def test_unservable_task_raises(self, solver_name: str, bad_task: Task) -> None:
        s = scenario((robot("r0"),), (task("t0"), bad_task))
        with pytest.raises(UnsolvableError, match="t1"):
            make(solver_name).solve(s)

    def test_name_and_config_are_loggable(self, solver_name: str) -> None:
        """ログの solver 行(ADR-0004)に書ける: 名前は文字列、config の値は整数・文字列・真偽値。"""
        solver = make(solver_name)
        assert solver.name == solver_name
        assert all(
            isinstance(k, str) and isinstance(v, int | str | bool) for k, v in solver.config.items()
        )

    def test_time_settings_are_integer_milliseconds(self, solver_name: str) -> None:
        """時間に関する設定は、整数ミリ秒で明示する(ADR-0004。浮動小数点・暗黙の時間を避ける)。"""
        solver = make(solver_name)
        for key, value in solver.config.items():
            if "time" in key:
                assert isinstance(value, int) and not isinstance(value, bool)
                assert key.endswith("_ms")


def test_registry_is_not_empty() -> None:
    assert SOLVERS, "契約テストの対象が無い"
