from collections.abc import Callable, Mapping

from mrta.solvers.base import ConfigValue, Solver, UnsolvableError, require_solvable
from mrta.solvers.cpsat import CpSatConfig, CpSatResult, CpSatSolver, solve_cpsat
from mrta.solvers.greedy import GreedySolver
from mrta.solvers.hungarian import HungarianSolver
from mrta.solvers.info import SOLVER_SUMMARIES
from mrta.solvers.rolling import RollingResult, RollingSolver, rolling_of, solve_rolling
from mrta.solvers.routing import RoutingConfig, RoutingResult, RoutingSolver, solve_routing

# 名前 → ソルバの生成。契約テストはここにある全てのソルバに対して走る。
# ソルバを足したら、ここに登録する(登録するだけで共通の契約テストの対象になる)。
SOLVERS: Mapping[str, Callable[[], Solver]] = {
    "greedy": GreedySolver,
    "cpsat": CpSatSolver,
    "hungarian": HungarianSolver,
    "routing": RoutingSolver,
}

# ローリングホライズン版(ADR-0012)。静的な `SOLVERS` を基底にする。`SOLVERS` には入れない:
# 静的なシナリオ(到着が全て0)では基底と同じ結果になり、静的なベンチマークの表に同じ行が増えるため。
ONLINE_SOLVERS: Mapping[str, Callable[[], Solver]] = {
    f"rolling-{name}": rolling_of(factory) for name, factory in SOLVERS.items()
}

# CLI と契約テストの対象(静的 + ローリング)。
ALL_SOLVERS: Mapping[str, Callable[[], Solver]] = {**SOLVERS, **ONLINE_SOLVERS}

__all__ = [
    "ALL_SOLVERS",
    "ONLINE_SOLVERS",
    "SOLVER_SUMMARIES",
    "SOLVERS",
    "ConfigValue",
    "CpSatConfig",
    "CpSatResult",
    "CpSatSolver",
    "GreedySolver",
    "HungarianSolver",
    "RollingResult",
    "RollingSolver",
    "RoutingConfig",
    "RoutingResult",
    "RoutingSolver",
    "Solver",
    "UnsolvableError",
    "require_solvable",
    "solve_cpsat",
    "solve_rolling",
    "solve_routing",
]
