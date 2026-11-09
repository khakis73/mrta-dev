// 2つのログの比較(ADR-0006)。ログの値を読んで並べるだけで、実行の意味は再計算しない。

import type { Log, Metrics } from "./log";
import { utilizationText } from "./replay";

type ScenarioOf = Log["scenario"];

/**
 * 2つのシナリオが一致しなければ、違いの説明を返す。一致なら null。
 * 比較の前提は「同じ問題」であること(ADR-0004)。構造として全項目を比べる。
 */
export function scenarioMismatch(a: ScenarioOf, b: ScenarioOf): string | null {
  for (const key of ["seed", "width", "height"] as const) {
    if (a[key] !== b[key]) {
      return `シナリオが一致しない: ${key} が違う(${a[key]} と ${b[key]})`;
    }
  }
  const differing = (x: unknown, y: unknown): boolean => JSON.stringify(x) !== JSON.stringify(y);

  const robotIds = (s: ScenarioOf): string => s.robots.map((r) => r.id).join(",");
  if (robotIds(a) !== robotIds(b)) {
    return `シナリオが一致しない: ロボットの集合が違う(${robotIds(a)} と ${robotIds(b)})`;
  }
  for (const [i, robot] of a.robots.entries()) {
    if (differing(robot, b.robots[i])) {
      return `シナリオが一致しない: ロボット ${robot.id} の設定が違う`;
    }
  }
  const taskIds = (s: ScenarioOf): string => s.tasks.map((t) => t.id).join(",");
  if (taskIds(a) !== taskIds(b)) {
    return `シナリオが一致しない: タスクの集合が違う(${taskIds(a)} と ${taskIds(b)})`;
  }
  for (const [i, task] of a.tasks.entries()) {
    if (differing(task, b.tasks[i])) {
      return `シナリオが一致しない: タスク ${task.id} の設定が違う`;
    }
  }
  return null;
}

export type Side = "a" | "b";

export interface MetricRow {
  name: "makespan" | "total_distance" | "utilization";
  label: string;
  a: string;
  b: string;
  /** B − A。見やすさのための表示。 */
  diff: string;
  /** 優れているほう。同値、または比較できないときは null。 */
  better: Side | null;
}

function signed(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

/** 小さいほうが優れている整数の指標。 */
function lowerIsBetter(a: number, b: number): Side | null {
  return a === b ? null : a < b ? "a" : "b";
}

/**
 * 稼働率(busy / available)は大きいほうが優れている。割り算せず、整数の交差乗算で比べる。
 * どちらかの完了時間が 0(available が 0)なら、稼働率は未定義なので比べない。
 */
export function betterUtilization(a: Metrics, b: Metrics): Side | null {
  if (a.availableTotal === 0 || b.availableTotal === 0) {
    return null;
  }
  const left = a.busyTotal * b.availableTotal;
  const right = b.busyTotal * a.availableTotal;
  return left === right ? null : left > right ? "a" : "b";
}

function utilizationDiff(a: Metrics, b: Metrics): string {
  if (a.availableTotal === 0 || b.availableTotal === 0) {
    return "—";
  }
  const points = (b.busyTotal / b.availableTotal - a.busyTotal / a.availableTotal) * 100;
  const text = points.toFixed(1);
  return `${points > 0 && text !== "0.0" ? "+" : ""}${text} pt`;
}

export function compareMetrics(a: Metrics, b: Metrics): MetricRow[] {
  return [
    {
      name: "makespan",
      label: "完了時間",
      a: `${a.makespan} ティック`,
      b: `${b.makespan} ティック`,
      diff: signed(b.makespan - a.makespan),
      better: lowerIsBetter(a.makespan, b.makespan),
    },
    {
      name: "total_distance",
      label: "総移動距離",
      a: String(a.totalDistance),
      b: String(b.totalDistance),
      diff: signed(b.totalDistance - a.totalDistance),
      better: lowerIsBetter(a.totalDistance, b.totalDistance),
    },
    {
      name: "utilization",
      label: "稼働率",
      a: utilizationText(a),
      b: utilizationText(b),
      diff: utilizationDiff(a, b),
      better: betterUtilization(a, b),
    },
  ];
}
