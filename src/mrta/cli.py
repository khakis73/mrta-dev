"""コマンドライン: シナリオを生成し、ソルバで解いて、ログ(JSONL)を書き出す。

uv run mrta run --seed 0 --solver greedy --out runs/seed0-greedy.jsonl
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from mrta.catalog import SCENARIOS
from mrta.logio import render_log, write_log
from mrta.model import ModelError, Scenario
from mrta.scenario import GeneratorConfig, generate
from mrta.solvers import SOLVERS


def _parser() -> argparse.ArgumentParser:
    defaults = GeneratorConfig()
    parser = argparse.ArgumentParser(prog="mrta", description="タスク割当ソルバ比較シミュレータ")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="シナリオを生成して解き、ログ(JSONL)を書き出す")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--seed", type=int, help="生成するシナリオのシード")
    source.add_argument("--scenario", choices=sorted(SCENARIOS), help="手作りシナリオの名前")
    run.add_argument("--solver", choices=sorted(SOLVERS), required=True)
    run.add_argument("--out", type=Path, help="出力ファイル(省略時は標準出力)")
    # 未指定は None にして、既定値は GeneratorConfig に任せる(--scenario との併用を検出するため)。
    gen = run.add_argument_group(f"生成器の設定(--seed のときだけ。既定: {_describe(defaults)})")
    gen.add_argument("--width", type=int)
    gen.add_argument("--height", type=int)
    gen.add_argument("--amr", type=int, help="AMR の台数")
    gen.add_argument("--manipulators", type=int, help="モバイルマニピュレーターの台数")
    gen.add_argument("--tasks", type=int, help="タスクの数")
    gen.add_argument(
        "--manipulate-percent", type=int, help="操作スキルを要するタスクの割合(整数%%)"
    )
    return parser


def _describe(c: GeneratorConfig) -> str:
    return (
        f"width={c.width} height={c.height} amr={c.n_amr} manipulators={c.n_mobile_manipulators} "
        f"tasks={c.n_tasks} manipulate-percent={c.manipulate_percent}"
    )


def _scenario(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Scenario:
    overrides = {
        field: value
        for field, value in {
            "width": args.width,
            "height": args.height,
            "n_amr": args.amr,
            "n_mobile_manipulators": args.manipulators,
            "n_tasks": args.tasks,
            "manipulate_percent": args.manipulate_percent,
        }.items()
        if value is not None
    }
    if args.scenario is not None:
        if overrides:
            parser.error("--scenario と生成器の設定(--width など)は併用できない")
        return SCENARIOS[args.scenario]()
    return generate(args.seed, GeneratorConfig(**overrides))


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        text = render_log(_scenario(args, parser), SOLVERS[args.solver]())
    except ModelError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2

    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_log(args.out, text)
    return 0
