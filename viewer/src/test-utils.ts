// テスト用: Python 側と共有する golden file(tests/golden)を読む(ADR-0004)。
// 読む側の契約テスト: Python が書いたログを、ビューアが読めること。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export function golden(name: string): string {
  const url = new URL(`../../tests/golden/${name}.jsonl`, import.meta.url);
  return readFileSync(fileURLToPath(url), "utf-8");
}

export function lines(text: string): string[] {
  return text.slice(0, -1).split("\n");
}

export function joined(ls: string[]): string {
  return `${ls.join("\n")}\n`;
}
