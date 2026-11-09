"""ハンガリアン法(最小費用割当)のテスト。全探索の最適解との一致で、自前実装の正しさを担保する。"""

from itertools import permutations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mrta.solvers.assignment import solve_assignment


def total(cost: list[list[int]], columns: tuple[int, ...]) -> int:
    return sum(cost[i][j] for i, j in enumerate(columns))


def brute_force_min(cost: list[list[int]]) -> int:
    n, m = len(cost), len(cost[0])
    return min(total(cost, cols) for cols in permutations(range(m), n))


@st.composite
def matrices(draw: st.DrawFn) -> list[list[int]]:
    n = draw(st.integers(1, 5))
    m = draw(st.integers(n, 6))
    return [[draw(st.integers(0, 30)) for _ in range(m)] for _ in range(n)]


@given(cost=matrices())
def test_matches_brute_force_optimum(cost: list[list[int]]) -> None:
    columns = solve_assignment(cost)
    assert total(cost, columns) == brute_force_min(cost)


@given(cost=matrices())
def test_assigns_every_row_to_a_distinct_column(cost: list[list[int]]) -> None:
    columns = solve_assignment(cost)
    assert len(columns) == len(cost)
    assert len(set(columns)) == len(columns)
    assert all(0 <= j < len(cost[0]) for j in columns)


def test_known_example() -> None:
    cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
    assert solve_assignment(cost) == (1, 0, 2)  # 1 + 2 + 2 = 5


def test_empty_matrix() -> None:
    assert solve_assignment([]) == ()


def test_rejects_more_rows_than_columns() -> None:
    with pytest.raises(ValueError, match="行数 ≤ 列数"):
        solve_assignment([[1], [2]])
