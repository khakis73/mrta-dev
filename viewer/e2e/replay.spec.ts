import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

// Python が書いた golden file を、そのままビューアに読ませる(ADR-0004 の読む側の契約)。
const TINY = readFileSync(
  fileURLToPath(new URL("../../tests/golden/tiny-greedy.jsonl", import.meta.url)),
  "utf-8",
);
// 動的な到着(ADR-0011): t0 は到着 4、t1 は到着 8、t2 は到着 2。
const DYNAMIC = readFileSync(
  fileURLToPath(new URL("../../tests/golden/dynamic-greedy.jsonl", import.meta.url)),
  "utf-8",
);

async function open(page: Page, body: string = TINY): Promise<void> {
  await page.route("**/data/test.jsonl", (route) =>
    route.fulfill({ body, contentType: "text/plain; charset=utf-8" }),
  );
  await page.goto("/?log=data/test.jsonl");
}

/** スライダーを動かす(range 入力は fill できないので、値を入れて input イベントを送る) */
async function seek(page: Page, t: number): Promise<void> {
  await page.locator("#time").evaluate((el, value) => {
    (el as HTMLInputElement).value = String(value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, t);
}

const cell = (page: Page, robot: string, field: string) =>
  page.locator(`#robots tr[data-robot="${robot}"] [data-field="${field}"]`);

test.describe("表示", () => {
  test("ログの内容(手計算した値)が表示される", async ({ page }) => {
    await open(page);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("mrta viewer");
    await expect(page.locator("#summary")).toHaveText(
      "ソルバ greedy ・ シード 0 ・ 格子 10×10 ・ ロボット 2 台 ・ タスク 3 件",
    );
    await expect(page.locator('#metrics [data-metric="makespan"]')).toHaveText("13 ティック");
    await expect(page.locator('#metrics [data-metric="total_distance"]')).toHaveText("22");
    await expect(page.locator('#metrics [data-metric="utilization"]')).toHaveText("96.2%"); // 25/26
    await expect(cell(page, "r0", "finish")).toHaveText("13");
    await expect(cell(page, "r1", "finish")).toHaveText("12");
    await expect(page.locator("#clock")).toHaveText("0.00 / 13");
  });

  test("時刻に応じて、ロボットの状態・位置とタスクの状態が変わる", async ({ page }) => {
    await open(page);
    const robot = (id: string) => page.locator(`#board [data-robot="${id}"]`);
    const task = (id: string) => page.locator(`#board [data-task="${id}"]`);

    // t=0: r0 は (6,6) から t0 へ向かう。セルの中心に描くので +0.5
    await expect(cell(page, "r0", "activity")).toHaveText("移動中");
    await expect(cell(page, "r0", "task")).toHaveText("t0");
    await expect(robot("r0")).toHaveAttribute("transform", "translate(6.5 6.5)");
    await expect(task("t0")).toHaveAttribute("data-status", "pending");

    // t=1: r0 は t0 (8,7) に着いて作業を始める
    await seek(page, 1);
    await expect(cell(page, "r0", "activity")).toHaveText("作業中");
    await expect(robot("r0")).toHaveAttribute("transform", "translate(8.5 7.5)");
    await expect(robot("r0")).toHaveAttribute("data-activity", "servicing");
    await expect(task("t0")).toHaveAttribute("data-status", "serving");

    // t=6.5: r0 は (8,7)→(4,2) の途中。x を先に進めるので (4, 6.5)
    await seek(page, 6.5);
    await expect(cell(page, "r0", "task")).toHaveText("t2");
    await expect(robot("r0")).toHaveAttribute("transform", "translate(4.5 7)");
    await expect(task("t0")).toHaveAttribute("data-status", "done");
    await expect(task("t2")).toHaveAttribute("data-status", "pending");
    await expect(page.locator("#clock")).toHaveText("6.50 / 13");

    // t=13: 全員が完了
    await seek(page, 13);
    await expect(cell(page, "r0", "activity")).toHaveText("完了");
    await expect(cell(page, "r1", "activity")).toHaveText("完了");
    await expect(page.locator('#board [data-status="done"]')).toHaveCount(3);
    await expect(page.locator("#play")).toHaveText("もう一度");
  });

  test("到着前のタスクは unreleased(薄く表示)で、到着時刻から pending になる", async ({ page }) => {
    await open(page, DYNAMIC);
    const task = (id: string) => page.locator(`#board [data-task="${id}"]`);

    // t=0: どのタスクもまだ現れていない
    await expect(page.locator('#board [data-status="unreleased"]')).toHaveCount(3);
    // t=3: t2 (到着 2) だけが現れた。t0 (到着 4)、t1 (到着 8) はまだ
    await seek(page, 3);
    await expect(task("t2")).toHaveAttribute("data-status", "pending");
    await expect(task("t0")).toHaveAttribute("data-status", "unreleased");
    await expect(task("t1")).toHaveAttribute("data-status", "unreleased");
    // t=4: t0 が現れ、ロボットが作業を始める(移動 [4,5]、作業 [5,9])
    await seek(page, 4);
    await expect(task("t0")).toHaveAttribute("data-status", "pending");
    // t=8: t1 が現れる
    await seek(page, 8);
    await expect(task("t1")).toHaveAttribute("data-status", "pending");
    await expect(page.locator('#board [data-status="unreleased"]')).toHaveCount(0);
    // 終端: 全て完了
    await seek(page, 20);
    await expect(page.locator('#board [data-status="done"]')).toHaveCount(3);
  });

  test("動的なログにだけ、到着前の凡例が出る(静的には出ない)", async ({ page }) => {
    await open(page, DYNAMIC);
    await expect(page.locator('[data-legend="arrival"]')).toHaveText(
      "薄い点線の丸: まだ現れていないタスク(到着前)",
    );
    await open(page);
    await expect(page.locator('[data-legend="arrival"]')).toHaveCount(0);
  });

  test("静的なログでは、unreleased は現れない", async ({ page }) => {
    await open(page);
    await expect(page.locator('#board [data-status="unreleased"]')).toHaveCount(0);
  });

  test("ログの文字列は HTML として解釈されない", async ({ page }) => {
    const evil = "<b>r0</b>";
    await open(page, TINY.replaceAll('"r0"', JSON.stringify(evil)));
    await expect(page.locator("#robots")).toContainText(evil); // 文字としてそのまま表示される
    await expect(page.locator("#robots b")).toHaveCount(0); // 要素にはならない
    await expect(page.locator("#board b")).toHaveCount(0);
  });
});

test.describe("再生", () => {
  test("再生すると進み、終端で止まり、「もう一度」で先頭から再生する", async ({ page }) => {
    await open(page);
    await page.locator("#speed").selectOption("8");
    await page.locator("#play").click();
    await expect(page.locator("#play")).toHaveText("一時停止");
    await expect(page.locator("#clock")).toHaveText("13.00 / 13"); // 8x = 16 ティック/秒
    await expect(page.locator("#play")).toHaveText("もう一度");

    await page.locator("#play").click();
    await expect(page.locator("#play")).toHaveText("一時停止");
    await expect(page.locator("#clock")).not.toHaveText("13.00 / 13");
  });

  test("一時停止すると、時刻が進まない", async ({ page }) => {
    await open(page);
    await page.locator("#speed").selectOption("8");
    await page.locator("#play").click();
    await expect.poll(async () => Number(await page.locator("#time").inputValue())).toBeGreaterThan(0);
    await page.locator("#play").click();
    await expect(page.locator("#play")).toHaveText("再生");
    const stopped = await page.locator("#time").inputValue();
    await page.waitForTimeout(300);
    expect(await page.locator("#time").inputValue()).toBe(stopped);
  });
});

test.describe("読み込みの失敗は、画面に原因を出す", () => {
  test("途中で切れたログ", async ({ page }) => {
    await open(page, TINY.slice(0, -1));
    await expect(page.getByRole("alert")).toContainText("末尾が改行");
    await expect(page.locator("#board")).toHaveCount(0);
  });

  test("未対応のスキーマ版", async ({ page }) => {
    await open(page, TINY.replace('"schema_version":1', '"schema_version":2'));
    await expect(page.getByRole("alert")).toContainText("未対応のスキーマ版: 2");
  });

  test("存在しないログ", async ({ page }) => {
    await page.goto("/?log=data/missing.jsonl");
    await expect(page.getByRole("alert")).toContainText("HTTP 404");
  });

  test("別のオリジンのログは読まない", async ({ page }) => {
    await page.goto("/?log=https://example.com/log.jsonl");
    await expect(page.getByRole("alert")).toContainText("同じオリジン");
  });
});

test.describe("スマホの幅", () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test("横スクロールが出ず、盤面が画面に収まる", async ({ page }) => {
    await open(page);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    const box = await page.locator("#board").boundingBox();
    expect(box?.width).toBeLessThanOrEqual(375);
    expect(box?.x).toBeGreaterThanOrEqual(0);
  });
});

test.describe("盤面のスクリーンショット", () => {
  // 盤面(SVG)だけを撮る。時刻ごとの見た目の回帰を検出する。基準画像は e2e/__screenshots__。
  for (const t of [0, 1, 6.5, 13]) {
    test(`tiny-greedy の t=${t}`, async ({ page }) => {
      await open(page);
      await seek(page, t);
      await expect(page.locator("#board")).toHaveScreenshot(`tiny-greedy-t${t}.png`);
    });
  }

  // 到着前のタスクが薄く表示されること(ADR-0011)。状態が混在する時刻を撮る。
  for (const t of [0, 3, 6]) {
    test(`dynamic-greedy の t=${t}`, async ({ page }) => {
      await open(page, DYNAMIC);
      await seek(page, t);
      // 到着前の丸は細く薄い線で、既定の threshold(0.2)だと、透明度を変えても差に数えられず、
      // 見た目の回帰を検出できない(opacity 0.45 → 1 を試して確認した)。このケースだけ下げる。
      await expect(page.locator("#board")).toHaveScreenshot(`dynamic-greedy-t${t}.png`, {
        threshold: 0.1,
      });
    });
  }
});
