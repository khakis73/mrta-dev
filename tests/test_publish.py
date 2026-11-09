import json
from pathlib import Path

from mrta.cli import main
from mrta.logio import check_log_structure
from mrta.publish import DEMO_NAME, MANIFEST_NAME, MANIFEST_VERSION
from tests.golden_cases import GOLDEN_DIR


def published(tmp_path: Path) -> Path:
    assert main(["publish", "--out", str(tmp_path / "data")]) == 0
    return tmp_path / "data"


def scenario_line(path: Path) -> str:
    return next(ln for ln in path.read_text(encoding="utf-8").splitlines() if '"scenario"' in ln)


def test_every_manifest_log_exists_and_is_valid(tmp_path: Path) -> None:
    out = published(tmp_path)
    manifest = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest["examples"]
    for example in manifest["examples"]:
        for name in example["logs"]:
            check_log_structure((out / name).read_text(encoding="utf-8"))


def test_logs_of_an_example_share_the_same_scenario(tmp_path: Path) -> None:
    """比較の前提(ADR-0004): 同じ例のログは scenario 行が一致する。"""
    out = published(tmp_path)
    manifest = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    for example in manifest["examples"]:
        assert len(example["logs"]) >= 2
        lines = {scenario_line(out / name) for name in example["logs"]}
        assert len(lines) == 1, example["id"]


def test_catalog_logs_are_the_golden_files(tmp_path: Path) -> None:
    out = published(tmp_path)
    for solver in ("greedy", "hungarian"):
        name = f"greedy-trap-{solver}.jsonl"
        assert (out / name).read_bytes() == (GOLDEN_DIR / name).read_bytes()


def test_demo_log_is_kept_for_the_viewer_default(tmp_path: Path) -> None:
    out = published(tmp_path)
    check_log_structure((out / DEMO_NAME).read_text(encoding="utf-8"))


def test_publish_is_deterministic(tmp_path: Path) -> None:
    first = published(tmp_path / "a")
    second = published(tmp_path / "b")
    names = sorted(p.name for p in first.iterdir())
    assert names == sorted(p.name for p in second.iterdir())
    assert all((first / n).read_bytes() == (second / n).read_bytes() for n in names)
