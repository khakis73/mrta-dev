import { defineConfig } from "vite";

// GitHub Pages のサブパス配信でも動くよう、アセットは相対パスで参照する。
export default defineConfig({
  base: "./",
});
