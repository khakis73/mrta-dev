// リプレイ画面の組み立てと操作。DOM は createElement と textContent だけで作る(innerHTML は使わない)。

import { createBoard, robotColor } from "./board";
import { compareMetrics, scenarioMismatch } from "./compare";
import type { MetricRow } from "./compare";
import type { Log } from "./log";
import { compareHref } from "./manifest";
import type { Example } from "./manifest";
import { Player, frameSeconds } from "./player";
import { Replay, utilizationText } from "./replay";
import type { Activity } from "./replay";

const ACTIVITY_LABEL: Record<Activity, string> = {
  idle: "待機",
  moving: "移動中",
  servicing: "作業中",
  done: "完了",
};

const KIND_LABEL: Record<string, string> = {
  amr: "AMR",
  mobile_manipulator: "モバイルマニピュレーター",
};

const SPEEDS = [1, 2, 4, 8];

function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string> = {},
  ...children: (Node | string)[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
}

/** 動的なログ(到着が 0 より後のタスクがある)のときだけ出す、盤面の凡例。盤面にはテキストを描かない。 */
export const ARRIVAL_LEGEND = "薄い点線の丸: まだ現れていないタスク(到着前)";

function scenarioSummary({ scenario }: Log): string {
  return (
    `シード ${scenario.seed} ・ 格子 ${scenario.width}×${scenario.height} ・ ` +
    `ロボット ${scenario.robots.length} 台 ・ タスク ${scenario.tasks.length} 件`
  );
}

/** 1つのログの表示部品(盤面・ロボットの表・指標)。ids は 1画面のときだけ空の接尾辞、比較では -a / -b。 */
interface Panel {
  replay: Replay;
  summary: HTMLElement;
  board: HTMLElement;
  robotsSection: HTMLElement;
  metricsSection: HTMLElement;
  /** 時刻 t の状態に更新する。t が完了時間を超えても、完了した状態で止まる。 */
  update(t: number): void;
}

function createPanel(log: Log, suffix: string, heading: "h2" | "h3"): Panel {
  const replay = new Replay(log);
  const board = createBoard(replay);
  board.svg.id = `board${suffix}`;
  const { scenario, metrics } = log;

  const summary = h(
    "p",
    { id: `summary${suffix}`, class: "summary" },
    `ソルバ ${log.solver.name} ・ ${scenarioSummary(log)}`,
  );

  const rows = new Map<string, { activity: HTMLElement; task: HTMLElement }>();
  const tbody = h("tbody");
  scenario.robots.forEach((robot, index) => {
    const swatch = h("span", { class: "swatch", style: `background:${robotColor(index)}` });
    const activity = h("td", { "data-field": "activity" });
    const task = h("td", { "data-field": "task" });
    rows.set(robot.id, { activity, task });
    tbody.append(
      h(
        "tr",
        { "data-robot": robot.id },
        h("th", { scope: "row" }, swatch, robot.id),
        h("td", {}, KIND_LABEL[robot.kind] ?? robot.kind),
        activity,
        task,
        h("td", { "data-field": "finish" }, String(metrics.perRobot[robot.id]?.finish ?? "—")),
      ),
    );
  });
  const robotTable = h(
    "table",
    { id: `robots${suffix}` },
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        ...["ロボット", "種別", "状態", "タスク", "完了時刻"].map((c) => h("th", { scope: "col" }, c)),
      ),
    ),
    tbody,
  );

  // 指標はログに書かれた値。稼働率は分子・分母から計算して表示する。
  const metric = (name: string, label: string, value: string): HTMLElement[] => [
    h("dt", {}, label),
    h("dd", { "data-metric": name }, value),
  ];
  const metricList = h(
    "dl",
    { id: `metrics${suffix}` },
    ...metric("makespan", "完了時間", `${metrics.makespan} ティック`),
    ...metric("total_distance", "総移動距離", String(metrics.totalDistance)),
    ...metric("utilization", "稼働率", utilizationText(metrics)),
  );

  function update(t: number): void {
    board.update(t);
    for (const robot of scenario.robots) {
      const state = replay.robotStateAt(robot.id, t);
      const row = rows.get(robot.id);
      if (row !== undefined) {
        row.activity.textContent = ACTIVITY_LABEL[state.activity];
        row.task.textContent = state.taskId ?? "—";
      }
    }
  }

  return {
    replay,
    summary,
    board: h(
      "div",
      { class: "board-wrap" },
      board.svg,
      ...(replay.isDynamic
        ? [h("p", { class: "legend", "data-legend": "arrival" }, ARRIVAL_LEGEND)]
        : []),
    ),
    robotsSection: h("section", {}, h(heading, {}, "ロボット"), robotTable),
    metricsSection: h("section", {}, h(heading, {}, "指標"), metricList),
    update,
  };
}

/** 共通の操作部(再生・スライダー・時刻・速度)。時刻は1つだけで、全パネルが共有する。 */
function createControls(end: number): {
  element: HTMLElement;
  playButton: HTMLElement;
  slider: HTMLInputElement;
  clock: HTMLElement;
  speed: HTMLSelectElement;
} {
  const playButton = h("button", { id: "play", type: "button" }, "再生");
  const slider = h("input", {
    id: "time",
    type: "range",
    min: "0",
    max: String(end),
    step: "0.01",
    value: "0",
    "aria-label": "時刻",
  });
  const clock = h("output", { id: "clock", for: "time" }, "");
  const speed = h(
    "select",
    { id: "speed", "aria-label": "再生速度" },
    ...SPEEDS.map((s) => h("option", { value: String(s) }, `${s}x`)),
  );
  const element = h("section", { class: "controls" }, playButton, slider, clock, h("label", {}, "速度 ", speed));
  return { element, playButton, slider, clock, speed };
}

/** 比較表。優劣の印は表示上の慣習で、どのソルバが良いかの結論ではない(ADR-0006)。 */
function createComparisonTable(rows: MetricRow[], nameA: string, nameB: string): HTMLElement {
  const cell = (row: MetricRow, side: "a" | "b"): HTMLElement =>
    h(
      "td",
      { "data-cell": side, ...(row.better === side ? { "data-better": "true" } : {}) },
      row[side],
      ...(row.better === side ? [h("span", { class: "mark" }, " ◎")] : []),
    );
  return h(
    "section",
    {},
    h("h2", {}, "指標の比較"),
    h(
      "table",
      { id: "comparison" },
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          h("th", { scope: "col" }, "指標"),
          h("th", { scope: "col" }, `A: ${nameA}`),
          h("th", { scope: "col" }, `B: ${nameB}`),
          h("th", { scope: "col" }, "差(B − A)"),
        ),
      ),
      h(
        "tbody",
        {},
        ...rows.map((row) =>
          h(
            "tr",
            { "data-metric": row.name, ...(row.better === null ? {} : { "data-better-side": row.better }) },
            h("th", { scope: "row" }, row.label),
            cell(row, "a"),
            cell(row, "b"),
            h("td", { "data-cell": "diff" }, row.diff),
          ),
        ),
      ),
    ),
    h(
      "p",
      { class: "note" },
      "◎ は小さいほう(稼働率は大きいほう)。1シナリオの結果であり、ソルバの優劣の結論ではない。",
    ),
  );
}

function createExamples(examples: Example[]): HTMLElement | null {
  if (examples.length === 0) {
    return null;
  }
  return h(
    "nav",
    { id: "examples", "aria-label": "比較の例" },
    h("h2", {}, "比較の例"),
    h(
      "ul",
      {},
      ...examples.map((e) => h("li", {}, h("a", { href: compareHref(e) }, e.title))),
    ),
  );
}

export interface MountOptions {
  /** 比較の例(manifest.json)。空ならリンクを出さない */
  examples?: Example[];
}

/** 1つのログならリプレイ、2つなら同期した2画面比較。 */
export function mountApp(root: HTMLElement, logs: Log[], options: MountOptions = {}): void {
  const [logA, logB] = logs;
  if (logA === undefined || logs.length > 2) {
    throw new Error(`ログは1つか2つ指定する(指定: ${logs.length})`);
  }
  const compare = logB !== undefined;
  if (compare) {
    const mismatch = scenarioMismatch(logA.scenario, logB.scenario);
    if (mismatch !== null) {
      throw new Error(mismatch);
    }
  }

  const panels = compare
    ? [createPanel(logA, "-a", "h3"), createPanel(logB, "-b", "h3")]
    : [createPanel(logA, "", "h2")];
  const end = Math.max(...panels.map((p) => p.replay.makespan));
  const player = new Player(end);
  const controls = createControls(end);
  const { playButton, slider, clock, speed } = controls;
  const examples = createExamples(options.examples ?? []);

  const first = panels[0] as Panel;
  const second = panels[1];
  if (second === undefined) {
    root.replaceChildren(
      h(
        "main",
        { class: "app" },
        h("header", {}, h("h1", {}, "mrta viewer"), first.summary),
        first.board,
        controls.element,
        first.robotsSection,
        first.metricsSection,
        ...(examples === null ? [] : [examples]),
      ),
    );
  } else {
    const panel = (p: Panel, label: string, name: string): HTMLElement =>
      h(
        "section",
        { class: "panel", "data-panel": label.toLowerCase() },
        h("h2", {}, `${label}: ${name}`),
        p.board,
        p.robotsSection,
      );
    const rows = compareMetrics(first.replay.log.metrics, second.replay.log.metrics);
    root.replaceChildren(
      h(
        "main",
        { class: "app app-compare" },
        // 比較の前提は同じシナリオなので、概要は1回だけ出す(ソルバ名は各パネルの見出し)。
        h(
          "header",
          {},
          h("h1", {}, "mrta viewer"),
          h("p", { id: "summary", class: "summary" }, scenarioSummary(first.replay.log)),
        ),
        h(
          "div",
          { class: "panels" },
          panel(first, "A", first.replay.log.solver.name),
          panel(second, "B", second.replay.log.solver.name),
        ),
        controls.element,
        createComparisonTable(rows, first.replay.log.solver.name, second.replay.log.solver.name),
        ...(examples === null ? [] : [examples]),
      ),
    );
  }

  // --- 描画の更新 ---
  function render(): void {
    for (const p of panels) {
      p.update(player.t);
    }
    slider.value = String(player.t);
    clock.textContent = `${player.t.toFixed(2)} / ${end}`;
    playButton.textContent = player.playing
      ? "一時停止"
      : player.t >= end && end > 0
        ? "もう一度"
        : "再生";
  }

  let last: number | null = null;
  function frame(timestamp: number): void {
    if (last !== null) {
      player.advance(frameSeconds(last, timestamp));
    }
    last = timestamp;
    render();
    if (player.playing) {
      requestAnimationFrame(frame);
    } else {
      last = null;
    }
  }

  playButton.addEventListener("click", () => {
    if (player.playing) {
      player.pause();
      render();
      return;
    }
    player.play();
    last = null;
    render();
    if (player.playing) {
      requestAnimationFrame(frame);
    }
  });
  slider.addEventListener("input", () => {
    player.seek(Number(slider.value));
    render();
  });
  speed.addEventListener("change", () => {
    player.setSpeed(Number(speed.value));
  });

  render();
}
