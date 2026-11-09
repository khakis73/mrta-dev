"""JSON Schema(schema/log-v1.schema.json)のテスト。ADR-0004 の契約。"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

SCHEMA_PATH = Path(__file__).parent.parent / "schema" / "log-v1.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
validator = Draft202012Validator(SCHEMA)

# 各 type の、最小限の有効な行
VALID: dict[str, dict[str, Any]] = {
    "header": {"type": "header", "schema_version": 1},
    "scenario": {
        "type": "scenario",
        "seed": 42,
        "width": 10,
        "height": 10,
        "robots": [
            {
                "id": "r0",
                "kind": "amr",
                "start": [0, 0],
                "speed": 2,
                "capacity": 5,
                "skills": ["carry"],
            }
        ],
        "tasks": [
            {
                "id": "t0",
                "location": [3, 4],
                "required_skill": "carry",
                "demand": 1,
                "service_time": 2,
            }
        ],
    },
    "solver": {
        "type": "solver",
        "name": "greedy",
        "config": {"num_workers": 1, "mode": "x", "f": True},
    },
    "plan": {"type": "plan", "routes": {"r0": ["t0"]}},
    "segment": {
        "type": "segment",
        "robot": "r0",
        "kind": "move",
        "task": "t0",
        "from": [0, 0],
        "to": [3, 4],
        "t0": 0,
        "t1": 4,
    },
    "metrics": {
        "type": "metrics",
        "makespan": 6,
        "total_distance": 7,
        "busy_total": 6,
        "available_total": 6,
        "per_robot": {"r0": {"finish": 6, "distance": 7, "busy": 6}},
    },
}


def valid(type_: str) -> dict[str, Any]:
    return copy.deepcopy(VALID[type_])


def test_the_schema_itself_is_a_valid_json_schema() -> None:
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("type_", VALID)
def test_valid_lines_pass(type_: str) -> None:
    validator.validate(VALID[type_])


@pytest.mark.parametrize("type_", VALID)
def test_unknown_extra_fields_are_allowed(type_: str) -> None:
    """後方互換な追加(任意のフィールド)は、読む側が無視できる(ADR-0004)。"""
    line = valid(type_)
    line["future_field"] = {"anything": [1, 2, 3]}
    validator.validate(line)


def test_unknown_line_types_are_allowed() -> None:
    validator.validate({"type": "annotation", "text": "future"})


def test_a_line_without_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        validator.validate({"schema_version": 1})


@pytest.mark.parametrize(
    ("type_", "key"),
    [(type_, key) for type_ in VALID for key in VALID[type_] if key != "type"],
)
def test_every_field_is_required(type_: str, key: str) -> None:
    line = valid(type_)
    del line[key]
    with pytest.raises(ValidationError):
        validator.validate(line)


def mutated(type_: str, edit: Any) -> dict[str, Any]:
    line = valid(type_)
    edit(line)
    return line


@pytest.mark.parametrize(
    ("type_", "edit"),
    [
        ("header", lambda ln: ln.update(schema_version=2)),  # 未対応の版
        ("scenario", lambda ln: ln.update(seed="42")),
        ("scenario", lambda ln: ln.update(width=0)),
        ("scenario", lambda ln: ln.update(robots=[])),  # ロボットは1台以上
        ("scenario", lambda ln: ln["robots"][0].update(speed=0)),
        ("scenario", lambda ln: ln["robots"][0].update(speed=1.5)),  # 浮動小数点
        ("scenario", lambda ln: ln["robots"][0].update(start=[0, 0, 0])),  # 3要素
        ("scenario", lambda ln: ln["robots"][0].update(start=[-1, 0])),  # 負の座標
        ("scenario", lambda ln: ln["robots"][0].update(skills=[])),
        ("scenario", lambda ln: ln["robots"][0].update(skills=["carry", "carry"])),
        ("scenario", lambda ln: ln["tasks"][0].update(demand=0)),
        ("scenario", lambda ln: ln["tasks"][0].update(service_time=-1)),
        ("solver", lambda ln: ln["config"].update(limit=1.5)),  # config に浮動小数点
        ("solver", lambda ln: ln["config"].update(limit=None)),
        ("solver", lambda ln: ln["config"].update(limit=[1])),
        ("plan", lambda ln: ln["routes"].update(r1="t1")),  # 配列でない
        ("plan", lambda ln: ln["routes"].update(r1=[1])),  # ID が文字列でない
        ("segment", lambda ln: ln.update(kind="fly")),
        ("segment", lambda ln: ln.update(t0=-1)),
        ("segment", lambda ln: ln.update(t1=4.5)),
        ("segment", lambda ln: ln.update({"from": [0]})),
        ("metrics", lambda ln: ln.update(makespan=-1)),
        ("metrics", lambda ln: ln.update(makespan=6.5)),
        ("metrics", lambda ln: ln["per_robot"]["r0"].pop("busy")),
    ],
)
def test_invalid_lines_are_rejected(type_: str, edit: Any) -> None:
    with pytest.raises(ValidationError):
        validator.validate(mutated(type_, edit))
