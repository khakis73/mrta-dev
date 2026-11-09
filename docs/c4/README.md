# C4モデル(LikeC4)

[ADR-0002](../adr/0002-c4-dsl-selection.md) に従い、C4を [LikeC4](https://likec4.dev) のDSLで管理する。
モデルは1つで、図(ビュー)はそこから生成する。

| ファイル | 内容 |
|---|---|
| `spec.c4` | 要素の種別(kind)の定義 |
| `model.c4` | モデル本体(要素と関係) |
| `views.c4` | ビュー(C1/C2) |

## kind と C4 用語の対応

LikeC4 にはC4用語が組み込まれていないため、kind を自前で定義している。

| kind | C4の用語 |
|---|---|
| `person` | Person |
| `softwareSystem` | Software System(対象システム) |
| `externalSystem` | Software System(対象外の外部システム) |
| `container` | Container |
| `datastore` | Container(データストア。形状だけ変えている) |

## ビュー

| ビュー | C4の抽象度 | 方針 |
|---|---|---|
| `context` | C1: System Context | mrta をブラックボックスにし、内部要素は出さない |
| `containers` | C2: Container | mrta の内部と、関わる外部要素を出す |

関係はコンテナレベルで書く。C1 では自動で集約されるため、
ラベルは `views.c4` で上書きしている(未指定だと `[...]` になる)。

## 使い方

Node はグローバルに入れず、uv の仮想環境(`.venv`)に導入する。
バージョンはリポジトリ直下の `.node-version` で固定し、CI(`setup-node`)も同じファイルを読む。

```sh
./scripts/setup-node.sh              # 初回のみ(.venv に Node を導入。冪等)
cd docs/c4
uv run npm ci
uv run npm run validate              # 構文・参照の検証
uv run npm run build                 # 静的サイトを dist/ に出力
uv run npx likec4 start              # ローカルでプレビュー(編集に追従)
```

`likec4` のバージョンは `package.json` で固定している。更新時は `validate` と `build` が通ることを確認する。
Node の更新は `.node-version` を書き換えて `scripts/setup-node.sh` を再実行する(`likec4` の要求は `>=22.22.3`)。
