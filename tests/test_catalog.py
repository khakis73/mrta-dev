"""手作りシナリオ(ADR-0005)。「見せるための例」が腐らないよう、期待値を固定する。"""

import pytest

from mrta.catalog import SCENARIOS
from mrta.model import validate_plan
from mrta.sim import simulate
from mrta.solvers import SOLVERS


def makespan(scenario_name: str, solver_name: str) -> int:
    s = SCENARIOS[scenario_name]()
    plan = SOLVERS[solver_name]().solve(s)
    validate_plan(s, plan)
    return simulate(s, plan).metrics.makespan


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_is_solvable(name: str) -> None:
    assert not SCENARIOS[name]().unservable_tasks()


@pytest.mark.parametrize(
    ("name", "greedy", "hungarian"),
    [
        ("greedy-trap", 11, 6),
        ("skill-trap", 5, 3),
    ],
)
def test_hungarian_beats_greedy_on_the_traps(name: str, greedy: int, hungarian: int) -> None:
    assert makespan(name, "greedy") == greedy
    assert makespan(name, "hungarian") == hungarian
    assert hungarian < greedy
