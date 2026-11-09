import { mountApp } from "./app";
import { parseLog } from "./log";
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

async function loadLog(param: string | null): Promise<string> {
  const url = new URL(param ?? DEFAULT_LOG, document.baseURI);
  // 公開サイトと同じオリジンのログだけを読む(ADR-0004: ログは Pages のビルドで生成して同梱する)。
  if (url.origin !== location.origin) {
    throw new Error("同じオリジンのログだけを読み込める");
  }
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`ログを取得できなかった(HTTP ${response.status}): ${url.pathname}`);
  }
  return response.text();
}

async function main(): Promise<void> {
  const root = document.querySelector<HTMLElement>("#app");
  if (root === null) {
    throw new Error("#app が見つからない");
  }
  try {
    const param = new URLSearchParams(location.search).get("log");
    const text = await loadLog(param);
    let log;
    try {
      log = parseLog(text);
    } catch (e) {
      // どのファイルが不正かが分かるようにする
      throw new Error(`ログが不正(${param ?? DEFAULT_LOG}): ${e instanceof Error ? e.message : String(e)}`);
    }
    mountApp(root, log);
  } catch (e) {
    showError(root, e instanceof Error ? e.message : String(e));
  }
}

void main();
