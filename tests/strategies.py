"""hypothesis の戦略。生成器の設定とシナリオを、広い範囲で作る。"""

from dataclasses import replace

from hypothesis import strategies as st

from mrta.model import Plan, Scenario
from mrta.scenario import GeneratorConfig, generate

seeds = st.integers(-(2**31), 2**31)


@st.composite
def configs(
    draw: st.DrawFn,
    *,
    max_robots_per_kind: int = 4,
    max_tasks: int = 30,
    max_arrival_window: int = 30,
) -> GeneratorConfig:
    n_amr = draw(st.integers(0, max_robots_per_kind))
    n_mm = draw(st.integers(0 if n_amr > 0 else 1, max_robots_per_kind))
    return GeneratorConfig(
        width=draw(st.integers(1, 30)),
        height=draw(st.integers(1, 30)),
        n_amr=n_amr,
        n_mobile_manipulators=n_mm,
        n_tasks=draw(st.integers(0, max_tasks)),
        manipulate_percent=draw(st.integers(0, 100)) if n_mm > 0 else 0,
        amr_speed=draw(st.integers(1, 5)),
        amr_capacity=draw(st.integers(1, 12)),
        mm_speed=draw(st.integers(1, 5)),
        mm_capacity=draw(st.integers(1, 12)),
        max_service_time=draw(st.integers(1, 8)),
        arrival_window=draw(st.integers(0, max_arrival_window)),
    )


@st.composite
def with_ready_at(draw: st.DrawFn, s: Scenario, max_ready_at: int) -> Scenario:
    """各ロボットに `ready_at`(0 以上)を付ける(ADR-0012)。生成器は常に 0 なので、テストで足す。"""
    robots = tuple(replace(r, ready_at=draw(st.integers(0, max_ready_at))) for r in s.robots)
    return replace(s, robots=robots)


@st.composite
def scenarios(draw: st.DrawFn, *, max_ready_at: int = 0) -> Scenario:
    """既定は `ready_at` が 0(通常のシナリオ)。契約テストなどは `max_ready_at` を指定する。"""
    s = generate(draw(seeds), draw(configs()))
    return draw(with_ready_at(s, max_ready_at)) if max_ready_at > 0 else s


@st.composite
def small_scenarios(
    draw: st.DrawFn,
    *,
    max_robots_per_kind: int = 2,
    max_tasks: int = 6,
    max_arrival_window: int = 0,
    max_ready_at: int = 0,
) -> Scenario:
    """厳密解のソルバ(CP-SAT)や全探索を回せる規模のシナリオ。

    既定は**静的**(到着の窓 0)。静的ソルバのモデルは到着時刻を見ないので、モデルの値と
    シミュレータの値の一致や、全探索との一致は、静的なシナリオでだけ成り立つ(ADR-0011)。
    """
    config = draw(
        configs(
            max_robots_per_kind=max_robots_per_kind,
            max_tasks=max_tasks,
            max_arrival_window=max_arrival_window,
        )
    )
    s = generate(draw(seeds), config)
    return draw(with_ready_at(s, max_ready_at)) if max_ready_at > 0 else s


# 契約テストで、ソルバごとに使うシナリオの戦略。指定がなければ `scenarios()`。
# 厳密解・メタヒューリスティックのソルバは規模が大きいと遅い(ADR-0007、0009)ので、小さな規模に絞る。
CONTRACT_SCENARIOS: dict[str, st.SearchStrategy[Scenario]] = {
    "cpsat": small_scenarios(
        max_robots_per_kind=2, max_tasks=6, max_arrival_window=30, max_ready_at=30
    ),
    # Routing(GLS)は1例あたり数百 ms かかりうる。大きな戦略(30タスク)では契約テストが2分を超えた。
    "routing": small_scenarios(
        max_robots_per_kind=2, max_tasks=6, max_arrival_window=30, max_ready_at=30
    ),
}


def contract_scenarios(solver_name: str) -> st.SearchStrategy[Scenario]:
    return CONTRACT_SCENARIOS.get(solver_name, scenarios(max_ready_at=30))


@st.composite
def scenarios_with_plans(draw: st.DrawFn) -> tuple[Scenario, Plan]:
    """ソルバに依存しない、ランダムな有効な Plan。

    各タスクを適格なロボットのうち任意の1台に割り当て、実行順も任意に並べる。
    シミュレータを、特定のソルバの癖から切り離して検証するために使う。
    """
    s = draw(scenarios())
    routes: dict[str, list[str]] = {r.id: [] for r in s.robots}
    for task in draw(st.permutations(s.tasks)):
        robot = draw(st.sampled_from(s.eligible_robots(task)))
        routes[robot.id].append(task.id)
    return s, Plan({robot_id: tuple(ids) for robot_id, ids in routes.items()})
