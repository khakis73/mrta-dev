// 公開ログの一覧(manifest.json、ADR-0006)。リンクは補助なので、読めなければ「なし」として扱う。

export const SUPPORTED_MANIFEST_VERSION = 1;
/** manifest.json の場所。ログのパスはこのディレクトリからの相対(ADR-0006)。 */
export const MANIFEST_PATH = "data/manifest.json";
export const MANIFEST_DIR = "data/";

export interface Example {
  id: string;
  title: string;
  /** manifest.json と同じディレクトリからの相対パス */
  logs: string[];
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isRelativePath(v: unknown): v is string {
  // スキーム(https: など)・絶対パス・親ディレクトリへの参照は受け付けない。
  return typeof v === "string" && v !== "" && !/^([a-z][a-z0-9+.-]*:|\/|\\)/i.test(v) && !v.includes("..");
}

/** 不正・未対応の版なら空配列。 */
export function parseManifest(text: string): Example[] {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return [];
  }
  if (!isRecord(data) || data["manifest_version"] !== SUPPORTED_MANIFEST_VERSION) {
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
    const { id, title, logs } = item;
    if (
      typeof id === "string" &&
      typeof title === "string" &&
      Array.isArray(logs) &&
      logs.length === 2 &&
      logs.every(isRelativePath)
    ) {
      examples.push({ id, title, logs: logs as string[] });
    }
  }
  return examples;
}

/** 比較画面へのリンク(`?log=…&log=…`)。 */
export function compareHref(example: Example): string {
  const params = new URLSearchParams();
  for (const log of example.logs) {
    params.append("log", `${MANIFEST_DIR}${log}`);
  }
  return `?${params.toString()}`;
}
