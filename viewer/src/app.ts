// リプレイ画面の組み立てと操作。DOM は createElement と textContent だけで作る(innerHTML は使わない)。

import { createBoard, robotColor } from "./board";
import type { Log } from "./log";
import { Player } from "./player";
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

export function mountApp(root: HTMLElement, log: Log): void {
  const replay = new Replay(log);
  const player = new Player(replay.makespan);
  const board = createBoard(replay);
  const { scenario, metrics } = log;

  // --- ヘッダー ---
  const summary = h(
    "p",
    { id: "summary", class: "summary" },
    `ソルバ ${log.solver.name} ・ シード ${scenario.seed} ・ 格子 ${scenario.width}×${scenario.height} ・ ` +
      `ロボット ${scenario.robots.length} 台 ・ タスク ${scenario.tasks.length} 件`,
  );

  // --- 操作 ---
  const playButton = h("button", { id: "play", type: "button" }, "再生");
  const slider = h("input", {
    id: "time",
    type: "range",
    min: "0",
    max: String(replay.makespan),
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
  const controls = h(
    "section",
    { class: "controls" },
    playButton,
    slider,
    clock,
    h("label", {}, "速度 ", speed),
  );

  // --- ロボットの表 ---
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
    { id: "robots" },
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

  // --- 指標(ログに書かれた値。稼働率は分子・分母から計算して表示する) ---
  const metric = (name: string, label: string, value: string): HTMLElement[] => [
    h("dt", {}, label),
    h("dd", { "data-metric": name }, value),
  ];
  const metricList = h(
    "dl",
    { id: "metrics" },
    ...metric("makespan", "完了時間", `${metrics.makespan} ティック`),
    ...metric("total_distance", "総移動距離", String(metrics.totalDistance)),
    ...metric("utilization", "稼働率", utilizationText(metrics)),
  );

  root.replaceChildren(
    h(
      "main",
      { class: "app" },
      h("header", {}, h("h1", {}, "mrta viewer"), summary),
      h("div", { class: "board-wrap" }, board.svg),
      controls,
      h("section", {}, h("h2", {}, "ロボット"), robotTable),
      h("section", {}, h("h2", {}, "指標"), metricList),
    ),
  );

  // --- 描画の更新 ---
  function render(): void {
    board.update(player.t);
    slider.value = String(player.t);
    clock.textContent = `${player.t.toFixed(2)} / ${replay.makespan}`;
    playButton.textContent = player.playing
      ? "一時停止"
      : player.t >= replay.makespan && replay.makespan > 0
        ? "もう一度"
        : "再生";
    for (const robot of scenario.robots) {
      const state = replay.robotStateAt(robot.id, player.t);
      const row = rows.get(robot.id);
      if (row !== undefined) {
        row.activity.textContent = ACTIVITY_LABEL[state.activity];
        row.task.textContent = state.taskId ?? "—";
      }
    }
  }

  let last: number | null = null;
  function frame(timestamp: number): void {
    if (last !== null) {
      player.advance((timestamp - last) / 1000);
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
