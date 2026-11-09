import { describe, expect, it } from "vitest";
import { compareHref, parseManifest } from "./manifest";

const valid = {
  manifest_version: 1,
  examples: [{ id: "greedy-trap", title: "greedy-trap", logs: ["a.jsonl", "b.jsonl"] }],
};

describe("parseManifest", () => {
  it("正しいマニフェストを読む", () => {
    expect(parseManifest(JSON.stringify(valid))).toEqual([
      { id: "greedy-trap", title: "greedy-trap", logs: ["a.jsonl", "b.jsonl"] },
    ]);
  });

  it("未知のフィールドは無視する(後方互換な追加)", () => {
    const extended = { ...valid, extra: 1, examples: [{ ...valid.examples[0], note: "x" }] };
    expect(parseManifest(JSON.stringify(extended))).toHaveLength(1);
  });

  it.each([
    ["JSON ではない", "not json"],
    ["オブジェクトではない", "[]"],
    ["未対応の版", JSON.stringify({ ...valid, manifest_version: 2 })],
    ["版がない", JSON.stringify({ examples: valid.examples })],
    ["examples が配列ではない", JSON.stringify({ manifest_version: 1, examples: {} })],
  ])("読めないときは空(閲覧は妨げない): %s", (_label, text) => {
    expect(parseManifest(text)).toEqual([]);
  });

  it("不正な例だけを捨てる", () => {
    const mixed = {
      manifest_version: 1,
      examples: [
        { id: "ok", title: "ok", logs: ["a.jsonl", "b.jsonl"] },
        { id: "one", title: "one", logs: ["a.jsonl"] },
        { id: "num", title: 1, logs: ["a.jsonl", "b.jsonl"] },
        "string",
      ],
    };
    expect(parseManifest(JSON.stringify(mixed)).map((e) => e.id)).toEqual(["ok"]);
  });

  it.each(["https://example.com/a.jsonl", "//example.com/a.jsonl", "/etc/passwd", "../a.jsonl", ""])(
    "相対パスでないログは受け付けない: %j",
    (path) => {
      const bad = { ...valid, examples: [{ id: "x", title: "x", logs: [path, "b.jsonl"] }] };
      expect(parseManifest(JSON.stringify(bad))).toEqual([]);
    },
  );
});

describe("compareHref", () => {
  it("log を2回指定する URL にする", () => {
    const [example] = parseManifest(JSON.stringify(valid));
    expect(compareHref(example!)).toBe("?log=data%2Fa.jsonl&log=data%2Fb.jsonl");
  });
});
