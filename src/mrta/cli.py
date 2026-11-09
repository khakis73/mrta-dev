"""コマンドライン: シナリオを生成し、ソルバで解いて、ログ(JSONL)を書き出す。

uv run mrta run --seed 0 --solver greedy --out runs/seed0-greedy.jsonl
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from mrta.logio import render_log, write_log
from mrta.model import ModelError
from mrta.scenario import GeneratorConfig, generate
from mrta.solvers import SOLVERS


def _parser() -> argparse.ArgumentParser:
    defaults = GeneratorConfig()
    parser = argparse.ArgumentParser(prog="mrta", description="タスク割当ソルバ比較シミュレータ")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="シナリオを生成して解き、ログ(JSONL)を書き出す")
    run.add_argument("--seed", type=int, required=True, help="シナリオのシード")
    run.add_argument("--solver", choices=sorted(SOLVERS), required=True)
    run.add_argument("--out", type=Path, help="出力ファイル(省略時は標準出力)")
    run.add_argument("--width", type=int, default=defaults.width)
    run.add_argument("--height", type=int, default=defaults.height)
    run.add_argument("--amr", type=int, default=defaults.n_amr, help="AMR の台数")
    run.add_argument(
        "--manipulators",
        type=int,
        default=defaults.n_mobile_manipulators,
        help="モバイルマニピュレーターの台数",
    )
    run.add_argument("--tasks", type=int, default=defaults.n_tasks, help="タスクの数")
    run.add_argument(
        "--manipulate-percent",
        type=int,
        default=defaults.manipulate_percent,
        help="操作スキルを要するタスクの割合(整数%%)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = GeneratorConfig(
            width=args.width,
            height=args.height,
            n_amr=args.amr,
            n_mobile_manipulators=args.manipulators,
            n_tasks=args.tasks,
            manipulate_percent=args.manipulate_percent,
        )
        text = render_log(generate(args.seed, config), SOLVERS[args.solver]())
    except ModelError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2

    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_log(args.out, text)
    return 0
