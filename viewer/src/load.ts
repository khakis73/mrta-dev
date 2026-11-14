// ログ・マニフェストの取得。取り出して、単体でテストできるようにしてある(main.ts は import すると動き出す)。

/**
 * 公開サイトと同じオリジンのログだけを読む(ADR-0004: ログは Pages のビルドで生成して同梱する)。
 *
 * **キャッシュを使わず、毎回サーバーに更新の有無を確認する(`no-cache`)。**
 * GitHub Pages は全ファイルに `max-age=600` を付けるので、既定のままだと、デプロイ直後の10分間、
 * 新しいビューアが古い manifest.json・ログを使い、「比較の例」が古いままになる(実際に起きた)。
 * `no-cache` は、ETag で確認するだけで、変更がなければ本体は転送されない(小さなファイルなので十分)。
 */
export async function loadText(path: string, base: string, origin: string): Promise<Response> {
  const url = new URL(path, base);
  if (url.origin !== origin) {
    throw new Error("同じオリジンのログだけを読み込める");
  }
  const response = await fetch(url, { cache: "no-cache" });
  if (!response.ok) {
    throw new Error(`ログを取得できなかった(HTTP ${response.status}): ${url.pathname}`);
  }
  return response;
}
