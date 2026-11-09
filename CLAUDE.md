# CLAUDE.md

異種ロボット(AMR + モバイルマニピュレーター)のタスク割当ソルバ比較シミュレータ。
目的・スコープ・フェーズは [README.md](README.md)、設計判断は [docs/adr/](docs/adr/) を正とする。
このファイルは要点と参照のみを書く(二重管理しない)。

## 最優先の方針

- 主目的は **設計(C4/ADR)・テスト設計・CI/CDの型の習得**。題材の作り込みは目的外。
- **学習優先で小さく作る。** 指標は「完了時間・総移動距離・稼働率・下界ギャップ」の4つのみ。
- スコープ外: AIエージェント/RAG、経路の衝突回避、モバイルマニピュレーターの物理挙動、常駐サーバー。
- 会社の設計・コード・データは持ち込まない。

## Git運用 (詳細: [ADR-0001](docs/adr/0001-branch-strategy-and-versioning.md))

- GitHub flow。`main` は常に緑。変更は短命ブランチ + PR。
- ブランチ名: `feat/…` `fix/…` `docs/…` `ci/…` `adr/…`(タスク単位で小さく)。
  この命名規則に沿った名前なら、ユーザーの許可なく push してよい。
- マージは通常のマージコミット(squash・rebaseは使わない)。
- **PRはユーザーが依頼するまで作らない。**
- タグは SemVer `v0.MINOR.PATCH`。`main` のマージコミットに打つ。
- ブランチの削除など、取り消しにくい操作は事前に確認する。

## 設計・実装の規約

- **決定性を守る:** シード固定、ソルバ設定固定(`num_workers=1`、タイムリミット固定)。
- 構成: Pythonコア → JSONL → TypeScript静的ビューア → GitHub Pages。
- **ツールは仮想環境に閉じる:** Python は `uv`、Node は `.venv` に導入する
  (`.node-version` で固定、`scripts/setup-node.sh`)。コマンドは `uv run …` 経由で実行し、
  グローバルにインストールしない。
- C4はDSLで書き、設計判断は ADR(`docs/adr/NNNN-タイトル.md`)に残す。
  計画や範囲を変えるときは、README と ADR を更新する。
- テスト: 全ソルバ共通の契約テスト、property-based test
  (全タスクがちょうど1回割当、スキル・容量制約を満たす)、
  ビューアは Playwright のスクリーンショット。
- 1シナリオの勝ち負けで判断せず、複数シードの統計と下界を併記する。

## 現在地 (Phase 0: 雛形)

進捗に応じてチェックを更新する。完了したらタグ `v0.0.1`。

- [x] ADR-0001: ブランチ戦略とバージョニング
- [x] ADR-0002: C4のDSL選定(LikeC4を採用)
- [x] Python骨組み(`uv` + `ruff` + `mypy` + `pytest`)と、空でも緑になるCI
- [x] C4 Context/Container図(DSL)
- [x] TypeScriptの空ビューア(`viewer/`、Vite + TypeScript)
- [x] GitHub Pages公開(ビューアとC4サイト)
- [x] ブランチ保護の設定(ruleset `protect-main`、リポジトリをPublic化して有効化)

## 出力の好み

- 日本語。体系的・構造的に、要点を絞って書く。冗長な説明は避ける。
- 客観的・批判的な分析を重視する(良い点だけでなく、リスクやトレードオフも示す)。
