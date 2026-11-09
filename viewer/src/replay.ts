// ログからある時刻の状態を求める(リプレイの計算)。
//
// ログに書かれた時間区間(segment)を読むだけで、実行の意味は再計算しない(ADR-0004)。
// 区間の内側の位置は、x 方向に進んでから y 方向に進むものとして線形補間する。
// これは**表示のためだけ**で、浮動小数点を使ってよい(ログ自体は整数のみ)。

import type { Log, Metrics, Point, Segment } from "./log";

export type Activity = "idle" | "moving" | "servicing" | "done";
export type TaskStatus = "pending" | "serving" | "done";

export interface RobotState {
  position: readonly [number, number];
  activity: Activity;
  /** 移動中・作業中のタスク。それ以外は null */
  taskId: string | null;
}

/** from から to へ、マンハッタン経路(x → y の順)で progress(0〜1)だけ進んだ位置。 */
export function positionAlong(from: Point, to: Point, progress: number): readonly [number, number] {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const total = Math.abs(dx) + Math.abs(dy);
  if (total === 0) {
    return [from[0], from[1]];
  }
  const travelled = Math.min(Math.max(progress, 0), 1) * total;
  if (travelled <= Math.abs(dx)) {
    return [from[0] + Math.sign(dx) * travelled, from[1]];
  }
  return [to[0], from[1] + Math.sign(dy) * (travelled - Math.abs(dx))];
}

/** 稼働率の表示。分子・分母(整数)から計算する。完了時間が0なら未定義で「—」。 */
export function utilizationText(m: Metrics): string {
  if (m.availableTotal === 0) {
    return "—";
  }
  return `${((m.busyTotal / m.availableTotal) * 100).toFixed(1)}%`;
}

export class Replay {
  readonly makespan: number;
  private readonly segmentsByRobot = new Map<string, Segment[]>();
  private readonly completion = new Map<string, number>();
  private readonly serviceStart = new Map<string, number>();
  private readonly startOf = new Map<string, Point>();

  constructor(readonly log: Log) {
    this.makespan = log.metrics.makespan;
    for (const r of log.scenario.robots) {
      this.startOf.set(r.id, r.start);
      this.segmentsByRobot.set(r.id, []);
    }
    for (const g of log.segments) {
      this.segmentsByRobot.get(g.robot)?.push(g);
    }
    for (const segs of this.segmentsByRobot.values()) {
      segs.sort((a, b) => a.t0 - b.t0);
    }
    this.indexTasks();
  }

  /**
   * タスクの完了時刻と作業の開始時刻。
   * 完了時刻はそのタスクの区間の最大の t1。区間が1つもない(その場にいて作業時間も0)タスクは、
   * 経路の直前のタスクの完了時刻(先頭なら0)とする。
   */
  private indexTasks(): void {
    for (const g of this.log.segments) {
      this.completion.set(g.task, Math.max(this.completion.get(g.task) ?? 0, g.t1));
      if (g.kind === "service") {
        this.serviceStart.set(g.task, g.t0);
      }
    }
    for (const route of Object.values(this.log.plan)) {
      let previous = 0;
      for (const taskId of route) {
        const done = this.completion.get(taskId) ?? previous;
        this.completion.set(taskId, done);
        previous = done;
      }
    }
  }

  robotStateAt(robotId: string, t: number): RobotState {
    const start = this.startOf.get(robotId);
    if (start === undefined) {
      throw new Error(`未知のロボット: ${robotId}`);
    }
    const segs = this.segmentsByRobot.get(robotId) ?? [];
    const last = segs[segs.length - 1];
    if (last === undefined) {
      return { position: [start[0], start[1]], activity: "idle", taskId: null };
    }

    let position: readonly [number, number] = [start[0], start[1]];
    for (const g of segs) {
      if (t < g.t0) {
        break; // この区間はまだ始まっていない。直前の終点にいる。
      }
      if (t < g.t1) {
        if (g.kind === "service") {
          return { position: [g.to[0], g.to[1]], activity: "servicing", taskId: g.task };
        }
        const progress = (t - g.t0) / (g.t1 - g.t0);
        return { position: positionAlong(g.from, g.to, progress), activity: "moving", taskId: g.task };
      }
      position = [g.to[0], g.to[1]];
    }
    return { position, activity: t >= last.t1 ? "done" : "idle", taskId: null };
  }

  taskStatusAt(taskId: string, t: number): TaskStatus {
    const done = this.completion.get(taskId);
    if (done === undefined) {
      return "pending"; // どのロボットにも割り当てられていない(不正なログ)。
    }
    if (t >= done) {
      return "done";
    }
    const started = this.serviceStart.get(taskId);
    return started !== undefined && t >= started ? "serving" : "pending";
  }
}
