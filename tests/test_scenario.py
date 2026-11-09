import random

import pytest
from hypothesis import given

from mrta.model import CARRY, MANIPULATE, ModelError, RobotKind
from mrta.scenario import GeneratorConfig, generate
from tests.strategies import configs, seeds


class TestDeterminism:
    @given(seed=seeds, config=configs())
    def test_same_seed_gives_same_scenario(self, seed: int, config: GeneratorConfig) -> None:
        assert generate(seed, config) == generate(seed, config)

    def test_different_seeds_give_different_scenarios(self) -> None:
        assert generate(1) != generate(2)

    def test_does_not_touch_the_global_random_state(self) -> None:
        random.seed(123)
        before = random.getstate()
        generate(7)
        assert random.getstate() == before

    def test_pinned_snapshot_detects_rng_drift(self) -> None:
        """Python や乱数の実装の違いで、同じシードのシナリオが変わっていないことの回帰テスト。

        意図してシナリオの生成を変えたときは、この期待値も更新する(= 固定シードの比較が変わる)。
        """
        config = GeneratorConfig(width=10, height=10, n_amr=1, n_mobile_manipulators=1, n_tasks=3)
        s = generate(0, config)
        assert [(r.id, r.start) for r in s.robots] == [("r0", (6, 6)), ("r1", (0, 4))]
        assert [
            (t.id, t.location, t.required_skill, t.demand, t.service_time) for t in s.tasks
        ] == [
            ("t0", (8, 7), CARRY, 5, 4),
            ("t1", (5, 9), MANIPULATE, 3, 2),
            ("t2", (4, 2), CARRY, 2, 5),
        ]


class TestInvariants:
    @given(seed=seeds, config=configs())
    def test_every_task_has_an_eligible_robot(self, seed: int, config: GeneratorConfig) -> None:
        scenario = generate(seed, config)
        assert scenario.unservable_tasks() == ()

    @given(seed=seeds, config=configs())
    def test_shape_ids_and_bounds(self, seed: int, config: GeneratorConfig) -> None:
        s = generate(seed, config)
        assert s.seed == seed
        assert (s.width, s.height) == (config.width, config.height)
        assert [r.id for r in s.robots] == [f"r{i}" for i in range(len(s.robots))]
        assert [t.id for t in s.tasks] == [f"t{i}" for i in range(config.n_tasks)]
        assert sum(r.kind is RobotKind.AMR for r in s.robots) == config.n_amr
        for point in [r.start for r in s.robots] + [t.location for t in s.tasks]:
            assert 0 <= point[0] < s.width
            assert 0 <= point[1] < s.height
        assert all(1 <= t.service_time <= config.max_service_time for t in s.tasks)

    @given(seed=seeds, config=configs())
    def test_heterogeneity_follows_the_config(self, seed: int, config: GeneratorConfig) -> None:
        for r in generate(seed, config).robots:
            if r.kind is RobotKind.AMR:
                assert (r.speed, r.capacity, r.skills) == (
                    config.amr_speed,
                    config.amr_capacity,
                    frozenset({CARRY}),
                )
            else:
                assert (r.speed, r.capacity, r.skills) == (
                    config.mm_speed,
                    config.mm_capacity,
                    frozenset({CARRY, MANIPULATE}),
                )

    def test_manipulate_percent_extremes(self) -> None:
        none = generate(5, GeneratorConfig(n_tasks=40, manipulate_percent=0))
        every = generate(5, GeneratorConfig(n_tasks=40, manipulate_percent=100))
        assert all(t.required_skill == CARRY for t in none.tasks)
        assert all(t.required_skill == MANIPULATE for t in every.tasks)


class TestConfigValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"width": 0},
            {"n_amr": -1},
            {"n_amr": 0, "n_mobile_manipulators": 0},
            {"manipulate_percent": 101},
            {"n_mobile_manipulators": 0, "manipulate_percent": 30},  # 操作できるロボットがいない
            {"amr_speed": 0},
            {"max_service_time": 0},
            {"n_tasks": 2.5},
        ],
    )
    def test_invalid_config(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(ModelError):
            GeneratorConfig(**kwargs)  # type: ignore[arg-type]

    def test_amr_only_scenario_without_manipulate_tasks_is_valid(self) -> None:
        s = generate(1, GeneratorConfig(n_mobile_manipulators=0, manipulate_percent=0))
        assert s.unservable_tasks() == ()
