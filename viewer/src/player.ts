// 再生の状態(時刻・再生中か・速度)。DOM に依存しない純粋なクラスで、単体でテストできる。

/** 速度 1x のとき、1秒あたりに進むティック数。 */
export const TICKS_PER_SECOND = 2;

/**
 * 1フレームで進める実時間の上限(秒)。タブが裏に回ると requestAnimationFrame が止まり、
 * 戻ったときの経過時間がまとめて加算されて終端まで飛ぶのを防ぐ。
 */
export const MAX_FRAME_SECONDS = 0.1;

/** 2つのフレームの時刻(ミリ秒)から、進める実時間(秒)を返す。0 以上 MAX_FRAME_SECONDS 以下。 */
export function frameSeconds(prevMs: number, nowMs: number): number {
  return Math.min(Math.max((nowMs - prevMs) / 1000, 0), MAX_FRAME_SECONDS);
}

export class Player {
  /** 現在の時刻(ティック。小数を含む)。0 以上 end 以下。 */
  t = 0;
  playing = false;
  speed = 1;

  constructor(readonly end: number) {}

  seek(t: number): void {
    this.t = Math.min(Math.max(t, 0), this.end);
  }

  /** 終端にいるときの再生は、先頭からやり直す。長さ0のログは再生できない。 */
  play(): void {
    if (this.end === 0) {
      return;
    }
    if (this.t >= this.end) {
      this.t = 0;
    }
    this.playing = true;
  }

  pause(): void {
    this.playing = false;
  }

  setSpeed(speed: number): void {
    if (!Number.isFinite(speed) || speed <= 0) {
      throw new RangeError(`速度は正の数でなければならない: ${speed}`);
    }
    this.speed = speed;
  }

  /** dtSeconds(実時間の秒)だけ時刻を進める。終端に着いたら止まる。 */
  advance(dtSeconds: number): void {
    if (!this.playing) {
      return;
    }
    this.t = Math.min(this.end, this.t + dtSeconds * TICKS_PER_SECOND * this.speed);
    if (this.t >= this.end) {
      this.playing = false;
    }
  }
}
