"""公開するログとマニフェストを書き出す(ADR-0006)。

何を公開するかは、ここの1か所で決める。Pages のワークフローは `mrta publish` を呼ぶだけ。
ログはコミットせず、ビルド時に生成する(ADR-0004)。
"""

import json
from dataclasses import dataclass
from pathlib import Path

from mrta.catalog import SCENARIOS
from mrta.logio import render_log, write_log
from mrta.model import Scenario
from mrta.scenario import generate
from mrta.solvers import SOLVERS

# 公開するソルバ。`SOLVERS` の全件ではなく、**明示的に固定する**(ADR-0006: 比較は2画面なので、
# 1つの例に2つのログ)。ソルバを登録しても公開物は変わらない。
# CP-SAT は公開しない: 最適解が複数あるとき、選ばれる Plan が OR-Tools の版・OS で変わりうる
# (ADR-0007)ため、公開ログに向かない。公開するなら、ペアの出し方と合わせて別のADRで決める。
PUBLISHED_SOLVERS = ("greedy", "hungarian")

MANIFEST_VERSION = 1
MANIFEST_NAME = "manifest.json"
DEMO_NAME = "demo.jsonl"  # ビューアの既定の読み込み先(従来どおり: シード1、貪欲法)
DEMO_SEED = 1


@dataclass(frozen=True, slots=True)
class Example:
    """同じシナリオを公開するソルバで解いた、比較用のログ群。"""

    id: str
    scenario: Scenario

    def log_name(self, solver: str) -> str:
        return f"{self.id}-{solver}.jsonl"


def examples() -> tuple[Example, ...]:
    catalog = tuple(Example(id=name, scenario=make()) for name, make in sorted(SCENARIOS.items()))
    return (*catalog, Example(id=f"seed{DEMO_SEED}", scenario=generate(DEMO_SEED)))


def build_manifest(items: tuple[Example, ...]) -> str:
    """マニフェスト(JSON)。ログと同じ規則で決定的に書く(キーをソート、空白なし、末尾に改行)。"""
    solvers = sorted(PUBLISHED_SOLVERS)
    obj = {
        "manifest_version": MANIFEST_VERSION,
        "examples": [
            {"id": e.id, "title": e.id, "logs": [e.log_name(s) for s in solvers]} for e in items
        ],
    }
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def publish(out_dir: Path) -> list[Path]:
    """`out_dir` にログとマニフェストを書き、書いたファイルを返す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    items = examples()
    written: list[Path] = []
    for example in items:
        for solver_name in sorted(PUBLISHED_SOLVERS):
            path = out_dir / example.log_name(solver_name)
            write_log(path, render_log(example.scenario, SOLVERS[solver_name]()))
            written.append(path)
    demo = out_dir / DEMO_NAME
    write_log(demo, render_log(generate(DEMO_SEED), SOLVERS["greedy"]()))
    manifest = out_dir / MANIFEST_NAME
    write_log(manifest, build_manifest(items))
    return [*written, demo, manifest]
