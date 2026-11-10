"""コマンドライン: シナリオを生成し、ソルバで解いて、ログ(JSONL)を書き出す。

uv run mrta run --seed 0 --solver greedy --out runs/seed0-greedy.jsonl
"""

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from mrta.bench import PRESETS, render_json, render_markdown, run
from mrta.catalog import SCENARIOS
from mrta.logio import render_log, write_log
from mrta.model import ModelError, Scenario
from mrta.publish import publish
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

    pub = commands.add_parser(
        "publish", help="公開するログとマニフェストを書き出す(Pages のビルド用)"
    )
    pub.add_argument("--out", type=Path, required=True, help="出力ディレクトリ")

    bench = commands.add_parser(
        "bench", help="複数シードのベンチマーク(統計と下界ギャップ)を実行する"
    )
    bench.add_argument("--preset", choices=sorted(PRESETS), required=True)
    bench.add_argument("--seeds", type=int, help="シード数(先頭から。省略時はプリセットの既定)")
    bench.add_argument("--jobs", type=int, default=1, help="並列数(結果は並列数に依存しない)")
    bench.add_argument("--out", type=Path, help="出力ディレクトリ(bench.json と bench.md)")
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
    if args.command == "publish":
        publish(args.out)
        return 0
    if args.command == "bench":
        return _bench(args)
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


def _bench(args: argparse.Namespace) -> int:
    preset = PRESETS[args.preset]
    total = preset.seeds if args.seeds is None else args.seeds
    started = time.monotonic()

    def progress(done: int) -> None:  # 所要時間は標準エラーにだけ出す(結果は決定的に保つ)
        print(f"\r{done}/{total} ({time.monotonic() - started:.1f}s)", end="", file=sys.stderr)

    try:
        result = run(preset, seeds=args.seeds, jobs=args.jobs, on_done=progress)
    except ModelError as e:
        print(f"\nエラー: {e}", file=sys.stderr)
        return 2
    print(file=sys.stderr)

    markdown = render_markdown(result)
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        write_log(args.out / "bench.json", render_json(result))
        write_log(args.out / "bench.md", markdown)
    sys.stdout.write(markdown)
    return 0
