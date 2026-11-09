from collections.abc import Callable, Mapping

from mrta.solvers.base import ConfigValue, Solver, UnsolvableError, require_solvable
from mrta.solvers.greedy import GreedySolver
from mrta.solvers.hungarian import HungarianSolver

# 名前 → ソルバの生成。契約テストはここにある全てのソルバに対して走る。
# ソルバを足したら、ここに登録する(登録するだけで共通の契約テストの対象になる)。
SOLVERS: Mapping[str, Callable[[], Solver]] = {
    "greedy": GreedySolver,
    "hungarian": HungarianSolver,
}

__all__ = [
    "SOLVERS",
    "ConfigValue",
    "GreedySolver",
    "HungarianSolver",
    "Solver",
    "UnsolvableError",
    "require_solvable",
]
