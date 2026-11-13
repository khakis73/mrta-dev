// 公開ログの一覧(manifest.json、ADR-0006・0013)。リンクは補助なので、読めなければ「なし」として扱う。
//
// v1: 例ごとに2本のログ(文字列の配列)。v2: 2本以上の `{file, solver}`(ADR-0013)。
// どちらも、読み込み後は同じ `Example` に揃える。表示側は版を気にしない。

/** 読める版。未対応の版は、リンクを出さない(ADR-0006)。 */
export const SUPPORTED_MANIFEST_VERSIONS = [1, 2] as const;
/** manifest.json の場所。ログのパスはこのディレクトリからの相対(ADR-0006)。 */
export const MANIFEST_PATH = "data/manifest.json";
export const MANIFEST_DIR = "data/";

export interface ExampleLog {
  /** manifest.json と同じディレクトリからの相対パス */
  file: string;
  /** ソルバ名(ログの solver.name と一致する。v1 はファイル名から導く) */
  solver: string;
}

export interface Example {
  id: string;
  title: string;
  logs: ExampleLog[];
  /** 動的なシナリオ(タスクが途中で現れる。ADR-0011)か。v1 は常に false */
  dynamic: boolean;
  /** 最初に選ぶ組(ソルバ名)。無い・不正なら、先頭の2本 */
  defaultPair: readonly [string, string] | null;
  /** この例が何を見せるか(任意。v2)。無い・文字列でない・空なら null。画面には文字列として出す */
  description: string | null;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isRelativePath(v: unknown): v is string {
  // スキーム(https: など)・絶対パス・親ディレクトリへの参照は受け付けない。
  return typeof v === "string" && v !== "" && !/^([a-z][a-z0-9+.-]*:|\/|\\)/i.test(v) && !v.includes("..");
}

/** v1 はソルバ名を持たない。`<id>-<solver>.jsonl` の命名(ADR-0006)から導き、導けなければファイル名。 */
function solverFromFile(id: string, file: string): string {
  const base = file.replace(/\.jsonl$/, "");
  return base.startsWith(`${id}-`) ? base.slice(id.length + 1) : base;
}

function parseLogs(version: number, id: string, logs: unknown): ExampleLog[] | null {
  if (!Array.isArray(logs)) {
    return null;
  }
  if (version === 1) {
    // v1: ちょうど2本の相対パス
    if (logs.length !== 2 || !logs.every(isRelativePath)) {
      return null;
    }
    return (logs as string[]).map((file) => ({ file, solver: solverFromFile(id, file) }));
  }
  // v2: 2本以上の {file, solver}。ソルバ名は重複しない(選択の鍵になる)。
  if (logs.length < 2) {
    return null;
  }
  const parsed: ExampleLog[] = [];
  for (const item of logs) {
    if (!isRecord(item) || !isRelativePath(item["file"]) || typeof item["solver"] !== "string" || item["solver"] === "") {
      return null;
    }
    parsed.push({ file: item["file"], solver: item["solver"] });
  }
  return new Set(parsed.map((l) => l.solver)).size === parsed.length ? parsed : null;
}

function parseDefault(raw: unknown, logs: ExampleLog[]): readonly [string, string] | null {
  if (!isRecord(raw)) {
    return null;
  }
  const { a, b } = raw;
  const names = new Set(logs.map((l) => l.solver));
  if (typeof a === "string" && typeof b === "string" && a !== b && names.has(a) && names.has(b)) {
    return [a, b];
  }
  return null;
}

function parseDescription(raw: unknown): string | null {
  return typeof raw === "string" && raw.trim() !== "" ? raw : null;
}

/** 不正・未対応の版なら空配列。不正な例だけを捨てる。 */
export function parseManifest(text: string): Example[] {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return [];
  }
  if (!isRecord(data)) {
    return [];
  }
  const version = data["manifest_version"];
  if (typeof version !== "number" || !(SUPPORTED_MANIFEST_VERSIONS as readonly number[]).includes(version)) {
    return [];
  }
  const raw = data["examples"];
  if (!Array.isArray(raw)) {
    return [];
  }
  const examples: Example[] = [];
  for (const item of raw) {
    if (!isRecord(item)) {
      continue;
    }
    const { id, title } = item;
    if (typeof id !== "string" || typeof title !== "string") {
      continue;
    }
    const logs = parseLogs(version, id, item["logs"]);
    if (logs === null) {
      continue;
    }
    examples.push({
      id,
      title,
      logs,
      dynamic: version >= 2 && item["dynamic"] === true,
      defaultPair: version >= 2 ? parseDefault(item["default"], logs) : null,
      description: version >= 2 ? parseDescription(item["description"]) : null,
    });
  }
  return examples;
}

/** 最初に選ぶ A・B のソルバ名。既定が無ければ、先頭の2本。 */
export function initialPair(example: Example): readonly [string, string] {
  if (example.defaultPair !== null) {
    return example.defaultPair;
  }
  const [first, second] = example.logs;
  return [first!.solver, second!.solver];
}

/** 選択肢の表示名。動的な例では、静的ソルバが「到着を無視している」ことを添える(ADR-0011・0013)。 */
export function optionLabel(example: Example, solver: string): string {
  if (example.dynamic && !solver.startsWith("rolling-")) {
    return `${solver}(静的・到着を無視)`;
  }
  return example.dynamic ? `${solver}(ローリング)` : solver;
}

/** 比較画面へのリンク(`?log=…&log=…`)。A と B のソルバ名で選ぶ。同じ・存在しない名前なら null。 */
export function compareHref(example: Example, solverA?: string, solverB?: string): string | null {
  const [defaultA, defaultB] = initialPair(example);
  const a = solverA ?? defaultA;
  const b = solverB ?? defaultB;
  const logA = example.logs.find((l) => l.solver === a);
  const logB = example.logs.find((l) => l.solver === b);
  if (logA === undefined || logB === undefined || logA === logB) {
    return null;
  }
  const params = new URLSearchParams();
  for (const log of [logA, logB]) {
    params.append("log", `${MANIFEST_DIR}${log.file}`);
  }
  return `?${params.toString()}`;
}
