// ロボットの計画経路の折れ線(表示用)。x 方向に進んでから y 方向に進む(ADR-0004 の描画規約)。

import type { Log, Point } from "./log";

export function routePoints(log: Log, robotId: string): Point[] {
  const robot = log.scenario.robots.find((r) => r.id === robotId);
  if (robot === undefined) {
    throw new Error(`未知のロボット: ${robotId}`);
  }
  const locations = new Map(log.scenario.tasks.map((t) => [t.id, t.location] as const));
  const points: Point[] = [robot.start];
  let current: Point = robot.start;
  for (const taskId of log.plan[robotId] ?? []) {
    const next = locations.get(taskId);
    if (next === undefined) {
      throw new Error(`未知のタスク: ${taskId}`);
    }
    if (next[0] !== current[0] && next[1] !== current[1]) {
      points.push([next[0], current[1]]); // x 方向に進んだあとの角
    }
    if (next[0] !== current[0] || next[1] !== current[1]) {
      points.push(next);
    }
    current = next;
  }
  return points;
}
