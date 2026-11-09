// 盤面(SVG)の描画。ログ由来の文字列は属性にだけ入れ、innerHTML は使わない。
// 盤面にはテキストを描かない(IDなどは HTML の表に出す)。スクリーンショットテストが、
// フォントの違うOS間でも安定するようにするため。

import type { Log } from "./log";
import type { Replay } from "./replay";
import { routePoints } from "./route";

const SVG_NS = "http://www.w3.org/2000/svg";
export const ROBOT_COLORS = [
  "#2563eb",
  "#dc2626",
  "#059669",
  "#d97706",
  "#7c3aed",
  "#0891b2",
  "#be185d",
  "#4b5563",
];

export function robotColor(index: number): string {
  return ROBOT_COLORS[index % ROBOT_COLORS.length] as string;
}

function el<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | number>,
): SVGElementTagNameMap[K] {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    node.setAttribute(k, String(v));
  }
  return node;
}

export interface Board {
  svg: SVGSVGElement;
  /** 時刻 t の状態に更新する */
  update(t: number): void;
}

export function createBoard(replay: Replay): Board {
  const log: Log = replay.log;
  const { width, height } = log.scenario;
  const svg = el("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": "ロボットとタスクの盤面",
    preserveAspectRatio: "xMidYMid meet",
  });
  svg.id = "board";

  svg.append(el("rect", { class: "board-bg", x: 0, y: 0, width, height }));

  // 格子線
  const gridPath: string[] = [];
  for (let x = 0; x <= width; x++) {
    gridPath.push(`M${x} 0V${height}`);
  }
  for (let y = 0; y <= height; y++) {
    gridPath.push(`M0 ${y}H${width}`);
  }
  svg.append(el("path", { class: "board-grid", d: gridPath.join("") }));

  // 計画経路(薄い破線)。セルの中心を通す。
  log.scenario.robots.forEach((robot, index) => {
    const points = routePoints(log, robot.id)
      .map(([x, y]) => `${x + 0.5},${y + 0.5}`)
      .join(" ");
    svg.append(
      el("polyline", { class: "board-route", points, stroke: robotColor(index), fill: "none" }),
    );
  });

  // タスク
  const taskNodes = new Map<string, SVGCircleElement>();
  for (const task of log.scenario.tasks) {
    const node = el("circle", {
      class: "board-task",
      cx: task.location[0] + 0.5,
      cy: task.location[1] + 0.5,
      r: 0.28,
      "data-task": task.id,
      "data-status": "pending",
    });
    taskNodes.set(task.id, node);
    svg.append(node);
  }

  // ロボット(AMR は円、それ以外は四角。形は表示のためだけで、ソルバとは無関係)
  const robotNodes = new Map<string, SVGGElement>();
  log.scenario.robots.forEach((robot, index) => {
    const group = el("g", {
      class: "board-robot",
      "data-robot": robot.id,
      "data-activity": "idle",
    });
    const color = robotColor(index);
    group.append(
      robot.kind === "amr"
        ? el("circle", { r: 0.4, fill: color })
        : el("rect", { x: -0.38, y: -0.38, width: 0.76, height: 0.76, fill: color }),
    );
    robotNodes.set(robot.id, group);
    svg.append(group);
  });

  function update(t: number): void {
    for (const task of log.scenario.tasks) {
      taskNodes.get(task.id)?.setAttribute("data-status", replay.taskStatusAt(task.id, t));
    }
    for (const robot of log.scenario.robots) {
      const state = replay.robotStateAt(robot.id, t);
      const node = robotNodes.get(robot.id);
      node?.setAttribute("transform", `translate(${state.position[0] + 0.5} ${state.position[1] + 0.5})`);
      node?.setAttribute("data-activity", state.activity);
    }
  }

  update(0);
  return { svg, update };
}
