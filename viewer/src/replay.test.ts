import { describe, expect, it } from "vitest";
import { parseLog } from "./log";
import { positionAlong, Replay, utilizationText } from "./replay";
import { golden } from "./test-utils";

const tiny = new Replay(parseLog(golden("tiny-greedy")));
const big = new Replay(parseLog(golden("default-greedy")));
// 動的な到着(ADR-0011): t0 は到着 4、t1 は到着 8、t2 は到着 2。r0 は t0 → t2、r1 は t1。
const dynamic = new Replay(parseLog(golden("dynamic-greedy")));
const dynamicRolling = new Replay(parseLog(golden("dynamic-rolling-greedy")));

describe("positionAlong: x 方向に進んでから y 方向", () => {
  it("x を先に進める", () => {
    // (8,7) → (4,2): dx=-4, dy=-5。全体9のうち 4.5 進むと x は終点まで、y は 0.5 進む
    expect(positionAlong([8, 7], [4, 2], 0.5)).toEqual([4, 6.5]);
    expect(positionAlong([6, 6], [8, 7], 0.5)).toEqual([7.5, 6]);
  });

  it("端点と、進まない場合", () => {
    expect(positionAlong([1, 1], [4, 5], 0)).toEqual([1, 1]);
    expect(positionAlong([1, 1], [4, 5], 1)).toEqual([4, 5]);
    expect(positionAlong([3, 3], [3, 3], 0.7)).toEqual([3, 3]);
    expect(positionAlong([1, 1], [4, 5], 5)).toEqual([4, 5]); // 範囲外は丸める
    expect(positionAlong([1, 1], [4, 5], -1)).toEqual([1, 1]);
  });
});

describe("Replay: tiny-greedy を手計算の値と突き合わせる", () => {
  // r0: t0 へ移動 [0,1]、作業 [1,5]、t2 へ移動 [5,8]、作業 [8,13]。 r1: t1 へ移動 [0,10]、作業 [10,12]。
  it("ロボットの位置と状態", () => {
    expect(tiny.robotStateAt("r0", 0)).toEqual({ position: [6, 6], activity: "moving", taskId: "t0" });
    expect(tiny.robotStateAt("r0", 0.5)).toEqual({ position: [7.5, 6], activity: "moving", taskId: "t0" });
    expect(tiny.robotStateAt("r0", 1)).toEqual({ position: [8, 7], activity: "servicing", taskId: "t0" });
    expect(tiny.robotStateAt("r0", 4.99)).toMatchObject({ activity: "servicing", taskId: "t0" });
    expect(tiny.robotStateAt("r0", 5)).toEqual({ position: [8, 7], activity: "moving", taskId: "t2" });
    expect(tiny.robotStateAt("r0", 6.5)).toEqual({ position: [4, 6.5], activity: "moving", taskId: "t2" });
    expect(tiny.robotStateAt("r0", 8)).toEqual({ position: [4, 2], activity: "servicing", taskId: "t2" });
    expect(tiny.robotStateAt("r0", 13)).toEqual({ position: [4, 2], activity: "done", taskId: null });
    expect(tiny.robotStateAt("r1", 12)).toEqual({ position: [5, 9], activity: "done", taskId: null });
  });

  it("時刻が範囲外でも壊れない", () => {
    expect(tiny.robotStateAt("r0", -5).position).toEqual([6, 6]);
    expect(tiny.robotStateAt("r0", 999)).toEqual({ position: [4, 2], activity: "done", taskId: null });
  });

  it("タスクの状態: 作業中だけ serving、完了後は done", () => {
    expect(tiny.taskStatusAt("t0", 0.9)).toBe("pending");
    expect(tiny.taskStatusAt("t0", 1)).toBe("serving");
    expect(tiny.taskStatusAt("t0", 4.9)).toBe("serving");
    expect(tiny.taskStatusAt("t0", 5)).toBe("done");
    expect(tiny.taskStatusAt("t2", 7.9)).toBe("pending"); // 移動中はまだ作業していない
    expect(tiny.taskStatusAt("t2", 8)).toBe("serving");
    expect(tiny.taskStatusAt("t1", 11)).toBe("serving");
    expect(tiny.taskStatusAt("t1", 12)).toBe("done");
  });

  it("未知のロボットは例外", () => {
    expect(() => tiny.robotStateAt("rX", 0)).toThrow(/未知のロボット/);
  });

  it("makespan を持つ", () => {
    expect(tiny.makespan).toBe(13);
  });
});

describe("Replay: default-greedy で成り立つ性質", () => {
  const log = big.log;
  const ticks = Array.from({ length: big.makespan + 1 }, (_, t) => t);

  it("開始時刻は初期位置、完了時刻は最後のタスクの場所にいる", () => {
    for (const r of log.scenario.robots) {
      const route = log.plan[r.id] ?? [];
      const first = big.robotStateAt(r.id, 0);
      if (route.length > 0) {
        expect(first.activity).toBe("moving"); // 先頭タスクが初期位置にあれば作業中
      }
      expect(big.robotStateAt(r.id, big.makespan).activity).toBe(route.length > 0 ? "done" : "idle");
      const lastTask = log.scenario.tasks.find((t) => t.id === route[route.length - 1]);
      if (lastTask !== undefined) {
        expect(big.robotStateAt(r.id, big.makespan).position).toEqual(lastTask.location);
      }
    }
  });

  it("位置は常に格子の中にあり、1ティックの移動はそのロボットの速度以下", () => {
    for (const r of log.scenario.robots) {
      let previous = big.robotStateAt(r.id, 0).position;
      for (const t of ticks.slice(1)) {
        const { position } = big.robotStateAt(r.id, t);
        expect(position[0]).toBeGreaterThanOrEqual(0);
        expect(position[0]).toBeLessThanOrEqual(log.scenario.width - 1);
        expect(position[1]).toBeGreaterThanOrEqual(0);
        expect(position[1]).toBeLessThanOrEqual(log.scenario.height - 1);
        const step = Math.abs(position[0] - previous[0]) + Math.abs(position[1] - previous[1]);
        expect(step).toBeLessThanOrEqual(r.speed + 1e-9);
        previous = position;
      }
    }
  });

  it("作業中は、そのタスクの場所にいる", () => {
    for (const r of log.scenario.robots) {
      for (const t of ticks) {
        const s = big.robotStateAt(r.id, t);
        if (s.activity === "servicing") {
          const task = log.scenario.tasks.find((x) => x.id === s.taskId);
          expect(s.position).toEqual(task?.location);
        }
      }
    }
  });

  it("タスクの状態は unreleased → pending → serving → done の順にしか進まない", () => {
    const rank = { unreleased: 0, pending: 1, serving: 2, done: 3 } as const;
    for (const replay of [big, dynamic, dynamicRolling]) {
      const times = Array.from({ length: replay.makespan * 4 + 1 }, (_, i) => i / 4);
      for (const task of replay.log.scenario.tasks) {
        let previous = 0;
        for (const t of times) {
          const now = rank[replay.taskStatusAt(task.id, t)];
          expect(now).toBeGreaterThanOrEqual(previous);
          previous = now;
        }
        expect(replay.taskStatusAt(task.id, replay.makespan)).toBe("done");
      }
    }
  });
});

describe("Replay: 到着前のタスク(unreleased。ADR-0011)", () => {
  it("到着時刻の手前までは unreleased、ちょうどから pending", () => {
    // t0 は到着 4: 3.99 までは現れていない。4 から到着済みで未着手。
    expect(dynamic.taskStatusAt("t0", 0)).toBe("unreleased");
    expect(dynamic.taskStatusAt("t0", 3.99)).toBe("unreleased");
    expect(dynamic.taskStatusAt("t0", 4)).toBe("pending");
    // t1 は到着 8。r1 は 8 に出発する(移動中は pending)。作業は 18 から。
    expect(dynamic.taskStatusAt("t1", 7.99)).toBe("unreleased");
    expect(dynamic.taskStatusAt("t1", 8)).toBe("pending");
    expect(dynamic.taskStatusAt("t1", 17.99)).toBe("pending");
    expect(dynamic.taskStatusAt("t1", 18)).toBe("serving");
    expect(dynamic.taskStatusAt("t1", 20)).toBe("done");
  });

  it("到着済みなら、ロボットが向かっていなくても pending(unreleased ではない)", () => {
    // t2 は到着 2。静的ソルバの Plan では r0 が t0 の後に t2 へ向かう(t0 の作業が [5,9]、t2 は 9 から移動)。
    expect(dynamic.taskStatusAt("t2", 1.99)).toBe("unreleased");
    expect(dynamic.taskStatusAt("t2", 2)).toBe("pending");
    expect(dynamic.taskStatusAt("t2", 8.99)).toBe("pending"); // 到着済みだが、r0 は t0 の作業中
    expect(dynamic.taskStatusAt("t2", 12)).toBe("serving");
  });

  it("同じシナリオでも、ローリングは順序が違う(到着済みの t2 を先に取る)", () => {
    // ローリング: r0 は t2 (到着 2) へ 2 から出発し、作業は [4,9]。t0 (到着 4) は後。
    expect(dynamicRolling.taskStatusAt("t2", 2)).toBe("pending");
    expect(dynamicRolling.taskStatusAt("t2", 4)).toBe("serving");
    expect(dynamicRolling.taskStatusAt("t0", 4)).toBe("pending"); // 到着したが、r0 は t2 の作業中
    expect(dynamicRolling.taskStatusAt("t0", 12)).toBe("serving");
  });

  it("静的なログ(到着が全て 0)では、unreleased は一度も現れない", () => {
    for (const replay of [tiny, big]) {
      const times = Array.from({ length: replay.makespan * 4 + 1 }, (_, i) => i / 4);
      for (const task of replay.log.scenario.tasks) {
        for (const t of times) {
          expect(replay.taskStatusAt(task.id, t)).not.toBe("unreleased");
        }
      }
    }
  });

  it("動的かどうかと、最後の到着時刻", () => {
    expect(dynamic.isDynamic).toBe(true);
    expect(dynamic.lastRelease).toBe(8);
    expect(dynamicRolling.lastRelease).toBe(8);
    expect(tiny.isDynamic).toBe(false);
    expect(tiny.lastRelease).toBe(0);
    expect(big.isDynamic).toBe(false);
  });

  it("負の時刻は、どのタスクの到着よりも前(静的でも unreleased)。UI からは届かないが、壊れない", () => {
    expect(dynamic.taskStatusAt("t0", -1)).toBe("unreleased");
    expect(tiny.taskStatusAt("t0", -1)).toBe("unreleased");
    expect(tiny.taskStatusAt("t0", 0)).toBe("pending"); // 到着 0 は t=0 から到着済み
  });
});

describe("utilizationText", () => {
  it("分子・分母から計算し、完了時間が0なら未定義の「—」", () => {
    const base = { makespan: 0, totalDistance: 0, busyTotal: 0, availableTotal: 0, perRobot: {} };
    expect(utilizationText({ ...base, busyTotal: 25, availableTotal: 26 })).toBe("96.2%");
    expect(utilizationText({ ...base, busyTotal: 6, availableTotal: 6 })).toBe("100.0%");
    expect(utilizationText(base)).toBe("—");
    expect(utilizationText(tiny.log.metrics)).toBe("96.2%");
  });
});
