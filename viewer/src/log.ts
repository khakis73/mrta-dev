// ログ(JSONL)の型と、読み込み・検証(ADR-0004 の「読む側」)。
//
// - 実行の意味(移動時間の丸めなど)は Python だけが持つ。ここはログの事実を読むだけで、再計算しない。
// - 未知のフィールドと、未知の type の行は無視する(後方互換な追加)。
// - 対応しない schema_version は、黙って誤表示せず、明示的なエラーにする。
// - 途中で切れたファイル(末尾が metrics でない、末尾の改行がない)は拒否する。

export const SUPPORTED_SCHEMA_VERSION = 1;

export type Point = readonly [number, number];

export interface Robot {
  id: string;
  kind: string;
  start: Point;
  speed: number;
  capacity: number;
  skills: string[];
}

export interface Task {
  id: string;
  location: Point;
  requiredSkill: string;
  demand: number;
  serviceTime: number;
}

export type SegmentKind = "move" | "service";

export interface Segment {
  robot: string;
  kind: SegmentKind;
  task: string;
  from: Point;
  to: Point;
  t0: number;
  t1: number;
}

export interface RobotMetrics {
  finish: number;
  distance: number;
  busy: number;
}

export interface Metrics {
  makespan: number;
  totalDistance: number;
  busyTotal: number;
  availableTotal: number;
  perRobot: Readonly<Record<string, RobotMetrics>>;
}

export interface Log {
  schemaVersion: number;
  scenario: {
    seed: number;
    width: number;
    height: number;
    robots: Robot[];
    tasks: Task[];
  };
  solver: { name: string; config: Readonly<Record<string, number | string | boolean>> };
  /** ロボットID → 実行順のタスクID */
  plan: Readonly<Record<string, string[]>>;
  segments: Segment[];
  metrics: Metrics;
}

export class LogError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LogError";
  }
}

type Obj = Record<string, unknown>;

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function field(obj: Obj, key: string, where: string): unknown {
  if (!(key in obj)) {
    throw new LogError(`${where}: 必須フィールド ${key} がない`);
  }
  return obj[key];
}

function int(v: unknown, where: string, minimum: number): number {
  if (typeof v !== "number" || !Number.isInteger(v)) {
    throw new LogError(`${where}: 整数でなければならない(${JSON.stringify(v)})`);
  }
  if (v < minimum) {
    throw new LogError(`${where}: ${minimum} 以上でなければならない(${v})`);
  }
  return v;
}

function str(v: unknown, where: string): string {
  if (typeof v !== "string" || v === "") {
    throw new LogError(`${where}: 空でない文字列でなければならない(${JSON.stringify(v)})`);
  }
  return v;
}

function point(v: unknown, where: string): Point {
  if (!Array.isArray(v) || v.length !== 2) {
    throw new LogError(`${where}: [x, y] でなければならない(${JSON.stringify(v)})`);
  }
  return [int(v[0], `${where}[0]`, 0), int(v[1], `${where}[1]`, 0)];
}

function array(v: unknown, where: string): unknown[] {
  if (!Array.isArray(v)) {
    throw new LogError(`${where}: 配列でなければならない`);
  }
  return v;
}

function object(v: unknown, where: string): Obj {
  if (!isObj(v)) {
    throw new LogError(`${where}: オブジェクトでなければならない`);
  }
  return v;
}

function parseRobot(v: unknown, i: number): Robot {
  const where = `scenario.robots[${i}]`;
  const o = object(v, where);
  return {
    id: str(field(o, "id", where), `${where}.id`),
    kind: str(field(o, "kind", where), `${where}.kind`),
    start: point(field(o, "start", where), `${where}.start`),
    speed: int(field(o, "speed", where), `${where}.speed`, 1),
    capacity: int(field(o, "capacity", where), `${where}.capacity`, 1),
    skills: array(field(o, "skills", where), `${where}.skills`).map((s, j) =>
      str(s, `${where}.skills[${j}]`),
    ),
  };
}

function parseTask(v: unknown, i: number): Task {
  const where = `scenario.tasks[${i}]`;
  const o = object(v, where);
  return {
    id: str(field(o, "id", where), `${where}.id`),
    location: point(field(o, "location", where), `${where}.location`),
    requiredSkill: str(field(o, "required_skill", where), `${where}.required_skill`),
    demand: int(field(o, "demand", where), `${where}.demand`, 1),
    serviceTime: int(field(o, "service_time", where), `${where}.service_time`, 0),
  };
}

function parseSegment(o: Obj, i: number): Segment {
  const where = `segment[${i}]`;
  const kind = field(o, "kind", where);
  if (kind !== "move" && kind !== "service") {
    throw new LogError(`${where}.kind: move か service でなければならない(${JSON.stringify(kind)})`);
  }
  const t0 = int(field(o, "t0", where), `${where}.t0`, 0);
  const t1 = int(field(o, "t1", where), `${where}.t1`, 0);
  if (t0 >= t1) {
    throw new LogError(`${where}: t0 < t1 でなければならない(長さ0の区間は書かない)`);
  }
  return {
    robot: str(field(o, "robot", where), `${where}.robot`),
    kind,
    task: str(field(o, "task", where), `${where}.task`),
    from: point(field(o, "from", where), `${where}.from`),
    to: point(field(o, "to", where), `${where}.to`),
    t0,
    t1,
  };
}

function parseMetrics(o: Obj): Metrics {
  const perRobot: Record<string, RobotMetrics> = {};
  for (const [id, v] of Object.entries(object(field(o, "per_robot", "metrics"), "metrics.per_robot"))) {
    const where = `metrics.per_robot.${id}`;
    const r = object(v, where);
    perRobot[id] = {
      finish: int(field(r, "finish", where), `${where}.finish`, 0),
      distance: int(field(r, "distance", where), `${where}.distance`, 0),
      busy: int(field(r, "busy", where), `${where}.busy`, 0),
    };
  }
  return {
    makespan: int(field(o, "makespan", "metrics"), "metrics.makespan", 0),
    totalDistance: int(field(o, "total_distance", "metrics"), "metrics.total_distance", 0),
    busyTotal: int(field(o, "busy_total", "metrics"), "metrics.busy_total", 0),
    availableTotal: int(field(o, "available_total", "metrics"), "metrics.available_total", 0),
    perRobot,
  };
}

/** 既知の行の並び: header, scenario, solver, plan, segment*, metrics */
const HEAD = ["header", "scenario", "solver", "plan"] as const;
const KNOWN = new Set<string>([...HEAD, "segment", "metrics"]);

export function parseLog(text: string): Log {
  if (!text.endsWith("\n")) {
    throw new LogError("ログの末尾が改行で終わっていない(途中で切れている可能性)");
  }

  const objs: Obj[] = [];
  for (const [i, raw] of text.slice(0, -1).split("\n").entries()) {
    if (raw === "") {
      throw new LogError(`${i + 1} 行目が空行`);
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new LogError(`${i + 1} 行目が JSON として不正`);
    }
    if (!isObj(parsed) || typeof parsed["type"] !== "string") {
      throw new LogError(`${i + 1} 行目が type を持つオブジェクトではない`);
    }
    objs.push(parsed);
  }

  // 版の確認を最優先する。対応しない版は、他の検証より先に、原因が分かるエラーにする。
  const first = objs[0];
  if (first === undefined || first["type"] !== "header") {
    throw new LogError("先頭の行が header ではない");
  }
  const version = int(field(first, "schema_version", "header"), "header.schema_version", 0);
  if (version !== SUPPORTED_SCHEMA_VERSION) {
    throw new LogError(
      `未対応のスキーマ版: ${version}(このビューアは ${SUPPORTED_SCHEMA_VERSION} のみ対応)`,
    );
  }

  if (objs[objs.length - 1]?.["type"] !== "metrics") {
    throw new LogError("末尾の行が metrics ではない(途中で切れている、または metrics の後ろに行がある)");
  }
  // 未知の type の行は無視する。既知の行だけで、並びを検査する。
  const known = objs.filter((o) => KNOWN.has(o["type"] as string));
  const types = known.map((o) => o["type"] as string);
  const middle = types.slice(HEAD.length, -1);
  if (
    HEAD.some((t, i) => types[i] !== t) ||
    types.length < HEAD.length + 1 ||
    middle.some((t) => t !== "segment")
  ) {
    throw new LogError(`行の並びが header, scenario, solver, plan, segment*, metrics ではない: ${types.join(", ")}`);
  }

  const [, scenarioLine, solverLine, planLine] = known as [Obj, Obj, Obj, Obj];
  const metricsLine = known[known.length - 1] as Obj;
  const segmentLines = known.slice(HEAD.length, -1);

  const solverConfig: Record<string, number | string | boolean> = {};
  for (const [k, v] of Object.entries(object(field(solverLine, "config", "solver"), "solver.config"))) {
    if (typeof v !== "number" && typeof v !== "string" && typeof v !== "boolean") {
      throw new LogError(`solver.config.${k}: 整数・文字列・真偽値でなければならない`);
    }
    solverConfig[k] = v;
  }

  const plan: Record<string, string[]> = {};
  for (const [id, v] of Object.entries(object(field(planLine, "routes", "plan"), "plan.routes"))) {
    plan[id] = array(v, `plan.routes.${id}`).map((t, j) => str(t, `plan.routes.${id}[${j}]`));
  }

  return {
    schemaVersion: version,
    scenario: {
      seed: int(field(scenarioLine, "seed", "scenario"), "scenario.seed", Number.MIN_SAFE_INTEGER),
      width: int(field(scenarioLine, "width", "scenario"), "scenario.width", 1),
      height: int(field(scenarioLine, "height", "scenario"), "scenario.height", 1),
      robots: array(field(scenarioLine, "robots", "scenario"), "scenario.robots").map(parseRobot),
      tasks: array(field(scenarioLine, "tasks", "scenario"), "scenario.tasks").map(parseTask),
    },
    solver: { name: str(field(solverLine, "name", "solver"), "solver.name"), config: solverConfig },
    plan,
    segments: segmentLines.map(parseSegment),
    metrics: parseMetrics(metricsLine),
  };
}
