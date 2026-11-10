"""ログの書き出しと構造チェック(ADR-0004)のテスト。"""

import json
import re
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from jsonschema import Draft202012Validator

from mrta.logio import LogFormatError, check_log_structure, render_log
from mrta.model import Robot, RobotKind, Scenario, Task
from mrta.sim import simulate
from mrta.solvers import GreedySolver
from tests.builders import robot, task
from tests.strategies import scenarios

ROOT = Path(__file__).parent.parent
SCHEMA = json.loads((ROOT / "schema" / "log-v1.schema.json").read_text(encoding="utf-8"))
validator = Draft202012Validator(SCHEMA)


def adr_example() -> str:
    """ADR-0004 に載っているログの例(```jsonl ブロック)。ドキュメントと実装の乖離を検出する。"""
    text = (ROOT / "docs" / "adr" / "0004-jsonl-log-schema.md").read_text(encoding="utf-8")
    match = re.search(r"```jsonl\n(.*?)```", text, re.DOTALL)
    assert match, "ADR-0004 に ```jsonl ブロックがない"
    return match.group(1)


def lines_of(text: str) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in text.splitlines()]


def rebuild_scenario(line: dict[str, Any]) -> Scenario:
    """scenario 行から Scenario を再構成する(ビューアが再構成できることの確認)。"""
    return Scenario(
        seed=line["seed"],
        width=line["width"],
        height=line["height"],
        robots=tuple(
            Robot(
                id=r["id"],
                kind=RobotKind(r["kind"]),
                start=(r["start"][0], r["start"][1]),
                speed=r["speed"],
                capacity=r["capacity"],
                skills=frozenset(r["skills"]),
            )
            for r in line["robots"]
        ),
        tasks=tuple(
            Task(
                id=t["id"],
                location=(t["location"][0], t["location"][1]),
                required_skill=t["required_skill"],
                demand=t["demand"],
                service_time=t["service_time"],
                release_time=t.get("release_time", 0),  # 無ければ 0(ADR-0011)
            )
            for t in line["tasks"]
        ),
    )


def sorted_entities(s: Scenario) -> tuple[Any, ...]:
    return (
        s.seed,
        s.width,
        s.height,
        sorted(s.robots, key=lambda r: r.id),
        sorted(s.tasks, key=lambda t: t.id),
    )


def small_log() -> str:
    s = Scenario(seed=42, width=10, height=10, robots=(robot("r0"),), tasks=(task("t0"),))
    return render_log(s, GreedySolver())


class TestAdrExample:
    def test_output_matches_the_example_in_the_adr_byte_for_byte(self) -> None:
        assert small_log() == adr_example()

    def test_the_example_is_a_valid_log(self) -> None:
        check_log_structure(adr_example())
        for obj in lines_of(adr_example()):
            validator.validate(obj)


class TestWrittenLogs:
    @given(s=scenarios())
    def test_structure_and_schema_hold_for_any_scenario(self, s: Scenario) -> None:
        text = render_log(s, GreedySolver())
        check_log_structure(text)
        for obj in lines_of(text):
            validator.validate(obj)

    @given(s=scenarios())
    def test_every_line_is_canonical_ascii_json(self, s: Scenario) -> None:
        text = render_log(s, GreedySolver())
        assert text.isascii()
        assert "\r" not in text
        for raw in text.splitlines():
            canonical = json.dumps(
                json.loads(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            assert raw == canonical

    @given(s=scenarios())
    def test_is_byte_for_byte_deterministic(self, s: Scenario) -> None:
        assert render_log(s, GreedySolver()) == render_log(s, GreedySolver())

    @given(s=scenarios())
    def test_does_not_depend_on_the_order_of_robots_in_the_input(self, s: Scenario) -> None:
        reordered = replace(s, robots=tuple(reversed(s.robots)))
        assert render_log(reordered, GreedySolver()) == render_log(s, GreedySolver())

    @given(s=scenarios())
    def test_scenario_line_can_rebuild_the_scenario(self, s: Scenario) -> None:
        line = lines_of(render_log(s, GreedySolver()))[1]
        assert sorted_entities(rebuild_scenario(line)) == sorted_entities(s)

    @given(s=scenarios())
    def test_lines_carry_exactly_what_the_simulator_computed(self, s: Scenario) -> None:
        plan = GreedySolver().solve(s)
        result = simulate(s, plan)
        header, scenario_line, solver_line, plan_line, *rest = lines_of(
            render_log(s, GreedySolver())
        )
        *segment_lines, metrics_line = rest

        assert header == {"type": "header", "schema_version": 1}
        assert solver_line == {"type": "solver", "name": "greedy", "config": {}}
        assert plan_line["routes"] == {k: list(v) for k, v in plan.routes.items()}
        assert len(segment_lines) == len(result.segments)
        for obj, g in zip(segment_lines, result.segments, strict=True):
            assert (obj["robot"], obj["kind"], obj["task"], obj["t0"], obj["t1"]) == (
                g.robot,
                g.kind.value,
                g.task,
                g.t0,
                g.t1,
            )
            assert (obj["from"], obj["to"]) == (list(g.src), list(g.dst))

        m = result.metrics
        assert (metrics_line["makespan"], metrics_line["total_distance"]) == (
            m.makespan,
            m.total_distance,
        )
        assert (metrics_line["busy_total"], metrics_line["available_total"]) == (
            m.busy_total,
            m.available_total,
        )
        assert metrics_line["per_robot"] == {
            k: {"finish": x.finish, "distance": x.distance, "busy": x.busy}
            for k, x in m.per_robot.items()
        }
        # 稼働率は、ログの分子・分母から復元できる(割り算した値は書かない)
        if metrics_line["available_total"] == 0:
            assert m.utilization is None
        else:
            assert m.utilization == Fraction(
                metrics_line["busy_total"], metrics_line["available_total"]
            )
        assert scenario_line["type"] == "scenario"

    def test_ids_are_ordered_lexicographically_not_numerically(self) -> None:
        s = Scenario(
            seed=0,
            width=10,
            height=10,
            robots=tuple(robot(f"r{i}") for i in (2, 10, 1)),
            tasks=(),
        )
        scenario_line = lines_of(render_log(s, GreedySolver()))[1]
        assert [r["id"] for r in scenario_line["robots"]] == ["r1", "r10", "r2"]

    def test_non_ascii_ids_are_escaped(self) -> None:
        s = Scenario(seed=0, width=10, height=10, robots=(robot("ロボ"),), tasks=())
        text = render_log(s, GreedySolver())
        assert text.isascii()
        assert lines_of(text)[1]["robots"][0]["id"] == "ロボ"


class TestCheckLogStructure:
    def lines(self) -> list[str]:
        return small_log().splitlines()

    def check(self, lines: list[str], *, newline: bool = True) -> None:
        check_log_structure("\n".join(lines) + ("\n" if newline else ""))

    def test_a_valid_log_passes(self) -> None:
        self.check(self.lines())

    @pytest.mark.parametrize(
        ("name", "mutate"),
        [
            ("末尾に改行がない", lambda ls: (ls, False)),
            ("metrics がない(途中で切れた)", lambda ls: (ls[:-1], True)),
            ("最後の行が欠けている", lambda ls: (ls[:-1] + [ls[-1][:20]], True)),
            ("metrics の後ろに行がある", lambda ls: (ls + [ls[4]], True)),
            ("metrics が2回ある", lambda ls: (ls + [ls[-1]], True)),
            ("header が2回ある", lambda ls: ([ls[0], *ls], True)),
            ("scenario と solver の順序が逆", lambda ls: ([ls[0], ls[2], ls[1], *ls[3:]], True)),
            ("plan がない", lambda ls: ([*ls[:3], *ls[4:]], True)),
            ("空行がある", lambda ls: ([*ls[:2], "", *ls[2:]], True)),
            ("JSON として不正", lambda ls: ([*ls[:2], "{oops", *ls[2:]], True)),
            ("オブジェクトでない行", lambda ls: ([*ls[:2], "[1,2]", *ls[2:]], True)),
            ("metrics が segment より前にある", lambda ls: ([*ls[:4], ls[-1], *ls[4:-1]], True)),
        ],
    )
    def test_rejects_malformed_files(self, name: str, mutate: Any) -> None:
        lines, newline = mutate(self.lines())
        with pytest.raises(LogFormatError):
            self.check(lines, newline=newline)

    def test_missing_trailing_newline_is_reported_as_such(self) -> None:
        """拒否するだけでなく、原因(末尾の改行がない)が分かるメッセージにする。"""
        with pytest.raises(LogFormatError, match="改行"):
            self.check(self.lines(), newline=False)

    @pytest.mark.parametrize("bad_number", ["1.0", "1.5", "NaN", "Infinity", "1e2"])
    def test_rejects_non_integer_numbers(self, bad_number: str) -> None:
        lines = self.lines()
        lines[0] = f'{{"schema_version":{bad_number},"type":"header"}}'
        with pytest.raises(LogFormatError):
            self.check(lines)

    def test_rejects_zero_length_segments(self) -> None:
        lines = self.lines()
        seg = json.loads(lines[4])
        seg["t1"] = seg["t0"]
        lines[4] = json.dumps(seg, sort_keys=True, separators=(",", ":"))
        with pytest.raises(LogFormatError, match="t0 < t1"):
            self.check(lines)

    def test_rejects_service_that_moves(self) -> None:
        lines = self.lines()
        seg = json.loads(lines[5])
        assert seg["kind"] == "service"
        seg["to"] = [0, 0]
        lines[5] = json.dumps(seg, sort_keys=True, separators=(",", ":"))
        with pytest.raises(LogFormatError, match="from == to"):
            self.check(lines)

    def test_rejects_unsorted_segments(self) -> None:
        lines = self.lines()
        lines[4], lines[5] = lines[5], lines[4]
        with pytest.raises(LogFormatError):
            self.check(lines)

    def test_unknown_line_types_before_metrics_are_ignored(self) -> None:
        """後方互換な追加: 未知の type の行は、metrics の前なら無視される(ADR-0004)。"""
        lines = self.lines()
        extra = '{"note":"future extension","type":"annotation"}'
        self.check([*lines[:3], extra, *lines[3:]])  # 例外にならない
