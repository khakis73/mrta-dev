import { describe, expect, it } from "vitest";
import { MAX_FRAME_SECONDS, Player, TICKS_PER_SECOND, frameSeconds } from "./player";

describe("Player", () => {
  it("再生中だけ、実時間 × 基本速度 × 倍率で進む", () => {
    const p = new Player(100);
    p.advance(1);
    expect(p.t).toBe(0); // 再生していないので進まない
    p.play();
    p.advance(1);
    expect(p.t).toBe(TICKS_PER_SECOND);
    p.setSpeed(4);
    p.advance(0.5);
    expect(p.t).toBe(TICKS_PER_SECOND + 0.5 * TICKS_PER_SECOND * 4);
  });

  it("終端に着いたら止まり、終端を超えない", () => {
    const p = new Player(5);
    p.play();
    p.advance(100);
    expect(p.t).toBe(5);
    expect(p.playing).toBe(false);
  });

  it("終端で再生すると、先頭からやり直す", () => {
    const p = new Player(5);
    p.seek(5);
    p.play();
    expect(p.t).toBe(0);
    expect(p.playing).toBe(true);
  });

  it("seek は範囲に丸める。一時停止すると進まない", () => {
    const p = new Player(10);
    p.seek(-3);
    expect(p.t).toBe(0);
    p.seek(99);
    expect(p.t).toBe(10);
    p.seek(4);
    p.play();
    p.pause();
    p.advance(10);
    expect(p.t).toBe(4);
  });

  it("長さ0のログは再生できない", () => {
    const p = new Player(0);
    p.play();
    expect(p.playing).toBe(false);
  });

  it.each([0, -1, Number.NaN, Number.POSITIVE_INFINITY])("不正な速度 %s を拒否する", (speed) => {
    expect(() => new Player(10).setSpeed(speed)).toThrow(RangeError);
  });
});

describe("frameSeconds", () => {
  it("通常のフレーム間隔は、そのまま秒にする", () => {
    expect(frameSeconds(1000, 1016)).toBeCloseTo(0.016);
  });

  it("タブが裏に回った後の長い間隔は、上限で切る(終端まで飛ばない)", () => {
    expect(frameSeconds(0, 60_000)).toBe(MAX_FRAME_SECONDS);
  });

  it("時刻が戻っても負にしない", () => {
    expect(frameSeconds(1000, 900)).toBe(0);
  });
});
