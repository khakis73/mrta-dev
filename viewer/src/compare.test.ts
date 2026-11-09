import { describe, expect, it } from "vitest";
import { betterUtilization, compareMetrics, scenarioMismatch } from "./compare";
import { parseLog } from "./log";
import type { Metrics } from "./log";
import { golden } from "./test-utils";

const greedy = parseLog(golden("greedy-trap-greedy"));
const hungarian = parseLog(golden("greedy-trap-hungarian"));

function metrics(over: Partial<Metrics>): Metrics {
  return { makespan: 10, totalDistance: 20, busyTotal: 10, availableTotal: 20, perRobot: {}, ...over };
}

describe("scenarioMismatch", () => {
  it("同じシナリオを別のソルバで解いた2つのログは一致する(Python の golden file)", () => {
    expect(greedy.solver.name).toBe("greedy");
    expect(hungarian.solver.name).toBe("hungarian");
    expect(scenarioMismatch(greedy.scenario, hungarian.scenario)).toBeNull();
  });

  it("別のシナリオは、違いの項目を示して拒否する", () => {
    const other = parseLog(golden("tiny-greedy"));
    expect(scenarioMismatch(greedy.scenario, other.scenario)).toMatch(/一致しない/);
  });

  it("シードが違う", () => {
    const changed = { ...hungarian.scenario, seed: 9 };
    expect(scenarioMismatch(greedy.scenario, changed)).toBe(
      "シナリオが一致しない: seed が違う(0 と 9)",
    );
  });

  it("ロボット1台の設定が違う", () => {
    const [r0, ...rest] = hungarian.scenario.robots;
    const changed = { ...hungarian.scenario, robots: [{ ...r0!, speed: r0!.speed + 1 }, ...rest] };
    expect(scenarioMismatch(greedy.scenario, changed)).toBe(
      "シナリオが一致しない: ロボット r0 の設定が違う",
    );
  });

  it("タスク1件の設定が違う", () => {
    const [t0, ...rest] = hungarian.scenario.tasks;
    const changed = { ...hungarian.scenario, tasks: [{ ...t0!, serviceTime: 9 }, ...rest] };
    expect(scenarioMismatch(greedy.scenario, changed)).toBe(
      "シナリオが一致しない: タスク t0 の設定が違う",
    );
  });

  it("タスクの数が違う", () => {
    const changed = { ...hungarian.scenario, tasks: hungarian.scenario.tasks.slice(1) };
    expect(scenarioMismatch(greedy.scenario, changed)).toMatch(/タスクの集合が違う/);
  });
});

describe("compareMetrics(手計算: greedy-trap は貪欲法 11、ハンガリアン法 6)", () => {
  const rows = compareMetrics(greedy.metrics, hungarian.metrics);
  const row = (name: string) => rows.find((r) => r.name === name)!;

  it("完了時間は小さいほうが優れ、差は B − A", () => {
    expect(row("makespan")).toMatchObject({
      a: "11 ティック",
      b: "6 ティック",
      diff: "-5",
      better: "b",
    });
  });

  it("総移動距離は小さいほうが優れる", () => {
    // 貪欲法: r0 が (0,0)→(3,0)→(0,3) = 3 + 6 = 9。ハンガリアン法: 3 + 5 = 8
    expect(row("total_distance")).toMatchObject({ a: "9", b: "8", diff: "-1", better: "b" });
  });

  it("稼働率は大きいほうが優れる(ハンガリアン法は 10/12、貪欲法は 11/22)", () => {
    expect(row("utilization")).toMatchObject({ a: "50.0%", b: "83.3%", better: "b" });
    expect(row("utilization").diff).toBe("+33.3 pt");
  });
});

describe("優劣の判定", () => {
  it("同値には印を付けない", () => {
    const rows = compareMetrics(metrics({}), metrics({}));
    expect(rows.map((r) => r.better)).toEqual([null, null, null]);
    expect(rows.map((r) => r.diff)).toEqual(["0", "0", "0.0 pt"]);
  });

  it("稼働率は整数の交差乗算で比べる(割り算の丸めで同値に見えるものも区別する)", () => {
    // 1/3 と 333333333/1000000000 は、小数点以下1桁の表示では同じ 33.3%
    const a = metrics({ busyTotal: 1, availableTotal: 3 });
    const b = metrics({ busyTotal: 333_333_333, availableTotal: 1_000_000_000 });
    expect(betterUtilization(a, b)).toBe("a");
    expect(betterUtilization(b, a)).toBe("b");
  });

  it("完了時間が0のログがあれば、稼働率は比べない", () => {
    const empty = metrics({ makespan: 0, busyTotal: 0, availableTotal: 0 });
    expect(betterUtilization(empty, metrics({}))).toBeNull();
    const row = compareMetrics(empty, metrics({})).find((r) => r.name === "utilization")!;
    expect(row).toMatchObject({ a: "—", better: null, diff: "—" });
  });
});
