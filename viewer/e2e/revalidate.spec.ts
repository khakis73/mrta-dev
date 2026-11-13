import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { expect, test } from "@playwright/test";

// GitHub Pages と同じく、全ファイルに max-age=600 と ETag を付けて配信するサーバー。
// どのパスに何回リクエストが届いたか、条件付きリクエスト(If-None-Match)だったかを記録する。
// (ブラウザは favicon.ico なども自動で取りに来るので、対象のパスだけを数える。)
interface Hit {
  path: string;
  conditional: boolean;
}

let server: Server;
let origin: string;
let hits: Hit[] = [];
let etag = '"v1"';

test.beforeAll(async () => {
  server = createServer((req: IncomingMessage, res) => {
    hits.push({ path: req.url ?? "", conditional: req.headers["if-none-match"] !== undefined });
    res.setHeader("Cache-Control", "max-age=600");
    res.setHeader("ETag", etag);
    res.setHeader("Access-Control-Allow-Origin", "*");
    if (req.headers["if-none-match"] === etag) {
      res.statusCode = 304;
      res.end();
      return;
    }
    res.setHeader("Content-Type", "text/plain");
    res.end(`body ${etag}`);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});

test.afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

test.beforeEach(() => {
  hits = [];
  etag = '"v1"';
});

const MANIFEST = "/data/manifest.json";
/** manifest.json にサーバーまで届いたリクエスト */
const manifestHits = () => hits.filter((h) => h.path === MANIFEST);

/** ブラウザ内で fetch を実行する(ビューアの取得と同じ呼び出し)。 */
async function get(page: import("@playwright/test").Page, path: string, init: RequestInit | undefined) {
  return page.evaluate(
    async ([url, options]) => (await fetch(url as string, options as RequestInit)).text(),
    [`${origin}${path}`, init] as const,
  );
}

test.describe("キャッシュの再確認(GitHub Pages の max-age=600)", () => {
  test("対照: 指定なしだと、max-age の間は、2回目はサーバーに届かず、古いまま", async ({ page }) => {
    await page.goto(`${origin}/`);
    await get(page, MANIFEST, undefined);
    etag = '"v2"'; // デプロイで中身が変わった
    const second = await get(page, MANIFEST, undefined);
    expect(second).toBe('body "v1"'); // 古いまま(今回の不具合)
    expect(manifestHits()).toHaveLength(1); // 1回目だけ。2回目はサーバーに届かない
  });

  test("no-cache だと、max-age の間でも、毎回サーバーに確認する", async ({ page }) => {
    await page.goto(`${origin}/`);
    await get(page, MANIFEST, { cache: "no-cache" });
    etag = '"v2"';
    const second = await get(page, MANIFEST, { cache: "no-cache" });
    expect(second).toBe('body "v2"'); // 新しい中身
    expect(manifestHits()).toHaveLength(2); // 2回ともサーバーに届いた
  });

  test("変更がなければ 304(条件付きリクエスト)で、本体は転送されない", async ({ page }) => {
    await page.goto(`${origin}/`);
    await get(page, MANIFEST, { cache: "no-cache" });
    const second = await get(page, MANIFEST, { cache: "no-cache" });
    expect(second).toBe('body "v1"');
    expect(manifestHits()).toHaveLength(2);
    expect(manifestHits()[0]?.conditional).toBe(false); // 1回目は無条件
    expect(manifestHits()[1]?.conditional).toBe(true); // 2回目は If-None-Match つき(= 304 で済む)
  });
});
