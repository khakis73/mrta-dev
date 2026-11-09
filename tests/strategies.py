"""hypothesis の戦略。生成器の設定とシナリオを、広い範囲で作る。"""

from hypothesis import strategies as st

from mrta.model import Scenario
from mrta.scenario import GeneratorConfig, generate

seeds = st.integers(-(2**31), 2**31)


@st.composite
def configs(draw: st.DrawFn) -> GeneratorConfig:
    n_amr = draw(st.integers(0, 4))
    n_mm = draw(st.integers(0 if n_amr > 0 else 1, 4))
    return GeneratorConfig(
        width=draw(st.integers(1, 30)),
        height=draw(st.integers(1, 30)),
        n_amr=n_amr,
        n_mobile_manipulators=n_mm,
        n_tasks=draw(st.integers(0, 30)),
        manipulate_percent=draw(st.integers(0, 100)) if n_mm > 0 else 0,
        amr_speed=draw(st.integers(1, 5)),
        amr_capacity=draw(st.integers(1, 12)),
        mm_speed=draw(st.integers(1, 5)),
        mm_capacity=draw(st.integers(1, 12)),
        max_service_time=draw(st.integers(1, 8)),
    )


@st.composite
def scenarios(draw: st.DrawFn) -> Scenario:
    return generate(draw(seeds), draw(configs()))
