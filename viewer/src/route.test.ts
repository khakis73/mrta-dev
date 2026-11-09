import { describe, expect, it } from "vitest";
import { parseLog } from "./log";
import { routePoints } from "./route";
import { golden } from "./test-utils";

const tiny = parseLog(golden("tiny-greedy"));

describe("routePoints", () => {
  it("初期位置から、タスクを実行順に、x 方向 → y 方向の角を挟んで結ぶ", () => {
    // r0: (6,6) → t0 (8,7) → t2 (4,2)
    expect(routePoints(tiny, "r0")).toEqual([
      [6, 6],
      [8, 6], // x 方向に進んだ角
      [8, 7],
      [4, 7],
      [4, 2],
    ]);
    // r1: (0,4) → t1 (5,9)
    expect(routePoints(tiny, "r1")).toEqual([
      [0, 4],
      [5, 4],
      [5, 9],
    ]);
  });

  it("同じ行・列にあるタスクは角を作らず、同じ場所のタスクは点を足さない", () => {
    const log = structuredClone(tiny);
    log.scenario.tasks[0]!.location = [6, 9]; // r0 の初期位置と同じ x
    log.scenario.tasks[2]!.location = [6, 9]; // 直前のタスクと同じ場所
    expect(routePoints(log, "r0")).toEqual([
      [6, 6],
      [6, 9],
    ]);
  });

  it("未知のロボット・タスクは例外", () => {
    expect(() => routePoints(tiny, "rX")).toThrow(/未知のロボット/);
    const bad = { ...tiny, plan: { ...tiny.plan, r0: ["tX"] } };
    expect(() => routePoints(bad, "r0")).toThrow(/未知のタスク/);
  });
});
