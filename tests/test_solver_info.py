"""ソルバの説明(画面と README に出す。ADR-0013)のテスト。

説明の元は `mrta.solvers.info` の1か所。ソルバを足したのに説明を忘れる、README に載せ忘れる、
README に書いた性質が実装と食い違う、を防ぐ。
"""

import re
from dataclasses import replace
from pathlib import Path

import pytest

from mrta.scenario import GeneratorConfig, generate
from mrta.solvers import ALL_SOLVERS, ONLINE_SOLVERS, SOLVER_SUMMARIES, SOLVERS

README = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")


class TestSummaries:
    def test_every_registered_solver_has_a_summary_and_nothing_extra(self) -> None:
        """登録したのに説明を忘れる・消したソルバの説明が残る、を防ぐ。"""
        assert set(SOLVER_SUMMARIES) == set(ALL_SOLVERS)

    @pytest.mark.parametrize("name", sorted(ALL_SOLVERS))
    def test_a_summary_is_a_short_sentence_for_a_phone_screen(self, name: str) -> None:
        summary = SOLVER_SUMMARIES[name]
        assert summary.strip() == summary and summary.endswith("。")
        assert 20 <= len(summary) <= 100, (name, len(summary))

    def test_summaries_are_distinct(self) -> None:
        assert len(set(SOLVER_SUMMARIES.values())) == len(SOLVER_SUMMARIES)

    def test_a_rolling_summary_names_its_base_and_says_it_does_not_know_the_future(self) -> None:
        labels = {
            "greedy": "貪欲法",
            "hungarian": "ハンガリアン法",
            "routing": "Routing",
            "cpsat": "CP-SAT",
        }
        for name in ONLINE_SOLVERS:
            summary = SOLVER_SUMMARIES[name]
            assert f"「{labels[name.removeprefix('rolling-')]}」を" in summary, name
            assert "解き直す" in summary, name
            # ローリングの肝心な性質。静的ソルバとの違いが、この1文で伝わる。
            assert "未来のタスクは知らない" in summary, name

    def test_a_static_summary_does_not_claim_the_rolling_properties(self) -> None:
        """静的な要約に、ローリングの性質を混ぜない(取り違えの防止)。"""
        for name in SOLVERS:
            assert "解き直す" not in SOLVER_SUMMARIES[name], name
            assert "未来のタスクは知らない" not in SOLVER_SUMMARIES[name], name

    def test_the_summary_states_what_distinguishes_each_static_solver(self) -> None:
        """各ソルバを区別する、定義の核。これを落とすと、説明が説明にならない。"""
        assert "順に" in SOLVER_SUMMARIES["greedy"] and "順序に依存" in SOLVER_SUMMARIES["greedy"]
        assert (
            "総和" in SOLVER_SUMMARIES["hungarian"]
            and "全体の完了時間ではない" in SOLVER_SUMMARIES["hungarian"]
        )
        assert (
            "局所探索" in SOLVER_SUMMARIES["routing"]
            and "保証はない" in SOLVER_SUMMARIES["routing"]
        )
        assert "最小化" in SOLVER_SUMMARIES["cpsat"] and "証明" in SOLVER_SUMMARIES["cpsat"]
        assert "到着時刻は見ない" in SOLVER_SUMMARIES["cpsat"]

    def test_summaries_do_not_carry_measurements_that_can_drift(self) -> None:
        """測定値(%・小数・単位つきの数)は README とベンチマークに置く。ずれると嘘になるため。

        「1対1」のような概念の数は、測定値ではないので許す。
        **限界:** 正規表現なので、言い回しによっては通る(例: 「約3割」)。書くときに気をつける。
        """
        measurement = re.compile(r"\d+(\.\d+)?\s*(%|％|秒|ティック|タスク|台|件|倍)|\d+\.\d+")
        for name, summary in SOLVER_SUMMARIES.items():
            assert not measurement.search(summary), (name, summary)


def readme_section() -> str:
    return README.split("## ソルバの定義と違い")[1].split("\n## ")[0]


def table_rows() -> list[str]:
    """節の表の、各行の先頭のセル(ソルバ名)。ヘッダと区切りは除く。"""
    cells = [
        line.split("|")[1].strip()
        for line in readme_section().splitlines()
        if line.startswith("|") and not line.startswith("|---")
    ]
    return cells[1:]  # 先頭はヘッダ


class TestReadme:
    def test_every_solver_has_a_row_in_the_readme_table(self) -> None:
        """表の行を検査する。節のどこかに名前が出るだけでは、表から落としても気づけない。"""
        first_cells = table_rows()
        for name in SOLVERS:
            assert any(cell.startswith(f"`{name}`") for cell in first_cells), name
        assert any(cell.startswith("`rolling-*`") for cell in first_cells)

    def test_the_table_has_no_unknown_solver(self) -> None:
        known = {f"`{name}`" for name in SOLVERS} | {"`rolling-*`"}
        for cell in table_rows():
            assert cell.split("(")[0] in known, cell

    def test_the_readme_links_the_adr_of_each_solver(self) -> None:
        for adr in ("0005", "0007", "0009", "0012"):
            assert f"docs/adr/{adr}-" in readme_section(), adr
            assert any(Path(__file__).parent.parent.joinpath("docs/adr").glob(f"{adr}-*.md")), adr


class TestClaimsMatchTheImplementation:
    """README と要約に書いた性質が、実装で成り立つ。"""

    def test_only_greedy_depends_on_the_order_of_tasks(self) -> None:
        """「greedy は順序に依存する。他の3つは、タスクの並びに依存しない」"""
        changed = {name: 0 for name in SOLVERS}
        for seed in range(15):
            s = generate(seed, GeneratorConfig(n_tasks=8))
            reversed_order = replace(s, tasks=s.tasks[::-1])
            for name, make in SOLVERS.items():
                if make().solve(s) != make().solve(reversed_order):
                    changed[name] += 1
        assert changed["greedy"] > 0
        assert changed["hungarian"] == changed["cpsat"] == changed["routing"] == 0

    def test_static_solvers_do_not_look_at_the_release_time(self) -> None:
        """「静的な4つは、到着時刻を見ない」: 到着時刻を変えても、Plan は変わらない。"""
        for seed in range(8):
            dynamic = generate(seed, GeneratorConfig(n_tasks=6, arrival_window=20))
            static = replace(
                dynamic, tasks=tuple(replace(t, release_time=0) for t in dynamic.tasks)
            )
            for name, make in SOLVERS.items():
                assert make().solve(dynamic) == make().solve(static), name
