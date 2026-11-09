import { describe, expect, it } from "vitest";
import { LogError, parseLog } from "./log";
import { golden, joined, lines } from "./test-utils";

const TINY = golden("tiny-greedy");
const DEFAULT = golden("default-greedy");

function replaceLine(text: string, index: number, edit: (o: Record<string, unknown>) => void): string {
  const ls = lines(text);
  const o = JSON.parse(ls[index] as string) as Record<string, unknown>;
  edit(o);
  ls[index] = JSON.stringify(o);
  return joined(ls);
}

describe("parseLog: Python が書いた golden file を読める", () => {
  it("tiny-greedy の内容が、手計算した値と一致する", () => {
    const log = parseLog(TINY);
    expect(log.schemaVersion).toBe(1);
    expect(log.scenario.seed).toBe(0);
    expect([log.scenario.width, log.scenario.height]).toEqual([10, 10]);
    expect(log.scenario.robots.map((r) => [r.id, r.kind, r.start, r.speed, r.capacity])).toEqual([
      ["r0", "amr", [6, 6], 3, 10],
      ["r1", "mobile_manipulator", [0, 4], 1, 3],
    ]);
    expect(log.scenario.robots[1]?.skills).toEqual(["carry", "manipulate"]);
    expect(log.scenario.tasks.map((t) => [t.id, t.location, t.requiredSkill, t.demand, t.serviceTime])).toEqual([
      ["t0", [8, 7], "carry", 5, 4],
      ["t1", [5, 9], "manipulate", 3, 2],
      ["t2", [4, 2], "carry", 2, 5],
    ]);
    expect(log.solver).toEqual({ name: "greedy", config: {} });
    expect(log.plan).toEqual({ r0: ["t0", "t2"], r1: ["t1"] });
    expect(log.segments).toHaveLength(6);
    expect(log.metrics).toEqual({
      makespan: 13,
      totalDistance: 22,
      busyTotal: 25,
      availableTotal: 26,
      perRobot: {
        r0: { finish: 13, distance: 12, busy: 13 },
        r1: { finish: 12, distance: 10, busy: 12 },
      },
    });
  });

  it("default-greedy を読め、ログの指標と区間が整合している", () => {
    const log = parseLog(DEFAULT);
    const m = log.metrics;
    // 区間から独立に求めた値が、ログの metrics と一致する(読む側が信頼できることの確認)
    expect(Math.max(...log.segments.map((g) => g.t1))).toBe(m.makespan);
    expect(Math.max(...Object.values(m.perRobot).map((r) => r.finish))).toBe(m.makespan);
    expect(log.segments.reduce((sum, g) => sum + (g.t1 - g.t0), 0)).toBe(m.busyTotal);
    expect(log.scenario.robots.length * m.makespan).toBe(m.availableTotal);
    const moveDistance = log.segments
      .filter((g) => g.kind === "move")
      .reduce((sum, g) => sum + Math.abs(g.to[0] - g.from[0]) + Math.abs(g.to[1] - g.from[1]), 0);
    expect(moveDistance).toBe(m.totalDistance);
  });

  it("全タスクが plan にちょうど1回ずつ現れる", () => {
    const log = parseLog(DEFAULT);
    const assigned = Object.values(log.plan).flat().sort();
    expect(assigned).toEqual(log.scenario.tasks.map((t) => t.id).sort());
  });
});

describe("parseLog: 読む側の規則(ADR-0004)", () => {
  it("未対応のスキーマ版は、原因が分かるエラーにする(他の検証より先に)", () => {
    const text = replaceLine(TINY, 0, (o) => {
      o["schema_version"] = 2;
    });
    expect(() => parseLog(text)).toThrow(/未対応のスキーマ版: 2/);
    // 版が違えば、他の部分が壊れていても、版のエラーが先に出る
    const broken = joined(["{\"schema_version\":2,\"type\":\"header\"}", "{\"type\":\"scenario\"}", "{\"type\":\"metrics\"}"]);
    expect(() => parseLog(broken)).toThrow(/未対応のスキーマ版/);
  });

  it("未知のフィールドと、metrics の前の未知の type の行は無視する(後方互換な追加)", () => {
    const withField = replaceLine(TINY, 2, (o) => {
      o["future_field"] = { anything: [1, 2] };
    });
    const ls = lines(withField);
    ls.splice(3, 0, '{"note":"future extension","type":"annotation"}');
    expect(parseLog(joined(ls))).toEqual(parseLog(TINY));
  });

  it("途中で切れたログを拒否する", () => {
    expect(() => parseLog(TINY.slice(0, -1))).toThrow(/末尾が改行/);
    expect(() => parseLog(joined(lines(TINY).slice(0, -1)))).toThrow(/metrics/);
    expect(() => parseLog(joined(lines(TINY).slice(0, -1).concat('{"makespan":'))) ).toThrow(LogError);
  });

  it("metrics の後ろに行があるログを拒否する", () => {
    const ls = lines(TINY);
    // 既知の行(segment)でも、未知の type の行でも不正。metrics は常に末尾(ADR-0004)
    expect(() => parseLog(joined([...ls, ls[4] as string]))).toThrow(/末尾の行が metrics ではない/);
    expect(() => parseLog(joined([...ls, '{"note":"x","type":"annotation"}']))).toThrow(
      /末尾の行が metrics ではない/,
    );
  });

  it("行の並びが違うログを拒否する", () => {
    const ls = lines(TINY);
    [ls[1], ls[2]] = [ls[2] as string, ls[1] as string];
    expect(() => parseLog(joined(ls))).toThrow(/並び/);
  });

  it("空行・不正なJSON・オブジェクトでない行を拒否する", () => {
    const ls = lines(TINY);
    expect(() => parseLog(joined([...ls.slice(0, 2), "", ...ls.slice(2)]))).toThrow(/空行/);
    expect(() => parseLog(joined([...ls.slice(0, 2), "{oops", ...ls.slice(2)]))).toThrow(/JSON/);
    expect(() => parseLog(joined([...ls.slice(0, 2), "[1,2]", ...ls.slice(2)]))).toThrow(/type/);
  });

  it.each([
    ["小数の速度", 1, (o: Record<string, unknown>) => { ((o["robots"] as Record<string, unknown>[])[0] as Record<string, unknown>)["speed"] = 1.5; }, /speed/],
    ["必須フィールドの欠落", 1, (o: Record<string, unknown>) => { delete o["width"]; }, /width/],
    ["位置が2要素でない", 1, (o: Record<string, unknown>) => { ((o["robots"] as Record<string, unknown>[])[0] as Record<string, unknown>)["start"] = [1, 2, 3]; }, /start/],
    ["config に配列", 2, (o: Record<string, unknown>) => { o["config"] = { x: [1] }; }, /config/],
    ["segment の kind が不正", 4, (o: Record<string, unknown>) => { o["kind"] = "fly"; }, /kind/],
    ["長さ0の segment", 4, (o: Record<string, unknown>) => { o["t1"] = o["t0"]; }, /t0 < t1/],
    ["metrics の負の値", 10, (o: Record<string, unknown>) => { o["makespan"] = -1; }, /makespan/],
  ])("不正な値を拒否する: %s", (_name, index, edit, message) => {
    expect(() => parseLog(replaceLine(TINY, index, edit))).toThrow(message);
  });
});
