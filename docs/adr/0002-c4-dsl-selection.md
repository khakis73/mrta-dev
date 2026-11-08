# ADR-0002: C4のDSL選定

- Status: Proposed
- Date: 2026-11-08

## Context

- 方針「設計をコード化する」に従い、C4図(Context/Container、必要ならComponent)をテキストで管理する。
- 主目的は **C4の型の習得**。図の見栄えの作り込みは目的外。
- 開発者は1人。成果物は静的サイト(GitHub Pages)のみで、サーバーは持たない。
- 既にNode/TypeScriptを使う(ビューア)。Java等の追加ランタイムは避けたい。
- CIで「DSLの構文検証 → ビルド → Pages公開」を回したい(CI/CDの練習対象でもある)。

### 評価軸

| 軸 | 重み | 理由 |
|---|---|---|
| 単一モデル + 複数ビュー | 高 | C4の本質。図ごとに別定義だと不整合が起きる |
| CI/Pagesとの相性(追加ランタイム、静的ビルド) | 高 | 学習対象のCI/CDに直結 |
| 学習の転用性(業界標準度) | 中 | 習得した型が他で使えるか |
| 保守性・成熟度 | 中 | 仕様変更で図が壊れないか |
| レイアウト制御・見栄え | 低 | 目的外 |

## Options

### A. Structurizr DSL

- C4の考案者系のツール。モデルを1つ定義し、そこから複数ビューを生成する。
- CLI(Java製)で Mermaid / PlantUML 等へのエクスポートと静的サイト出力(`static`)が可能。
- (+) 業界での認知が最も高く、C4の概念をそのまま学べる。転用性が高い。
- (−) Java/Dockerが必要で、Node中心のこのリポジトリでは追加ランタイムになる。
- (−) Mermaid/PlantUMLへの出力は静的で、レイアウトを調整できない。
  静的サイト出力ではドキュメント(文章)が除かれる。
- (−) 公開まで「エクスポート → 別ツールで整形」の工程が増える。

### B. LikeC4

- モデルを1つ定義し複数ビューを生成する点はStructurizrと同じ。要素種別(kind)は自分で定義する。
- `likec4 build` でインタラクティブな静的サイトを出力でき、公式テンプレートにPages用ワークフローがある。
- (+) Node(npm)のみで完結し、既存のTS環境・CIに載せやすい。
- (+) 出力がそのままPagesに置ける。ズームやビュー間遷移もスマホで見られる。
- (−) C4の用語(Person/System/Container)は組み込みではなく、kindとして自前定義が要る。
- (−) 比較的新しく、Structurizrより利用者が少ない。DSLやパッケージ構成が変わる可能性がある
  (旧 `@likec4/cli` はnpm上でdeprecated表示のため、導入時に現行のパッケージ名を公式Docsで確認する)。
- (−) 公式GitHub Actionでの公開に不具合報告があり(未解決かは未確認)、`npx` で直接ビルドする方が安全。

### C. Mermaid C4

- Markdown内に書け、GitHub上で追加ツールなしに描画される。
- (+) 導入コストが最小。
- (−) 公式Docsで **experimental** とされ、構文・属性が変わりうる。
  レイアウト指定、タグ、凡例などが未対応または効かない。
- (−) **モデルを持たない。** 図ごとに別々に書くため、Context/Containerの整合は手作業になる。
  これはC4を「コードとして管理する」目的に反する。

## Decision

**B. LikeC4 を採用する。**

- C4モデルは `docs/c4/` 配下の `.c4` ファイルに書く。
- CIで `npx likec4 build` を実行し、DSLの検証とビルドを兼ねる。成果物は他のPages成果物と合わせて公開する。
- 公式GitHub Actionは使わず、npmの `likec4` を直接実行する(上記の不具合報告を避ける)。
- バージョンは `package.json` で固定する(決定性・再現性の方針に合わせる)。

### 選定理由

1. 「単一モデル + 複数ビュー」を満たすのはAとBのみ。Cは目的に反するため除外。
2. AとBの差は主に **追加ランタイム(Java)の有無** と **転用性**。
   このプロジェクトはCIとPagesの練習が主目的で、Nodeだけで完結する方が学習コストが低い。
3. 転用性はAが勝る。ただしC4の概念(モデル・ビュー・抽象度)はDSLを問わず共通で、
   DSL固有の構文を覚える範囲は小さい。

## Consequences

- (+) ツールチェーンがNodeに統一され、CIの構成が単純になる。
- (+) 図がインタラクティブなサイトとして公開され、スマホで確認できる。
- (−) Structurizr DSL固有の知識は身につかない。
- (−) LikeC4の仕様変更に追従する必要がある。バージョン固定と、アップグレード時の
  ビルド確認で対処する。
- (−) kindの定義(Person/System/Container等)を自前で持つため、C4用語との対応を
  `docs/c4/` 内に明記する必要がある。

## 見直しの条件

次のいずれかが起きたら本ADRを見直す。

- LikeC4のメンテナンスが止まる、またはビルドが頻繁に壊れる。
- Structurizrの記法を学ぶ必要が出る(業務での利用予定など)。
- 図の数・複雑さが増し、LikeC4の表現力では足りなくなる。

## 実施前の確認事項

- 導入時に、現行のパッケージ名・CLIコマンド・Node最低バージョンを公式Docsで確認する。
- Context/Container図が1つのモデルから出ること、`build` が空でない図で成功することを、
  最初のPRで確認する。

## 参考

- [LikeC4 CLI](https://likec4.pages.dev/docs/tools/cli)
- [LikeC4 template(Pages用ワークフローを含む)](https://github.com/likec4/template)
- [Structurizr CLI export](https://docs.structurizr.com/cli/export)
- [Structurizr static site](https://docs.structurizr.com/static)
- [Mermaid C4 diagram](https://mermaid.js.org/syntax/c4)
