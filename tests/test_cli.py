from pathlib import Path

import pytest

from mrta.cli import main
from mrta.logio import check_log_structure, render_log
from mrta.scenario import GeneratorConfig, generate
from mrta.solvers import GreedySolver


def test_run_writes_the_same_log_as_the_library(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "run.jsonl"
    assert main(["run", "--seed", "3", "--solver", "greedy", "--out", str(out)]) == 0
    expected = render_log(generate(3), GreedySolver())
    assert out.read_bytes() == expected.encode("utf-8")
    check_log_structure(out.read_text(encoding="utf-8"))


def test_run_prints_to_stdout_without_out(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "--seed", "0", "--solver", "greedy", "--tasks", "2"]) == 0
    config = GeneratorConfig(n_tasks=2)
    assert capsys.readouterr().out == render_log(generate(0, config), GreedySolver())


def test_generator_options_are_passed_through(capsys: pytest.CaptureFixture[str]) -> None:
    args = [
        "run", "--seed", "5", "--solver", "greedy",
        "--width", "8", "--height", "9", "--amr", "1", "--manipulators", "1",
        "--tasks", "4", "--manipulate-percent", "50",
    ]  # fmt: skip
    assert main(args) == 0
    config = GeneratorConfig(
        width=8, height=9, n_amr=1, n_mobile_manipulators=1, n_tasks=4, manipulate_percent=50
    )
    assert capsys.readouterr().out == render_log(generate(5, config), GreedySolver())


def test_invalid_scenario_options_exit_with_code_2(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run", "--seed", "0", "--solver", "greedy", "--amr", "0", "--manipulators", "0"])
    assert code == 2
    assert "エラー" in capsys.readouterr().err


def test_unknown_solver_is_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit) as e:
        main(["run", "--seed", "0", "--solver", "nope"])
    assert e.value.code == 2
