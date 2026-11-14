import { mountApp } from "./app";
import { loadText } from "./load";
import { parseLog } from "./log";
import type { Log } from "./log";
import { MANIFEST_PATH, parseManifest, parseSolverSummaries } from "./manifest";
import type { Example, SolverSummaries } from "./manifest";
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

const load = (path: string): Promise<Response> => loadText(path, document.baseURI, location.origin);

async function loadLog(path: string): Promise<Log> {
  const text = await (await load(path)).text();
  try {
    return parseLog(text);
  } catch (e) {
    // どのファイルが不正かが分かるようにする
    throw new Error(`ログが不正(${path}): ${e instanceof Error ? e.message : String(e)}`);
  }
}

interface Manifest {
  examples: Example[];
  solverSummaries: SolverSummaries;
}

/** 比較の例の一覧とソルバの説明。補助なので、無い・読めない・未対応なら空(閲覧は妨げない)。 */
async function loadManifest(): Promise<Manifest> {
  try {
    const text = await (await load(MANIFEST_PATH)).text();
    return { examples: parseManifest(text), solverSummaries: parseSolverSummaries(text) };
  } catch {
    return { examples: [], solverSummaries: {} };
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
    const [logs, { examples, solverSummaries }] = await Promise.all([
      Promise.all(paths.map(loadLog)),
      loadManifest(),
    ]);
    mountApp(root, logs, { examples, solverSummaries });
  } catch (e) {
    showError(root, e instanceof Error ? e.message : String(e));
  }
}

void main();
