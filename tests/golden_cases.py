"""golden file の定義。固定シードのログを `tests/golden/<name>.jsonl` にコミットする(ADR-0004)。

Python のテスト(バイト一致)と、ビューアのテスト(同じファイルを読む)で共有する。
仕様やシナリオ生成を変えたら `UPDATE_GOLDEN=1 uv run pytest tests/test_golden.py` で更新し、
差分をレビューする。
"""

from dataclasses import dataclass
from pathlib import Path

from mrta.scenario import GeneratorConfig

GOLDEN_DIR = Path(__file__).parent / "golden"


@dataclass(frozen=True)
class GoldenCase:
    name: str
    seed: int
    config: GeneratorConfig
    solver: str

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
)
