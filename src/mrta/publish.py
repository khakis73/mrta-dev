"""公開するログとマニフェストを書き出す(ADR-0006・0013)。

何を公開するかは、ここの1か所で決める。Pages のワークフローは `mrta publish` を呼ぶだけ。
ログはコミットせず、ビルド時に生成する(ADR-0004)。

公開する例は、**予備測定で選んだ「見せるための例」**であり、代表的な結果ではない(ADR-0013)。
結論は複数シードの統計と下界(ベンチマーク。README)で出す。
"""

import json
from dataclasses import dataclass
from pathlib import Path

from mrta.catalog import SCENARIOS
from mrta.logio import render_log, write_log
from mrta.model import Scenario
from mrta.scenario import GeneratorConfig, generate
from mrta.solvers import ALL_SOLVERS, ONLINE_SOLVERS, SOLVERS, Solver

MANIFEST_VERSION = 2
MANIFEST_NAME = "manifest.json"
DEMO_NAME = "demo.jsonl"  # ビューアの既定の読み込み先(従来どおり: シード1、貪欲法)
DEMO_SEED = 1

# 動的な例の到着の窓(ADR-0011・0012)。静的な makespan(約25)の約8割。
ARRIVAL_WINDOW = 20


@dataclass(frozen=True, slots=True)
class Example:
    """同じシナリオを、複数のソルバで解いた比較用のログ群。"""

    id: str
    scenario: Scenario
    dynamic: bool
    default: tuple[str, str]  # 最初に選ぶ A・B のソルバ名
    note: str  # 画面に出す説明(マニフェストの description)。何を見せる例か、どこを見るか

    def solver_names(self) -> list[str]:
        """公開するソルバ。静的 → ローリングの順、各群は名前順(ADR-0013)。

        ローリング版は、動的な例だけ(静的では基底と同じ結果になる。ADR-0012)。
        """
        names = sorted(SOLVERS)
        if self.dynamic:
            names += sorted(ONLINE_SOLVERS)
        return names

    def make_solver(self, name: str) -> Solver:
        return ALL_SOLVERS[name]()

    def log_name(self, solver: str) -> str:
        return f"{self.id}-{solver}.jsonl"


def examples() -> tuple[Example, ...]:
    """公開する例。増やすときは、ここに足す(ADR-0013)。

    `note` は画面に出る説明(マニフェストの `description`)。**読み手に向けて**、何を見せる例か、
    どこを見ればよいかを書く。数値は `tests/test_publish.py` で固定している(ずれたら選び直す)。
    """
    dynamic = GeneratorConfig(arrival_window=ARRIVAL_WINDOW)
    tiny_dynamic = GeneratorConfig(
        n_amr=1, n_mobile_manipulators=2, n_tasks=5, arrival_window=ARRIVAL_WINDOW
    )
    return (
        # --- 静的な例(静的なソルバ4つ) ---
        Example(
            id="greedy-trap",
            scenario=SCENARIOS["greedy-trap"](),
            dynamic=False,
            default=("greedy", "hungarian"),
            note="手作りの例。貪欲法は、近いロボットに先に取らせて、もう一方のタスクが遠回りになる。"
            "ハンガリアン法は2タスクを同時に見る。",
        ),
        Example(
            id="skill-trap",
            scenario=SCENARIOS["skill-trap"](),
            dynamic=False,
            default=("greedy", "hungarian"),
            note="手作りの例。運搬タスクを近いマニピュレーターが取り、そのロボットしかできない"
            "操作タスクが待たされる(スキル制約が絡む失敗)。",
        ),
        Example(
            id=f"seed{DEMO_SEED}",
            scenario=generate(DEMO_SEED),
            dynamic=False,
            default=("greedy", "cpsat"),
            note="既定の規模(4台・10タスク)の、ふつうの例。貪欲法と CP-SAT で、"
            "完了時間が大きく違う。",
        ),
        Example(
            id="static-spread",
            scenario=generate(11),
            dynamic=False,
            default=("greedy", "cpsat"),
            note="ソルバの差が最も大きい例(4台・10タスク。40シードから選んだ)。"
            "完了時間は 貪欲 47、ハンガリアン 25、Routing・CP-SAT 20。",
        ),
        Example(
            id="static-15tasks",
            scenario=generate(1, GeneratorConfig(n_tasks=15)),
            dynamic=False,
            default=("greedy", "cpsat"),
            note="規模を上げた例(4台・15タスク)。完了時間は 貪欲 61、ハンガリアン 57、"
            "Routing・CP-SAT 40。",
        ),
        # --- 動的な例(静的なソルバ4つ + ローリング4つ。窓 20) ---
        Example(
            id="dynamic-rolling-wins",
            scenario=generate(11, dynamic),
            dynamic=True,
            default=("cpsat", "rolling-cpsat"),
            note="ローリングが静的に大きく勝つ例。到着を無視した静的な CP-SAT(完了時間 38)より、"
            "到着を知ってから決めるローリング CP-SAT(25)のほうが短い。"
            "「静的に最適」は、動的では最適ではない。",
        ),
        Example(
            id="dynamic-rolling-loses",
            scenario=generate(3, dynamic),
            dynamic=True,
            default=("cpsat", "rolling-cpsat"),
            note="ローリングが静的に負ける例(貪欲法でも CP-SAT でも 41 → 46)。"
            "この到着の並びでは、未来を知っている静的が有利になる。いつも勝つわけではない。",
        ),
        Example(
            id="dynamic-tiny",
            scenario=generate(0, tiny_dynamic),
            dynamic=True,
            default=("greedy", "rolling-greedy"),
            note="タスクが5つと少なく、経路を目で追いやすい例(貪欲 40 → ローリング貪欲 33)。",
        ),
    )


def build_manifest(items: tuple[Example, ...]) -> str:
    """マニフェスト v2(JSON)。ログと同じ規則で決定的に書く(キーをソート、空白なし、末尾に改行)。"""
    obj = {
        "manifest_version": MANIFEST_VERSION,
        "examples": [
            {
                "id": e.id,
                "title": e.id,
                "dynamic": e.dynamic,
                "default": {"a": e.default[0], "b": e.default[1]},
                "description": e.note,
                "logs": [{"file": e.log_name(s), "solver": s} for s in e.solver_names()],
            }
            for e in items
        ],
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def publish(out_dir: Path) -> list[Path]:
    """`out_dir` にログとマニフェストを書き、書いたファイルを返す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    items = examples()
    written: list[Path] = []
    for example in items:
        for solver_name in example.solver_names():
            path = out_dir / example.log_name(solver_name)
            write_log(path, render_log(example.scenario, example.make_solver(solver_name)))
            written.append(path)
    demo = out_dir / DEMO_NAME
    write_log(demo, render_log(generate(DEMO_SEED), SOLVERS["greedy"]()))
    manifest = out_dir / MANIFEST_NAME
    write_log(manifest, build_manifest(items))
    return [*written, demo, manifest]
