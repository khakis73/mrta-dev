import { afterEach, describe, expect, it, vi } from "vitest";
import { loadText } from "./load";

const BASE = "https://khakis73.github.io/mrta-dev/";
const ORIGIN = "https://khakis73.github.io";

function stubFetch(response: Partial<Response> = { ok: true, status: 200 }) {
  const fn = vi.fn(async () => response as Response);
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("loadText: キャッシュ", () => {
  it("キャッシュを使わず、毎回サーバーに更新の有無を確認する(no-cache)", async () => {
    const fn = stubFetch();
    await loadText("data/manifest.json", BASE, ORIGIN);
    expect(fn).toHaveBeenCalledTimes(1);
    const [url, init] = fn.mock.calls[0] as unknown as [URL, RequestInit];
    expect(url.href).toBe("https://khakis73.github.io/mrta-dev/data/manifest.json");
    // GitHub Pages の max-age=600 のままだと、デプロイ直後の10分間、古い manifest・ログが使われる。
    expect(init.cache).toBe("no-cache");
  });

  it("ログにも同じ(マニフェストだけでなく、全ての取得)", async () => {
    const fn = stubFetch();
    await loadText("data/seed1-greedy.jsonl", BASE, ORIGIN);
    expect((fn.mock.calls[0] as unknown as [URL, RequestInit])[1].cache).toBe("no-cache");
  });
});

describe("loadText: 同じオリジンだけ(ADR-0004)", () => {
  it("相対パスと、同じオリジンの絶対 URL は読める", async () => {
    const fn = stubFetch();
    await loadText("data/a.jsonl", BASE, ORIGIN);
    await loadText("https://khakis73.github.io/mrta-dev/data/b.jsonl", BASE, ORIGIN);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it.each([
    "https://example.com/a.jsonl",
    "//example.com/a.jsonl",
    "http://khakis73.github.io/a.jsonl", // スキームが違う(別のオリジン)
    "https://khakis73.github.io:8443/a.jsonl", // ポートが違う
  ])("別のオリジンは、fetch を呼ぶ前に拒否する: %s", async (path) => {
    const fn = stubFetch();
    await expect(loadText(path, BASE, ORIGIN)).rejects.toThrow("同じオリジンのログだけ");
    expect(fn).not.toHaveBeenCalled();
  });
});

describe("loadText: 失敗", () => {
  it("HTTP エラーは、ステータスとパスつきのエラーにする", async () => {
    stubFetch({ ok: false, status: 404 });
    await expect(loadText("data/none.jsonl", BASE, ORIGIN)).rejects.toThrow(
      "ログを取得できなかった(HTTP 404): /mrta-dev/data/none.jsonl",
    );
  });

  it("ネットワークの失敗は、そのまま投げる", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(loadText("data/a.jsonl", BASE, ORIGIN)).rejects.toThrow("Failed to fetch");
  });
});
