import { defineConfig, devices } from "@playwright/test";

// スクリーンショットは盤面(SVG)だけを撮る。テキストを含まないので、OS が違っても安定する。
// 保存先に OS 名を含めず、同じ基準画像を共有する。アンチエイリアスの差は、画素ごとの許容(threshold)と、
// 差分の画素数の上限(maxDiffPixels)で吸収する。割合で指定しない: 盤面は大半が白なので、
// 割合の許容は、ロボット1台の位置や形の違い(全体の1%前後)を飲み込んでしまう。
export default defineConfig({
  testDir: "e2e",
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  expect: { toHaveScreenshot: { maxDiffPixels: 200 } },
  reporter: process.env["CI"] ? [["github"], ["list"]] : "list",
  use: { baseURL: "http://localhost:4173", trace: "off", screenshot: "off" },
  webServer: {
    command: "npm run build && npm run preview -- --port 4173 --strictPort",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env["CI"],
    timeout: 60_000,
  },
  projects: [
    {
      name: "chromium",
      // channel: "chromium" は、フルビルドの Chromium(新 headless)を使う。既定の headless shell は、
      // この環境で requestAnimationFrame が発火せず、click の安定性チェックと再生が止まるため。
      use: { ...devices["Desktop Chrome"], channel: "chromium", viewport: { width: 800, height: 900 } },
    },
  ],
});
