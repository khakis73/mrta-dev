from collections.abc import Callable, Mapping

from mrta.solvers.base import ConfigValue, Solver, UnsolvableError, require_solvable
from mrta.solvers.cpsat import CpSatConfig, CpSatResult, CpSatSolver, solve_cpsat
from mrta.solvers.greedy import GreedySolver
from mrta.solvers.hungarian import HungarianSolver
from mrta.solvers.routing import RoutingConfig, RoutingResult, RoutingSolver, solve_routing

# 名前 → ソルバの生成。契約テストはここにある全てのソルバに対して走る。
# ソルバを足したら、ここに登録する(登録するだけで共通の契約テストの対象になる)。
SOLVERS: Mapping[str, Callable[[], Solver]] = {
    "greedy": GreedySolver,
    "cpsat": CpSatSolver,
    "hungarian": HungarianSolver,
    "routing": RoutingSolver,
}

__all__ = [
    "SOLVERS",
    "ConfigValue",
    "CpSatConfig",
    "CpSatResult",
    "CpSatSolver",
    "GreedySolver",
    "HungarianSolver",
    "RoutingConfig",
    "RoutingResult",
    "RoutingSolver",
    "Solver",
    "UnsolvableError",
    "require_solvable",
    "solve_cpsat",
    "solve_routing",
]
