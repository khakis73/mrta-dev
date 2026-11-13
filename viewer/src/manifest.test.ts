import { describe, expect, it } from "vitest";
import { compareHref, initialPair, optionLabel, parseManifest } from "./manifest";

// v1: 例ごとにちょうど2本(文字列)。
const v1 = {
  manifest_version: 1,
  examples: [{ id: "greedy-trap", title: "greedy-trap", logs: ["greedy-trap-greedy.jsonl", "greedy-trap-hungarian.jsonl"] }],
};

// v2: 2本以上の {file, solver}。動的な例は、静的とローリングが混在する(ADR-0013)。
const v2 = {
  manifest_version: 2,
  examples: [
    {
      id: "dyn",
      title: "dyn",
      dynamic: true,
      default: { a: "greedy", b: "rolling-greedy" },
      logs: [
        { file: "dyn-cpsat.jsonl", solver: "cpsat" },
        { file: "dyn-greedy.jsonl", solver: "greedy" },
        { file: "dyn-rolling-greedy.jsonl", solver: "rolling-greedy" },
      ],
    },
  ],
};

function first(text: unknown) {
  return parseManifest(JSON.stringify(text))[0]!;
}

describe("parseManifest: v1(後方互換)", () => {
  it("2本の組を、ソルバ名つきの内部の形で読む(ソルバ名はファイル名から導く)", () => {
    expect(parseManifest(JSON.stringify(v1))).toEqual([
      {
        id: "greedy-trap",
        title: "greedy-trap",
        logs: [
          { file: "greedy-trap-greedy.jsonl", solver: "greedy" },
          { file: "greedy-trap-hungarian.jsonl", solver: "hungarian" },
        ],
        dynamic: false,
        defaultPair: null,
        description: null,
      },
    ]);
  });

  it("命名規則(<id>-<solver>.jsonl)に合わないファイル名は、ファイル名そのものをソルバ名にする", () => {
    const e = first({ manifest_version: 1, examples: [{ id: "x", title: "x", logs: ["a.jsonl", "b.jsonl"] }] });
    expect(e.logs.map((l) => l.solver)).toEqual(["a", "b"]);
  });

  it("v1 は、ちょうど2本だけ(1本・3本は捨てる)", () => {
    const text = {
      manifest_version: 1,
      examples: [
        { id: "ok", title: "ok", logs: ["a.jsonl", "b.jsonl"] },
        { id: "one", title: "one", logs: ["a.jsonl"] },
        { id: "three", title: "three", logs: ["a.jsonl", "b.jsonl", "c.jsonl"] },
      ],
    };
    expect(parseManifest(JSON.stringify(text)).map((e) => e.id)).toEqual(["ok"]);
  });

  it("v1 の dynamic・default は無視する(v1 にはない項目)", () => {
    const e = first({
      manifest_version: 1,
      examples: [{ id: "x", title: "x", dynamic: true, default: { a: "a", b: "b" }, logs: ["a.jsonl", "b.jsonl"] }],
    });
    expect(e.dynamic).toBe(false);
    expect(e.defaultPair).toBeNull();
  });
});

describe("parseManifest: v2", () => {
  it("N本の {file, solver}、dynamic、default を読む", () => {
    const e = first(v2);
    expect(e.logs).toHaveLength(3);
    expect(e.logs[1]).toEqual({ file: "dyn-greedy.jsonl", solver: "greedy" });
    expect(e.dynamic).toBe(true);
    expect(e.defaultPair).toEqual(["greedy", "rolling-greedy"]);
  });

  it("2本の v2 も読める", () => {
    const e = first({
      manifest_version: 2,
      examples: [{ id: "x", title: "x", logs: [{ file: "a.jsonl", solver: "a" }, { file: "b.jsonl", solver: "b" }] }],
    });
    expect(e.logs).toHaveLength(2);
    expect(e.dynamic).toBe(false);
  });

  it("未知のフィールドは無視する(後方互換な追加)", () => {
    const extended = { ...v2, extra: 1, examples: [{ ...v2.examples[0], note: "x" }] };
    expect(parseManifest(JSON.stringify(extended))).toHaveLength(1);
  });

  it.each([
    ["1本だけ", [{ file: "a.jsonl", solver: "a" }]],
    ["solver がない", [{ file: "a.jsonl" }, { file: "b.jsonl", solver: "b" }]],
    ["solver が空", [{ file: "a.jsonl", solver: "" }, { file: "b.jsonl", solver: "b" }]],
    ["solver が文字列でない", [{ file: "a.jsonl", solver: 1 }, { file: "b.jsonl", solver: "b" }]],
    ["solver が重複する", [{ file: "a.jsonl", solver: "x" }, { file: "b.jsonl", solver: "x" }]],
    ["file がない", [{ solver: "a" }, { file: "b.jsonl", solver: "b" }]],
    ["要素がオブジェクトでない", ["a.jsonl", "b.jsonl"]],
  ])("不正な例は捨てる: %s", (_label, logs) => {
    const text = { manifest_version: 2, examples: [{ id: "bad", title: "bad", logs }] };
    expect(parseManifest(JSON.stringify(text))).toEqual([]);
  });

  it.each(["https://example.com/a.jsonl", "//example.com/a.jsonl", "/etc/passwd", "../a.jsonl", ""])(
    "相対パスでない file は受け付けない: %j",
    (file) => {
      const text = {
        manifest_version: 2,
        examples: [{ id: "x", title: "x", logs: [{ file, solver: "a" }, { file: "b.jsonl", solver: "b" }] }],
      };
      expect(parseManifest(JSON.stringify(text))).toEqual([]);
    },
  );

  it.each([
    ["同じソルバ", { a: "greedy", b: "greedy" }],
    ["存在しないソルバ", { a: "greedy", b: "nope" }],
    ["片方だけ", { a: "greedy" }],
    ["文字列でない", { a: 1, b: 2 }],
    ["オブジェクトでない", "greedy"],
  ])("不正な default は、無いものとして扱う(例は捨てない): %s", (_label, def) => {
    const text = { ...v2, examples: [{ ...v2.examples[0], default: def }] };
    const e = first(text);
    expect(e.defaultPair).toBeNull();
    expect(e.logs).toHaveLength(3);
  });
});

describe("parseManifest: description(任意。ADR-0013)", () => {
  const withDescription = (description: unknown) => ({
    manifest_version: 2,
    examples: [{ ...v2.examples[0], description }],
  });

  it("文字列なら読む", () => {
    expect(first(withDescription("ローリングが静的に大きく勝つ")).description).toBe("ローリングが静的に大きく勝つ");
  });

  it("無ければ null", () => {
    expect(first(v2).description).toBeNull();
  });

  it.each([
    ["空文字", ""],
    ["空白だけ", "   "],
    ["数値", 1],
    ["配列", ["a"]],
    ["オブジェクト", { a: 1 }],
    ["null", null],
  ])("文字列でない・空なら null(例は捨てない): %s", (_label, value) => {
    const e = first(withDescription(value));
    expect(e.description).toBeNull();
    expect(e.logs).toHaveLength(3);
  });

  it("v1 には description がない(あっても読まない)", () => {
    const text = {
      manifest_version: 1,
      examples: [{ id: "x", title: "x", description: "v1 にはない", logs: ["a.jsonl", "b.jsonl"] }],
    };
    expect(first(text).description).toBeNull();
  });

  it("HTML のような文字列も、そのまま文字列として持つ(解釈しない)", () => {
    expect(first(withDescription("<b>x</b>")).description).toBe("<b>x</b>");
  });
});

describe("parseManifest: 版とトップレベル", () => {
  it.each([
    ["JSON ではない", "not json"],
    ["オブジェクトではない", "[]"],
    ["未対応の版(3)", JSON.stringify({ ...v2, manifest_version: 3 })],
    ["未対応の版(0)", JSON.stringify({ ...v1, manifest_version: 0 })],
    ["版が数値でない", JSON.stringify({ ...v1, manifest_version: "1" })],
    ["版がない", JSON.stringify({ examples: v1.examples })],
    ["examples が配列ではない", JSON.stringify({ manifest_version: 2, examples: {} })],
  ])("読めないときは空(閲覧は妨げない): %s", (_label, text) => {
    expect(parseManifest(text)).toEqual([]);
  });

  it("不正な例だけを捨てる(他の例は残る)", () => {
    const mixed = {
      manifest_version: 2,
      examples: [
        v2.examples[0],
        { id: "num", title: 1, logs: [{ file: "a.jsonl", solver: "a" }, { file: "b.jsonl", solver: "b" }] },
        "string",
      ],
    };
    expect(parseManifest(JSON.stringify(mixed)).map((e) => e.id)).toEqual(["dyn"]);
  });
});

describe("initialPair と optionLabel", () => {
  it("default があればそれ、なければ先頭の2本", () => {
    expect(initialPair(first(v2))).toEqual(["greedy", "rolling-greedy"]);
    const noDefault = first({ ...v2, examples: [{ ...v2.examples[0], default: undefined }] });
    expect(initialPair(noDefault)).toEqual(["cpsat", "greedy"]);
  });

  it("動的な例では、静的ソルバに「到着を無視」、ローリングに「ローリング」を添える", () => {
    const e = first(v2);
    expect(optionLabel(e, "greedy")).toBe("greedy(静的・到着を無視)");
    expect(optionLabel(e, "cpsat")).toBe("cpsat(静的・到着を無視)");
    expect(optionLabel(e, "rolling-greedy")).toBe("rolling-greedy(ローリング)");
  });

  it("静的な例では、ソルバ名のまま", () => {
    const e = first(v1);
    expect(optionLabel(e, "greedy")).toBe("greedy");
  });
});

describe("compareHref", () => {
  it("v1: 既定の組(先頭の2本)で、log を2回指定する URL にする", () => {
    expect(compareHref(first(v1))).toBe(
      "?log=data%2Fgreedy-trap-greedy.jsonl&log=data%2Fgreedy-trap-hungarian.jsonl",
    );
  });

  it("v2: 既定の組で作る", () => {
    expect(compareHref(first(v2))).toBe("?log=data%2Fdyn-greedy.jsonl&log=data%2Fdyn-rolling-greedy.jsonl");
  });

  it("選んだ組(A・B)で作る。順序は A、B のまま", () => {
    const e = first(v2);
    expect(compareHref(e, "cpsat", "greedy")).toBe("?log=data%2Fdyn-cpsat.jsonl&log=data%2Fdyn-greedy.jsonl");
    expect(compareHref(e, "greedy", "cpsat")).toBe("?log=data%2Fdyn-greedy.jsonl&log=data%2Fdyn-cpsat.jsonl");
  });

  it("A だけ・B だけを指定したら、もう一方は既定", () => {
    const e = first(v2);
    expect(compareHref(e, "cpsat")).toBe("?log=data%2Fdyn-cpsat.jsonl&log=data%2Fdyn-rolling-greedy.jsonl");
    expect(compareHref(e, undefined, "cpsat")).toBe("?log=data%2Fdyn-greedy.jsonl&log=data%2Fdyn-cpsat.jsonl");
  });

  it("同じログ・存在しないソルバは null(比較しない)", () => {
    const e = first(v2);
    expect(compareHref(e, "greedy", "greedy")).toBeNull();
    expect(compareHref(e, "greedy", "nope")).toBeNull();
    expect(compareHref(e, "nope", "greedy")).toBeNull();
  });
});
