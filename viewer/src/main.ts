import { mountApp } from "./app";
import { parseLog } from "./log";
import type { Log } from "./log";
import { MANIFEST_PATH, parseManifest } from "./manifest";
import type { Example } from "./manifest";
import "./style.css";

const DEFAULT_LOG = "data/demo.jsonl";

function showError(root: HTMLElement, message: string): void {
  const p = document.createElement("p");
  p.setAttribute("role", "alert");
  p.className = "error";
  p.textContent = message;
  const h1 = document.createElement("h1");
  h1.textContent = "mrta viewer";
  const main = document.createElement("main");
  main.className = "app";
  main.append(h1, p);
  root.replaceChildren(main);
}

async function loadText(path: string): Promise<Response> {
  const url = new URL(path, document.baseURI);
  // 公開サイトと同じオリジンのログだけを読む(ADR-0004: ログは Pages のビルドで生成して同梱する)。
  if (url.origin !== location.origin) {
    throw new Error("同じオリジンのログだけを読み込める");
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`ログを取得できなかった(HTTP ${response.status}): ${url.pathname}`);
  }
  return response;
}

async function loadLog(path: string): Promise<Log> {
  const text = await (await loadText(path)).text();
  try {
    return parseLog(text);
  } catch (e) {
    // どのファイルが不正かが分かるようにする
    throw new Error(`ログが不正(${path}): ${e instanceof Error ? e.message : String(e)}`);
  }
}

/** 比較の例の一覧。補助なので、無い・読めない・未対応なら空(閲覧は妨げない)。 */
async function loadExamples(): Promise<Example[]> {
  try {
    return parseManifest(await (await loadText(MANIFEST_PATH)).text());
  } catch {
    return [];
  }
}

async function main(): Promise<void> {
  const root = document.querySelector<HTMLElement>("#app");
  if (root === null) {
    throw new Error("#app が見つからない");
  }
  try {
    const params = new URLSearchParams(location.search).getAll("log");
    const paths = params.length === 0 ? [DEFAULT_LOG] : params;
    if (paths.length > 2) {
      throw new Error(`ログは2つまで指定できる(指定: ${paths.length})`);
    }
    const [logs, examples] = await Promise.all([Promise.all(paths.map(loadLog)), loadExamples()]);
    mountApp(root, logs, { examples });
  } catch (e) {
    showError(root, e instanceof Error ? e.message : String(e));
  }
}

void main();
