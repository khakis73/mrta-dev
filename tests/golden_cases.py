"""golden file の定義。固定シードのログを `tests/golden/<name>.jsonl` にコミットする(ADR-0004)。

Python のテスト(バイト一致)と、ビューアのテスト(同じファイルを読む)で共有する。
仕様やシナリオ生成を変えたら `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py` で更新し、
差分をレビューする。
"""

from dataclasses import dataclass
from pathlib import Path

from mrta.catalog import SCENARIOS
from mrta.model import Scenario
from mrta.scenario import GeneratorConfig, generate

GOLDEN_DIR = Path(__file__).parent / "golden"


@dataclass(frozen=True)
class GoldenCase:
    """固定シードの生成シナリオ、または名前つきの手作りシナリオ(`catalog`)のどちらか。"""

    name: str
    solver: str
    seed: int = 0
    config: GeneratorConfig = GeneratorConfig()
    catalog: str | None = None

    def scenario(self) -> Scenario:
        if self.catalog is not None:
            return SCENARIOS[self.catalog]()
        return generate(self.seed, self.config)

    @property
    def path(self) -> Path:
        return GOLDEN_DIR / f"{self.name}.jsonl"


CASES = (
    GoldenCase(
        name="tiny-greedy",
        seed=0,
        config=GeneratorConfig(width=10, height=10, n_amr=1, n_mobile_manipulators=1, n_tasks=3),
        solver="greedy",
    ),
    GoldenCase(name="default-greedy", seed=1, config=GeneratorConfig(), solver="greedy"),
    # 手作りシナリオ: 同じシナリオを2つのソルバで解いた対(ビューアの2画面比較の契約テスト用)。
    GoldenCase(name="greedy-trap-greedy", catalog="greedy-trap", solver="greedy"),
    GoldenCase(name="greedy-trap-hungarian", catalog="greedy-trap", solver="hungarian"),
)
