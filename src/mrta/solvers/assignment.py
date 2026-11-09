"""最小費用の割当問題(ハンガリアン法、Kuhn–Munkres のポテンシャル法)。O(n²m)。

整数の費用だけを扱う。行 ≤ 列の長方形行列を解く(全ての行が、異なる列に割り当てられる)。
"""

from collections.abc import Sequence


def solve_assignment(cost: Sequence[Sequence[int]]) -> tuple[int, ...]:
    """各行に割り当てる列を返す。`cost[i][j]` は行 i を列 j に割り当てる費用。

    行数 ≤ 列数が前提。総和が最小になる割当を返す(同費用の最適解のどれを返すかは、
    行列の並びだけで決まる。決定的)。
    """
    n = len(cost)
    if n == 0:
        return ()
    m = len(cost[0])
    if n > m or any(len(row) != m for row in cost):
        raise ValueError(f"行数 ≤ 列数の長方形行列が必要: {n} 行 × {m} 列")

    inf = sum(abs(c) for row in cost for c in row) + 1
    # 1 始まり。0 番は番兵(未割当)。
    u = [0] * (n + 1)  # 行のポテンシャル
    v = [0] * (m + 1)  # 列のポテンシャル
    owner = [0] * (m + 1)  # owner[j] = 列 j に割り当て済みの行(0 なら空き)
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        owner[0] = i
        j0 = 0
        min_v = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = owner[j0]
            delta, j1 = inf, 0
            for j in range(1, m + 1):
                if used[j]:
                    continue
                reduced = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if reduced < min_v[j]:
                    min_v[j], way[j] = reduced, j0
                if min_v[j] < delta:
                    delta, j1 = min_v[j], j
            for j in range(m + 1):
                if used[j]:
                    u[owner[j]] += delta
                    v[j] -= delta
                else:
                    min_v[j] -= delta
            j0 = j1
            if owner[j0] == 0:
                break
        while j0:  # 増加路に沿って付け替える
            j1 = way[j0]
            owner[j0] = owner[j1]
            j0 = j1

    columns = [0] * n
    for j in range(1, m + 1):
        if owner[j]:
            columns[owner[j] - 1] = j - 1
    return tuple(columns)
