"""JSONL ログの書き出しと構造チェック(ADR-0004)。

- ログは決定的: 数値は整数のみ、キーはソート、空白なし、非ASCIIはエスケープ、末尾も改行。
  同じシナリオ・同じソルバ設定なら、バイト列が完全に一致する。
- 壁時計の時間やパッケージのバージョンは書かない(決定性のため)。
- 実行の意味は `mrta.sim` だけが持つ。ここは結果を書き出すだけで、再計算しない。
"""

import json
from pathlib import Path

from mrta.model import Plan, Robot, Scenario, Task
from mrta.sim import Metrics, Segment, SegmentKind, SimulationResult, simulate
from mrta.solvers import Solver

SCHEMA_VERSION = 1

type JsonObject = dict[str, object]

# 行の種類と順序(ADR-0004)。segment は 0 個以上、他は1個ずつ。
_HEAD = ("header", "scenario", "solver", "plan")
_KNOWN = frozenset({*_HEAD, "segment", "metrics"})


class LogFormatError(ValueError):
    """ログがADR-0004の形式(ファイル全体の規則)に反している。"""


def _line(obj: JsonObject) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _robot(r: Robot) -> JsonObject:
    return {
        "id": r.id,
        "kind": r.kind.value,
        "start": list(r.start),
        "speed": r.speed,
        "capacity": r.capacity,
        "skills": sorted(r.skills),
    }


def _task(t: Task) -> JsonObject:
    obj: JsonObject = {
        "id": t.id,
        "location": list(t.location),
        "required_skill": t.required_skill,
        "demand": t.demand,
        "service_time": t.service_time,
    }
    # 0 のときは書かない(ADR-0011)。静的なシナリオのログは従来とバイト単位で同じになる。
    if t.release_time > 0:
        obj["release_time"] = t.release_time
    return obj


def _segment(g: Segment) -> JsonObject:
    return {
        "type": "segment",
        "robot": g.robot,
        "kind": g.kind.value,
        "task": g.task,
        "from": list(g.src),
        "to": list(g.dst),
        "t0": g.t0,
        "t1": g.t1,
    }


def _metrics(m: Metrics) -> JsonObject:
    # 稼働率は割り算せず、整数の分子(busy_total)と分母(available_total)で持つ。
    return {
        "type": "metrics",
        "makespan": m.makespan,
        "total_distance": m.total_distance,
        "busy_total": m.busy_total,
        "available_total": m.available_total,
        "per_robot": {
            robot_id: {"finish": x.finish, "distance": x.distance, "busy": x.busy}
            for robot_id, x in m.per_robot.items()
        },
    }


def build_log(
    scenario: Scenario, solver: Solver, plan: Plan, result: SimulationResult
) -> list[JsonObject]:
    """ログの各行(オブジェクト)を、ADR-0004 の順序で返す。"""
    lines: list[JsonObject] = [
        {"type": "header", "schema_version": SCHEMA_VERSION},
        {
            "type": "scenario",
            "seed": scenario.seed,
            "width": scenario.width,
            "height": scenario.height,
            # ID の並びは文字列としての辞書順(数値順ではない)。
            "robots": [_robot(r) for r in sorted(scenario.robots, key=lambda r: r.id)],
            "tasks": [_task(t) for t in sorted(scenario.tasks, key=lambda t: t.id)],
        },
        {"type": "solver", "name": solver.name, "config": dict(solver.config)},
        {"type": "plan", "routes": {k: list(v) for k, v in plan.routes.items()}},
    ]
    lines.extend(_segment(g) for g in result.segments)  # simulate が整列済み
    lines.append(_metrics(result.metrics))
    return lines


def dumps_log(scenario: Scenario, solver: Solver, plan: Plan, result: SimulationResult) -> str:
    return "".join(_line(obj) + "\n" for obj in build_log(scenario, solver, plan, result))


def render_log(scenario: Scenario, solver: Solver) -> str:
    """解いて、実行して、ログの文字列にする。"""
    plan = solver.solve(scenario)
    return dumps_log(scenario, solver, plan, simulate(scenario, plan))


def write_log(path: Path, text: str) -> None:
    # OS 依存の改行変換を避け、常に LF・UTF-8 で書く。
    path.write_text(text, encoding="utf-8", newline="\n")


def _reject_float(token: str) -> object:
    raise LogFormatError(f"浮動小数点は書かない(整数のみ): {token}")


def _reject_constant(token: str) -> object:
    raise LogFormatError(f"NaN / Infinity は書かない: {token}")


def check_log_structure(text: str) -> None:
    """ファイル全体の規則を検査する(JSON Schema では書けない部分)。

    - UTF-8 のテキストが、改行(LF)で終わる。空行がない。全ての行が JSON のオブジェクト。
    - 数値は整数のみ。
    - 既知の行の並びは `header, scenario, solver, plan, segment*, metrics`。末尾は `metrics`。
    - 未知の `type` の行は無視する(後方互換な追加。ただし `metrics` の後ろには置けない)。
    - segment は t0 < t1(長さ0は書かない)で、整列済み。作業は from == to。
    """
    if not text.endswith("\n"):
        raise LogFormatError("末尾が改行で終わっていない(途中で切れている可能性)")

    objs: list[JsonObject] = []
    for number, raw in enumerate(text[:-1].split("\n"), start=1):
        if raw == "":
            raise LogFormatError(f"{number} 行目が空行")
        try:
            obj = json.loads(raw, parse_float=_reject_float, parse_constant=_reject_constant)
        except json.JSONDecodeError as e:
            raise LogFormatError(f"{number} 行目が JSON として不正: {e.msg}") from e
        if not isinstance(obj, dict) or not isinstance(obj.get("type"), str):
            raise LogFormatError(f"{number} 行目が type を持つオブジェクトではない")
        objs.append(obj)

    if objs[-1]["type"] != "metrics":
        raise LogFormatError(
            "末尾の行が metrics ではない(途中で切れている、または metrics の後ろに行がある)"
        )

    known = [str(o["type"]) for o in objs if o["type"] in _KNOWN]
    middle = known[len(_HEAD) : -1]
    if known[: len(_HEAD)] != list(_HEAD) or any(t != "segment" for t in middle):
        raise LogFormatError(
            f"行の並びが header, scenario, solver, plan, segment*, metrics ではない: {known}"
        )

    keys: list[tuple[int, str, int]] = []
    for g in (o for o in objs if o["type"] == "segment"):
        t0, t1 = g.get("t0"), g.get("t1")
        if not (isinstance(t0, int) and isinstance(t1, int) and t0 < t1):
            raise LogFormatError(f"segment は t0 < t1 でなければならない: {g}")
        is_service = g.get("kind") == SegmentKind.SERVICE.value
        if is_service and g.get("from") != g.get("to"):
            raise LogFormatError(f"service の segment は from == to でなければならない: {g}")
        keys.append((t0, str(g.get("robot")), 1 if is_service else 0))
    if keys != sorted(keys):
        raise LogFormatError("segment が (t0, ロボットID, kind) の順に並んでいない")
