import { defineConfig } from "vitest/config";

// GitHub Pages のサブパス配信でも動くよう、アセットは相対パスで参照する。
export default defineConfig({
  base: "./",
  // 存在しないパスに index.html を返さない(SPA フォールバックなし)。GitHub Pages と同じく 404 にする。
  appType: "mpa",
  test: {
    // Playwright の e2e/*.spec.ts は vitest の対象にしない。
    include: ["src/**/*.test.ts"],
  },
});
