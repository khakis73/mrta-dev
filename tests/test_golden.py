"""golden file のテスト(ADR-0004)。

生成したログが、コミット済みの golden と**バイト一致**すること(決定性)。
ビューアのテストは、同じファイルを読み込む(読む側の契約テスト)。

更新: `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py` のあと、差分をレビューする。
"""

import json
import os

import pytest

from mrta.logio import check_log_structure, render_log, write_log
from mrta.scenario import generate
from mrta.solvers import SOLVERS
from tests.golden_cases import CASES, GoldenCase


def render(case: GoldenCase) -> str:
    return render_log(generate(case.seed, case.config), SOLVERS[case.solver]())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_matches_the_committed_golden_file(case: GoldenCase) -> None:
    text = render(case)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        write_log(case.path, text)
    assert case.path.exists(), "golden がない。UPDATE_GOLDEN=1 で作成する"
    assert case.path.read_bytes() == text.encode("utf-8")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_golden_files_are_valid_logs(case: GoldenCase) -> None:
    check_log_structure(case.path.read_text(encoding="utf-8"))


def test_tiny_golden_metrics_match_a_hand_calculation() -> None:
    """golden が「実装の出力を写しただけ」にならないよう、1つは手計算の値と突き合わせる。

    シナリオ(seed 0): r0=AMR (6,6) 速度3 容量10 / r1=MM (0,4) 速度1 容量3
      t0 (8,7) carry demand5 作業4 → AMR のみ適格。r0: 距離3 → ceil(3/3)=1、+4 → 完了5
      t1 (5,9) manipulate demand3 作業2 → MM のみ。r1: 距離10 → 10、+2 → 完了12
      t2 (4,2) carry demand2 作業5 → r0: (8,7)から距離9 → 3 ティック、5+3+5=13
                                     r1: (5,9)から距離8 → 8 ティック、12+8+5=25 → r0 を選ぶ
    r0 の経路 [t0, t2] は完了13・距離 3+9=12、稼働13。r1 の経路 [t1] は完了12・距離10、稼働12。
    """
    lines = [json.loads(raw) for raw in CASES[0].path.read_text(encoding="utf-8").splitlines()]
    plan = next(ln for ln in lines if ln["type"] == "plan")
    metrics = next(ln for ln in lines if ln["type"] == "metrics")
    assert plan["routes"] == {"r0": ["t0", "t2"], "r1": ["t1"]}
    assert metrics["per_robot"] == {
        "r0": {"finish": 13, "distance": 12, "busy": 13},
        "r1": {"finish": 12, "distance": 10, "busy": 12},
    }
    assert (metrics["makespan"], metrics["total_distance"]) == (13, 22)
    assert (metrics["busy_total"], metrics["available_total"]) == (25, 26)
