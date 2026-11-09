# viewer

JSONL ログ([ADR-0004](../docs/adr/0004-jsonl-log-schema.md))を読んで、ロボットの動きをリプレイする静的ビューア。
Vite + TypeScript。ブラウザ内で完結する(サーバーなし)。

コマンドは、リポジトリ直下の仮想環境の Node で実行する(`./scripts/setup-node.sh` で導入、`uv run …` 経由)。

```sh
cd viewer
uv run npm ci
uv run npm test         # 単体テスト(vitest)
uv run npm run build    # 型検査とビルド
```

## 画面を見る

公開用のログ(`demo.jsonl`、比較の例、`manifest.json`)を生成して `public/data/` に置く(コミットしない)。
Pages では、同じコマンドをビルド時に実行して同梱している。

```sh
uv run mrta publish --out viewer/public/data
cd viewer && uv run npm run dev
```

`?log=` で別のログを指定できる(同じオリジンのみ)。例: `?log=data/other.jsonl`

- `log` を2回指定すると、同じシナリオの2つのログを**同期して比較**する(時刻は共通)。
  例: `?log=data/greedy-trap-greedy.jsonl&log=data/greedy-trap-hungarian.jsonl`
  シナリオが一致しないログの組はエラーにする。3つ以上は受け付けない。
- `data/manifest.json` があれば、「比較の例」のリンクを出す(無くても閲覧はできる)。

## テスト

| 種類 | 対象 | コマンド |
|---|---|---|
| 単体(vitest) | ログの読み込み・検証、リプレイの計算、再生の状態、経路、比較(シナリオの一致・指標の優劣)、マニフェスト | `npm test` |
| e2e(Playwright) | 画面の表示・操作・エラー表示・スマホ幅・盤面のスクリーンショット | `npm run e2e` |

- 読む側の契約テスト: Python が書いた golden file(`../tests/golden`)を、単体テストと e2e の両方で読む。
- Playwright のブラウザは `node_modules` の中に入れる(グローバルに入れない)。

  ```sh
  PLAYWRIGHT_BROWSERS_PATH=0 uv run npx playwright install chromium
  ```

- `channel: "chromium"`(フルビルドの Chromium)を使う。既定の headless shell は、環境によって
  `requestAnimationFrame` が発火せず、再生とクリックの安定性チェックが止まる。

### スクリーンショットテストの方針

- **盤面(SVG)だけ**を撮る。盤面にはテキストを描かず、IDなどは HTML の表に出す。フォントの違うOSでも安定する。
- 基準画像は `e2e/__screenshots__/`(OS名を含めず共有)。許容は**画素数**(`maxDiffPixels`)で指定する。
  盤面は大半が白なので、割合で指定すると、ロボット1台の位置や形の違い(全体の1%前後)を飲み込む。
- 意図して見た目を変えたら、基準画像を更新して**画像を目で確認**してからコミットする。

  ```sh
  uv run npm run e2e:update -- --grep "スクリーンショット"
  ```

### 安全性

`?log=` で任意のログを読み込めるため、ログの文字列は **HTML として解釈させない**。
DOM は `createElement` と `textContent`・属性だけで作り、`innerHTML` は使わない(e2e で確認している)。
