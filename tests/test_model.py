from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mrta.model import (
    CARRY,
    MANIPULATE,
    InvalidPlanError,
    ModelError,
    Plan,
    RobotKind,
    is_eligible,
    manhattan,
    travel_ticks,
    validate_plan,
)
from tests.builders import robot, scenario, task


class TestDistanceAndTime:
    def test_manhattan(self) -> None:
        assert manhattan((0, 0), (3, 4)) == 7
        assert manhattan((5, 5), (5, 5)) == 0
        assert manhattan((2, 7), (6, 1)) == 10

    @pytest.mark.parametrize(
        ("distance", "speed", "expected"),
        [(7, 2, 4), (6, 2, 3), (1, 5, 1), (0, 3, 0), (10, 1, 10)],
    )
    def test_travel_ticks_is_ceil(self, distance: int, speed: int, expected: int) -> None:
        assert travel_ticks(distance, speed) == expected

    @given(distance=st.integers(0, 10_000), speed=st.integers(1, 100))
    def test_travel_ticks_is_the_smallest_sufficient_tick_count(
        self, distance: int, speed: int
    ) -> None:
        ticks = travel_ticks(distance, speed)
        assert ticks * speed >= distance  # 着ける
        assert ticks == 0 or (ticks - 1) * speed < distance  # それ以上短くできない

    def test_travel_ticks_rejects_non_positive_speed(self) -> None:
        with pytest.raises(ModelError):
            travel_ticks(5, 0)


class TestEntityValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"id": ""},
            {"speed": 0},
            {"speed": 1.5},
            {"speed": True},
            {"capacity": 0},
            {"start": (-1, 0)},
            {"start": (1,)},
            {"skills": frozenset()},
            {"skills": frozenset({""})},
        ],
    )
    def test_invalid_robot(self, overrides: dict[str, Any]) -> None:
        with pytest.raises(ModelError):
            robot(**overrides)

    @pytest.mark.parametrize(
        "overrides",
        [
            {"id": ""},
            {"demand": 0},
            {"service_time": -1},
            {"release_time": -1},
            {"release_time": 1.5},
            {"release_time": True},
            {"location": (0, -2)},
            {"required_skill": ""},
        ],
    )
    def test_invalid_task(self, overrides: dict[str, Any]) -> None:
        with pytest.raises(ModelError):
            task(**overrides)

    def test_zero_service_time_is_allowed(self) -> None:
        assert task(service_time=0).service_time == 0

    def test_release_time_defaults_to_zero_which_means_static(self) -> None:
        assert task().release_time == 0
        assert task(release_time=7).release_time == 7

    def test_scenario_rejects_duplicate_ids_and_out_of_bounds(self) -> None:
        with pytest.raises(ModelError, match="重複"):
            scenario((robot("r0"), robot("r0")), ())
        with pytest.raises(ModelError, match="重複"):
            scenario((robot(),), (task("t0"), task("t0")))
        with pytest.raises(ModelError, match="外"):
            scenario((robot(start=(10, 0)),), ())
        with pytest.raises(ModelError, match="外"):
            scenario((robot(),), (task(location=(0, 10)),))

    def test_scenario_requires_a_robot(self) -> None:
        with pytest.raises(ModelError):
            scenario((), ())

    def test_entities_are_immutable(self) -> None:
        r = robot()
        with pytest.raises(AttributeError):
            r.speed = 3  # type: ignore[misc]


class TestEligibility:
    def test_skill_and_capacity_are_checked_and_kind_is_ignored(self) -> None:
        manipulator = robot(
            kind=RobotKind.MOBILE_MANIPULATOR, capacity=3, skills=frozenset({CARRY, MANIPULATE})
        )
        assert is_eligible(manipulator, task(required_skill=MANIPULATE, demand=3))
        assert not is_eligible(manipulator, task(required_skill=MANIPULATE, demand=4))  # 容量
        assert not is_eligible(robot(), task(required_skill=MANIPULATE))  # スキル
        # kind が違っても、スキルと容量が同じなら結果は同じ
        assert is_eligible(robot(kind=RobotKind.MOBILE_MANIPULATOR), task()) == is_eligible(
            robot(kind=RobotKind.AMR), task()
        )

    def test_unservable_tasks(self) -> None:
        s = scenario((robot(),), (task("t0"), task("t1", required_skill=MANIPULATE)))
        assert [t.id for t in s.unservable_tasks()] == ["t1"]


class TestValidatePlan:
    def setup_method(self) -> None:
        self.scenario = scenario(
            (
                robot("r0", capacity=5),
                robot(
                    "r1",
                    kind=RobotKind.MOBILE_MANIPULATOR,
                    capacity=2,
                    skills=frozenset({CARRY, MANIPULATE}),
                ),
            ),
            (
                task("t0", demand=4),
                task("t1", required_skill=MANIPULATE, demand=2),
                task("t2"),
            ),
        )

    def test_valid_plan(self) -> None:
        validate_plan(self.scenario, Plan({"r0": ("t0", "t2"), "r1": ("t1",)}))

    def test_empty_route_is_valid(self) -> None:
        # タスクが0件のロボットも、キーは必要(値は空)
        s = scenario((robot("r0"), robot("r1")), (task("t0"),))
        validate_plan(s, Plan({"r0": ("t0",), "r1": ()}))

    @pytest.mark.parametrize(
        ("routes", "message"),
        [
            ({"r0": ("t0", "t2")}, "キー"),  # ロボットの欠落
            ({"r0": ("t0", "t2"), "r1": ("t1",), "r9": ()}, "キー"),  # 余分なキー
            ({"r0": ("t0", "t2", "tX"), "r1": ("t1",)}, "未知"),
            ({"r0": ("t0", "t2"), "r1": ("t1", "t2")}, "重複"),
            ({"r0": ("t0", "t0", "t2"), "r1": ("t1",)}, "重複"),
            ({"r0": ("t0",), "r1": ("t1",)}, "割り当てられていない"),
            ({"r0": ("t0", "t1", "t2"), "r1": ()}, "スキル・容量"),  # スキル不足
            ({"r0": ("t2",), "r1": ("t0", "t1")}, "スキル・容量"),  # 容量超過(t0 の demand は 4)
        ],
    )
    def test_invalid_plans(self, routes: dict[str, tuple[str, ...]], message: str) -> None:
        with pytest.raises(InvalidPlanError, match=message):
            validate_plan(self.scenario, Plan(routes))

    def test_plan_is_immutable_and_copies_its_input(self) -> None:
        source = {"r0": ["t0"]}
        plan = Plan(source)  # type: ignore[arg-type]
        source["r0"].append("t1")
        source["r9"] = []
        assert plan.routes == {"r0": ("t0",)}
        with pytest.raises(TypeError):
            plan.routes["r1"] = ()  # type: ignore[index]
