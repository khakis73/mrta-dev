import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

// Python が書いた golden file(手作りシナリオ greedy-trap を2つのソルバで解いたもの)を読ませる。
function golden(name: string): string {
  return readFileSync(
    fileURLToPath(new URL(`../../tests/golden/${name}.jsonl`, import.meta.url)),
    "utf-8",
  );
}
const GREEDY = golden("greedy-trap-greedy");
const HUNGARIAN = golden("greedy-trap-hungarian");
// 同じ動的シナリオ(到着 t0=4、t1=8、t2=2)を、静的ソルバとローリングホライズンで解いたもの。
const DYNAMIC_STATIC = golden("dynamic-greedy");
const DYNAMIC_ROLLING = golden("dynamic-rolling-greedy");

const MANIFEST = JSON.stringify({
  manifest_version: 1,
  examples: [
    { id: "greedy-trap", title: "greedy-trap", logs: ["greedy-trap-greedy.jsonl", "greedy-trap-hungarian.jsonl"] },
  ],
});

async function serve(page: Page, files: Record<string, string>): Promise<void> {
  for (const [name, body] of Object.entries(files)) {
    await page.route(`**/data/${name}`, (route) =>
      route.fulfill({ body, contentType: "text/plain; charset=utf-8" }),
    );
  }
}

async function openCompare(page: Page): Promise<void> {
  await serve(page, { "a.jsonl": GREEDY, "b.jsonl": HUNGARIAN });
  await page.goto("/?log=data/a.jsonl&log=data/b.jsonl");
}

async function seek(page: Page, t: number): Promise<void> {
  await page.locator("#time").evaluate((el, value) => {
    (el as HTMLInputElement).value = String(value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, t);
}

const robot = (page: Page, side: "a" | "b", id: string) =>
  page.locator(`#board-${side} [data-robot="${id}"]`);

test.describe("2画面比較: 動的な到着", () => {
  async function openDynamic(page: Page): Promise<void> {
    await serve(page, { "a.jsonl": DYNAMIC_STATIC, "b.jsonl": DYNAMIC_ROLLING });
    await page.goto("/?log=data/a.jsonl&log=data/b.jsonl");
  }
  const unreleased = (page: Page, side: "a" | "b") =>
    page.locator(`#board-${side} [data-status="unreleased"]`);
  const status = (page: Page, side: "a" | "b", id: string) =>
    page.locator(`#board-${side} [data-task="${id}"]`);

  test("同じシナリオなので、到着前のタスクは両画面で同じ(1つの時刻で同期する)", async ({ page }) => {
    await openDynamic(page);
    await expect(page.locator('[data-panel="a"] h2')).toHaveText("A: greedy");
    await expect(page.locator('[data-panel="b"] h2')).toHaveText("B: rolling-greedy");
    for (const [t, expected] of [[0, 3], [3, 2], [5, 1], [8, 0]] as const) {
      await seek(page, t);
      await expect(unreleased(page, "a")).toHaveCount(expected);
      await expect(unreleased(page, "b")).toHaveCount(expected);
    }
  });

  test("凡例は、画面ごとに1つずつ(盤面の直下)", async ({ page }) => {
    await openDynamic(page);
    await expect(page.locator('[data-legend="arrival"]')).toHaveCount(2);
    await expect(page.locator('#board-a ~ [data-legend="arrival"]')).toHaveCount(1);
    await expect(page.locator('#board-b ~ [data-legend="arrival"]')).toHaveCount(1);
  });

  test("到着後の扱いはソルバで違う: ローリングは到着済みの t2 を先に取る", async ({ page }) => {
    await openDynamic(page);
    // t=5: 静的(A)は t0 の作業中で t2 は未着手のまま。ローリング(B)は t2 の作業中(t2 は 2 から出発、作業 [4,9])。
    await seek(page, 5);
    await expect(status(page, "a", "t2")).toHaveAttribute("data-status", "pending");
    await expect(status(page, "a", "t0")).toHaveAttribute("data-status", "serving");
    await expect(status(page, "b", "t2")).toHaveAttribute("data-status", "serving");
    await expect(status(page, "b", "t0")).toHaveAttribute("data-status", "pending");
  });
});

test.describe("2画面比較", () => {
  test("左右にソルバ名と指標の比較(手計算した値)が表示される", async ({ page }) => {
    await openCompare(page);
    await expect(page.locator('[data-panel="a"] h2')).toHaveText("A: greedy");
    await expect(page.locator('[data-panel="b"] h2')).toHaveText("B: hungarian");
    await expect(page.locator("#board-a")).toBeVisible();
    await expect(page.locator("#board-b")).toBeVisible();

    const row = (name: string) => page.locator(`#comparison tr[data-metric="${name}"]`);
    await expect(row("makespan").locator('[data-cell="a"]')).toContainText("11 ティック");
    await expect(row("makespan").locator('[data-cell="b"]')).toContainText("6 ティック");
    await expect(row("makespan").locator('[data-cell="diff"]')).toHaveText("-5");
    await expect(row("total_distance").locator('[data-cell="diff"]')).toHaveText("-1");
    await expect(row("utilization").locator('[data-cell="a"]')).toContainText("50.0%");
    await expect(row("utilization").locator('[data-cell="b"]')).toContainText("83.3%");

    // 優劣の印は B 側(小さいほう・大きいほう)にだけ付く。同値でなければ必ずどちらかに付く。
    await expect(page.locator('#comparison [data-better="true"]')).toHaveCount(3);
    await expect(page.locator('#comparison [data-cell="b"][data-better="true"]')).toHaveCount(3);
    await expect(page.locator(".note")).toContainText("1シナリオの結果");
  });

  test("時刻は共通で、短い完了時間のほうは完了した状態で止まる", async ({ page }) => {
    await openCompare(page);
    await expect(page.locator("#clock")).toHaveText("0.00 / 11"); // 範囲は大きいほうの完了時間

    // t=3: 貪欲法の r0 は t0 (3,0) に着いて作業中。ハンガリアン法の r0 は t1 (0,3) に着いて作業中。
    await seek(page, 3);
    await expect(robot(page, "a", "r0")).toHaveAttribute("transform", "translate(3.5 0.5)");
    await expect(robot(page, "b", "r0")).toHaveAttribute("transform", "translate(0.5 3.5)");
    await expect(page.locator('[data-panel="a"] #robots-a tr[data-robot="r0"] [data-field="task"]')).toHaveText("t0");
    await expect(page.locator('[data-panel="b"] #robots-b tr[data-robot="r0"] [data-field="task"]')).toHaveText("t1");

    // t=11: ハンガリアン法(完了時間 6)は、とっくに完了している。貪欲法がちょうど完了する。
    await seek(page, 11);
    await expect(page.locator('#board-a [data-status="done"]')).toHaveCount(2);
    await expect(page.locator('#board-b [data-status="done"]')).toHaveCount(2);
    await expect(robot(page, "b", "r1")).toHaveAttribute("data-activity", "done");
    await expect(page.locator("#play")).toHaveText("もう一度");
  });

  test("1つの再生操作で、両方が進む", async ({ page }) => {
    await openCompare(page);
    await page.locator("#speed").selectOption("8");
    await page.locator("#play").click();
    await expect(page.locator("#clock")).toHaveText("11.00 / 11");
    await expect(page.locator('#board-a [data-status="done"]')).toHaveCount(2);
    await expect(page.locator('#board-b [data-status="done"]')).toHaveCount(2);
  });

  test("シナリオが一致しないログは、比較せず原因を出す", async ({ page }) => {
    await serve(page, { "a.jsonl": GREEDY, "b.jsonl": HUNGARIAN.replace('"seed":0', '"seed":7') });
    await page.goto("/?log=data/a.jsonl&log=data/b.jsonl");
    await expect(page.getByRole("alert")).toContainText("シナリオが一致しない: seed が違う");
    await expect(page.locator("#board-a")).toHaveCount(0);
  });

  test("3つ以上のログは受け付けない", async ({ page }) => {
    await page.goto("/?log=data/a.jsonl&log=data/b.jsonl&log=data/c.jsonl");
    await expect(page.getByRole("alert")).toContainText("2つまで");
  });

  test("片方が不正なら、どのファイルかを示す", async ({ page }) => {
    await serve(page, { "a.jsonl": GREEDY, "b.jsonl": HUNGARIAN.slice(0, -1) });
    await page.goto("/?log=data/a.jsonl&log=data/b.jsonl");
    await expect(page.getByRole("alert")).toContainText("ログが不正(data/b.jsonl)");
  });

  test("1つだけ指定したときは、従来どおりの1画面", async ({ page }) => {
    await serve(page, { "a.jsonl": GREEDY });
    await page.goto("/?log=data/a.jsonl");
    await expect(page.locator("#board")).toBeVisible();
    await expect(page.locator("#comparison")).toHaveCount(0);
  });
});

test.describe("比較の例(マニフェスト)", () => {
  test("リンクから比較画面を開ける", async ({ page }) => {
    await serve(page, {
      "manifest.json": MANIFEST,
      "greedy-trap-greedy.jsonl": GREEDY,
      "greedy-trap-hungarian.jsonl": HUNGARIAN,
      "demo.jsonl": GREEDY,
    });
    await page.goto("/");
    await page.locator('#examples a:has-text("greedy-trap")').click();
    await expect(page).toHaveURL(/log=data%2Fgreedy-trap-greedy\.jsonl&log=data%2Fgreedy-trap-hungarian\.jsonl/);
    await expect(page.locator("#comparison")).toBeVisible();
  });

  test("マニフェストが無くても、閲覧はできる(リンクが出ないだけ)", async ({ page }) => {
    await serve(page, { "demo.jsonl": GREEDY });
    await page.route("**/data/manifest.json", (route) => route.fulfill({ status: 404 }));
    await page.goto("/");
    await expect(page.locator("#board")).toBeVisible();
    await expect(page.locator("#examples")).toHaveCount(0);
  });
});

test.describe("比較の例: 組を選ぶ(マニフェスト v2。ADR-0013)", () => {
  // 動的な例: 静的の貪欲法・CP-SAT(の代わりに同じログ)・ローリングの3本。UI の検証なので、同じシナリオなら足りる。
  const V2 = JSON.stringify({
    manifest_version: 2,
    examples: [
      {
        id: "dyn",
        title: "dyn",
        dynamic: true,
        default: { a: "greedy", b: "rolling-greedy" },
        logs: [
          { file: "dyn-cpsat.jsonl", solver: "cpsat" },
          { file: "dyn-greedy.jsonl", solver: "greedy" },
          { file: "dyn-rolling-greedy.jsonl", solver: "rolling-greedy" },
        ],
      },
      // v1 と同じ2本の例は、従来どおり1本のリンクのまま
      {
        id: "greedy-trap",
        title: "greedy-trap",
        logs: [
          { file: "greedy-trap-greedy.jsonl", solver: "greedy" },
          { file: "greedy-trap-hungarian.jsonl", solver: "hungarian" },
        ],
      },
    ],
  });

  async function openV2(page: Page): Promise<void> {
    await serve(page, {
      "manifest.json": V2,
      "demo.jsonl": GREEDY,
      "dyn-cpsat.jsonl": DYNAMIC_STATIC,
      "dyn-greedy.jsonl": DYNAMIC_STATIC,
      "dyn-rolling-greedy.jsonl": DYNAMIC_ROLLING,
      "greedy-trap-greedy.jsonl": GREEDY,
      "greedy-trap-hungarian.jsonl": HUNGARIAN,
    });
    await page.goto("/");
  }
  const pick = (page: Page, side: "a" | "b") => page.locator(`#examples [data-example="dyn"] [data-pick="${side}"]`);
  const link = (page: Page) => page.locator('#examples [data-example="dyn"] [data-compare]');

  test("3本以上の例は選択、2本の例は従来どおりリンク1本", async ({ page }) => {
    await openV2(page);
    await expect(page.locator('#examples [data-example="dyn"] select')).toHaveCount(2);
    await expect(page.locator('#examples [data-example="greedy-trap"] select')).toHaveCount(0);
    await expect(page.locator('#examples [data-example="greedy-trap"] a')).toHaveAttribute(
      "href",
      "?log=data%2Fgreedy-trap-greedy.jsonl&log=data%2Fgreedy-trap-hungarian.jsonl",
    );
  });

  test("既定の組が選ばれていて、選択肢に種別が添えられる", async ({ page }) => {
    await openV2(page);
    await expect(pick(page, "a")).toHaveValue("greedy");
    await expect(pick(page, "b")).toHaveValue("rolling-greedy");
    await expect(pick(page, "a").locator("option")).toHaveText([
      "cpsat(静的・到着を無視)",
      "greedy(静的・到着を無視)",
      "rolling-greedy(ローリング)",
    ]);
    await expect(link(page)).toHaveAttribute(
      "href",
      "?log=data%2Fdyn-greedy.jsonl&log=data%2Fdyn-rolling-greedy.jsonl",
    );
  });

  test("選択を変えると、リンクが変わり、開くと A・B の順で比較される", async ({ page }) => {
    await openV2(page);
    await pick(page, "a").selectOption("rolling-greedy");
    await pick(page, "b").selectOption("cpsat");
    await expect(link(page)).toHaveAttribute(
      "href",
      "?log=data%2Fdyn-rolling-greedy.jsonl&log=data%2Fdyn-cpsat.jsonl",
    );
    await link(page).click();
    await expect(page.locator("#comparison")).toBeVisible();
    await expect(page.locator('[data-panel="a"] h2')).toHaveText("A: rolling-greedy");
    await expect(page.locator('[data-panel="b"] h2')).toHaveText("B: greedy"); // dyn-cpsat は貪欲法のログを流用
  });

  test("同じログを選ぶと、リンクが消えて理由が出る。直すと戻る", async ({ page }) => {
    await openV2(page);
    await pick(page, "b").selectOption("greedy");
    await expect(link(page)).toBeHidden();
    await expect(page.locator('#examples [data-example="dyn"] [data-same-log]')).toHaveText("A と B に同じものは選べない");
    await pick(page, "b").selectOption("cpsat");
    await expect(link(page)).toBeVisible();
    await expect(page.locator('#examples [data-example="dyn"] [data-same-log]')).toBeHidden();
  });

  test("注記: 見せるための例(全体)と、動的な例の静的ソルバ(動的な例だけ)", async ({ page }) => {
    await openV2(page);
    await expect(page.locator('#examples [data-note="examples"]')).toContainText("代表的な結果ではない");
    await expect(page.locator('#examples [data-example="dyn"] [data-note="dynamic"]')).toContainText("未来のタスクを知っている");
    await expect(page.locator('#examples [data-example="greedy-trap"] [data-note="dynamic"]')).toHaveCount(0);
  });

  test("スマホの幅でも、横スクロールが出ない", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await openV2(page);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

test.describe("スマホの幅", () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test("横スクロールが出ず、盤面は縦に並び、操作部は画面内に残る", async ({ page }) => {
    await openCompare(page);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    const a = await page.locator("#board-a").boundingBox();
    const b = await page.locator("#board-b").boundingBox();
    expect(a?.width).toBeLessThanOrEqual(375);
    expect(b!.y).toBeGreaterThan(a!.y + a!.height - 1); // 縦に積まれる

    await page.locator("#comparison").scrollIntoViewIfNeeded();
    await expect(page.locator("#play")).toBeInViewport(); // 下に固定された操作部
  });
});

test.describe("盤面のスクリーンショット", () => {
  // t=3: 同じ時刻で、貪欲法とハンガリアン法のロボットの位置が違うことを固定する。
  for (const side of ["a", "b"] as const) {
    test(`greedy-trap の t=3(${side})`, async ({ page }) => {
      await openCompare(page);
      await seek(page, 3);
      await expect(page.locator(`#board-${side}`)).toHaveScreenshot(`greedy-trap-t3-${side}.png`);
    });
  }
});
