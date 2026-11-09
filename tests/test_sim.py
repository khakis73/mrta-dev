"""シミュレータと指標のテスト。

具体例の期待値は、ADR-0003 の実行の意味と、ADR-0004 の例から**手計算**した。
性質のテストは、ソルバに依存しないランダムな有効 Plan で検証する。
"""

from fractions import Fraction

import pytest
from hypothesis import given

from mrta.model import InvalidPlanError, Plan, Scenario, manhattan, travel_ticks
from mrta.sim import Segment, SegmentKind, simulate
from tests.builders import robot, scenario, task
from tests.strategies import scenarios_with_plans

MOVE, SERVICE = SegmentKind.MOVE, SegmentKind.SERVICE


class TestWorkedExamples:
    def test_adr0004_example(self) -> None:
        # r0: 速度2、(0,0) 発。t0: (3,4)、作業2。距離7 → ceil(7/2)=4、作業2 → 完了6。
        s = scenario((robot("r0", speed=2),), (task("t0", location=(3, 4), service_time=2),))
        result = simulate(s, Plan({"r0": ("t0",)}))

        assert result.segments == (
            Segment("r0", MOVE, "t0", (0, 0), (3, 4), 0, 4),
            Segment("r0", SERVICE, "t0", (3, 4), (3, 4), 4, 6),
        )
        m = result.metrics
        assert (m.makespan, m.total_distance, m.busy_total, m.available_total) == (6, 7, 6, 6)
        assert m.per_robot["r0"].finish == 6
        assert m.per_robot["r0"].distance == 7
        assert m.per_robot["r0"].busy == 6
        assert m.utilization == Fraction(1)

    def test_idle_robot_lowers_utilization(self) -> None:
        # r1 はタスクなし(完了0)。makespan=6、稼働は r0 の6のみ。利用可能は 2台×6=12 → 1/2。
        s = scenario(
            (robot("r0", speed=2), robot("r1")), (task("t0", location=(3, 4), service_time=2),)
        )
        m = simulate(s, Plan({"r0": ("t0",), "r1": ()})).metrics
        assert m.per_robot["r1"].finish == 0
        assert (m.busy_total, m.available_total) == (6, 12)
        assert m.utilization == Fraction(1, 2)

    def test_makespan_is_the_slowest_robot_and_distance_is_summed(self) -> None:
        # r0: (0,0) 速度1 → t0 (2,0) 作業1: 移動2+作業1=3。 距離2
        # r1: (9,9) 速度3 → t1 (9,3) 作業4: 距離6 → ceil(6/3)=2、作業4 → 6。 距離6
        s = scenario(
            (robot("r0", speed=1), robot("r1", start=(9, 9), speed=3)),
            (
                task("t0", location=(2, 0), service_time=1),
                task("t1", location=(9, 3), service_time=4),
            ),
        )
        m = simulate(s, Plan({"r0": ("t0",), "r1": ("t1",)})).metrics
        assert (m.per_robot["r0"].finish, m.per_robot["r1"].finish) == (3, 6)
        assert m.makespan == 6
        assert m.total_distance == 8
        assert (m.busy_total, m.available_total) == (9, 12)
        assert m.utilization == Fraction(3, 4)

    def test_route_is_chained_through_tasks(self) -> None:
        # (0,0) 速度2 → t0 (4,0) 作業1 → t1 (4,3) 作業2。
        # t0: 距離4 → 2 ティック、作業1 → 3。 t1: 距離3 → ceil(3/2)=2、作業2 → 3+2+2=7。
        s = scenario(
            (robot("r0", speed=2),),
            (
                task("t0", location=(4, 0), service_time=1),
                task("t1", location=(4, 3), service_time=2),
            ),
        )
        result = simulate(s, Plan({"r0": ("t0", "t1")}))
        assert result.segments == (
            Segment("r0", MOVE, "t0", (0, 0), (4, 0), 0, 2),
            Segment("r0", SERVICE, "t0", (4, 0), (4, 0), 2, 3),
            Segment("r0", MOVE, "t1", (4, 0), (4, 3), 3, 5),
            Segment("r0", SERVICE, "t1", (4, 3), (4, 3), 5, 7),
        )
        assert result.metrics.makespan == 7
        assert result.metrics.total_distance == 7  # 4 + 3。帰還しない

    def test_zero_length_segments_are_omitted(self) -> None:
        # ロボットの初期位置にあるタスク(移動0)と、作業0のタスク。
        s = scenario(
            (robot("r0", start=(3, 4)),),
            (
                task("t0", location=(3, 4), service_time=2),  # 移動なし
                task("t1", location=(3, 5), service_time=0),  # 作業なし
            ),
        )
        result = simulate(s, Plan({"r0": ("t0", "t1")}))
        assert result.segments == (
            Segment("r0", SERVICE, "t0", (3, 4), (3, 4), 0, 2),
            Segment("r0", MOVE, "t1", (3, 4), (3, 5), 2, 3),
        )
        assert result.metrics.per_robot["r0"].finish == 3

    def test_no_tasks_means_zero_makespan_and_undefined_utilization(self) -> None:
        s = scenario((robot("r0"), robot("r1")), ())
        result = simulate(s, Plan({"r0": (), "r1": ()}))
        m = result.metrics
        assert result.segments == ()
        assert (m.makespan, m.total_distance, m.busy_total, m.available_total) == (0, 0, 0, 0)
        assert m.utilization is None

    def test_segments_are_ordered_by_start_then_robot_id_lexicographically(self) -> None:
        # 同時刻に始まる区間は、ロボットIDの辞書順("r10" < "r2")。
        s = scenario(
            (robot("r2"), robot("r10")),
            (task("t0", location=(0, 1)), task("t1", location=(0, 1))),
        )
        result = simulate(s, Plan({"r2": ("t0",), "r10": ("t1",)}))
        assert [(g.t0, g.robot, g.kind) for g in result.segments][:2] == [
            (0, "r10", MOVE),
            (0, "r2", MOVE),
        ]

    def test_invalid_plan_is_rejected(self) -> None:
        s = scenario((robot("r0"),), (task("t0"),))
        with pytest.raises(InvalidPlanError):
            simulate(s, Plan({"r0": ()}))  # t0 が未割当


class TestProperties:
    """任意のシナリオと有効な Plan に対して成り立つ性質。"""

    @given(sp=scenarios_with_plans())
    def test_each_robot_timeline_is_contiguous_from_start_to_finish(
        self, sp: tuple[Scenario, Plan]
    ) -> None:
        s, plan = sp
        result = simulate(s, plan)
        for r in s.robots:
            own = sorted((g for g in result.segments if g.robot == r.id), key=lambda g: g.t0)
            position, now = r.start, 0
            for g in own:
                assert (g.src, g.t0) == (position, now)  # 途切れ・重なりがない
                assert g.t1 > g.t0  # 長さ0の区間は出さない
                position, now = g.dst, g.t1
            assert now == result.metrics.per_robot[r.id].finish

    @given(sp=scenarios_with_plans())
    def test_segment_durations_follow_the_model(self, sp: tuple[Scenario, Plan]) -> None:
        s, plan = sp
        speeds = {r.id: r.speed for r in s.robots}
        services = {t.id: t.service_time for t in s.tasks}
        for g in simulate(s, plan).segments:
            if g.kind is SegmentKind.MOVE:
                assert g.t1 - g.t0 == travel_ticks(manhattan(g.src, g.dst), speeds[g.robot])
            else:
                assert g.src == g.dst
                assert g.t1 - g.t0 == services[g.task]

    @given(sp=scenarios_with_plans())
    def test_metrics_are_consistent_with_segments(self, sp: tuple[Scenario, Plan]) -> None:
        s, plan = sp
        result = simulate(s, plan)
        m = result.metrics
        finishes = [x.finish for x in m.per_robot.values()]
        assert m.makespan == max(finishes)
        assert m.total_distance == sum(
            manhattan(g.src, g.dst) for g in result.segments if g.kind is SegmentKind.MOVE
        )
        assert m.busy_total == sum(g.t1 - g.t0 for g in result.segments)
        assert m.available_total == len(s.robots) * m.makespan
        # このモデルには待ちがないので、稼働時間は完了時刻に一致する
        assert all(x.busy == x.finish for x in m.per_robot.values())
        assert m.busy_total == sum(finishes)

    @given(sp=scenarios_with_plans())
    def test_every_task_is_served_exactly_once(self, sp: tuple[Scenario, Plan]) -> None:
        s, plan = sp
        served = [g.task for g in simulate(s, plan).segments if g.kind is SegmentKind.SERVICE]
        # 生成器の service_time は 1 以上なので、全タスクに作業の区間がある
        assert sorted(served) == sorted(t.id for t in s.tasks)

    @given(sp=scenarios_with_plans())
    def test_utilization_is_a_valid_fraction(self, sp: tuple[Scenario, Plan]) -> None:
        s, plan = sp
        m = simulate(s, plan).metrics
        if m.available_total == 0:
            assert m.utilization is None
        else:
            assert m.utilization is not None
            assert 0 <= m.utilization <= 1

    @given(sp=scenarios_with_plans())
    def test_is_deterministic_and_segments_are_sorted(self, sp: tuple[Scenario, Plan]) -> None:
        s, plan = sp
        first = simulate(s, plan)
        assert simulate(s, plan) == first
        keys = [(g.t0, g.robot, g.kind is SegmentKind.SERVICE) for g in first.segments]
        assert keys == sorted(keys)
