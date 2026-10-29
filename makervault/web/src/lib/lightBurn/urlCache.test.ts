import { describe, expect, it } from "vitest";

import { LIGHTBURN_URL_CACHE_LIMIT, PreviewUrlCache } from "./urlCache";

type Harness = {
  cache: PreviewUrlCache;
  revoked: string[];
  created: string[];
  acquire: (key: string) => { url: string; release: () => void };
};

function harness(limit: number): Harness {
  const revoked: string[] = [];
  const created: string[] = [];
  let sequence = 0;
  const cache = new PreviewUrlCache(limit, () => "", url => revoked.push(url));
  const acquire = (key: string) =>
    cache.acquire(key, () => {
      sequence += 1;
      const url = `${key}-${sequence}`;
      created.push(url);
      return url;
    });
  return { cache, revoked, created, acquire };
}

describe("PreviewUrlCache", () => {
  it("evicts the least-recently-used unreferenced entry and revokes it", () => {
    const { cache, revoked, acquire } = harness(2);

    const a = acquire("a");
    a.release();
    const b = acquire("b");
    b.release();
    acquire("c");

    expect(cache.size()).toBe(2);
    expect(revoked).toEqual([a.url]);

    const fresh = acquire("a");
    expect(fresh.url).not.toBe(a.url);
    expect(revoked).toContain(b.url);
    expect(cache.size()).toBe(2);
  });

  it("touches on acquire", () => {
    const { cache, revoked, acquire } = harness(2);

    const a = acquire("a");
    a.release();
    const b = acquire("b");
    b.release();
    const again = acquire("a");
    expect(again.url).toBe(a.url);
    again.release();

    acquire("c");

    expect(revoked).toEqual([b.url]);
    expect(revoked).not.toContain(a.url);
    expect(cache.size()).toBe(2);
  });

  it("allows a temporary overshoot and honours pending revokes", () => {
    const { cache, revoked, acquire } = harness(1);

    const firstA = acquire("a");
    const b = acquire("b");
    expect(cache.size()).toBe(2);

    const secondA = acquire("a");
    expect(secondA.url).not.toBe(firstA.url);
    expect(secondA.url).not.toBe(b.url);

    firstA.release();
    expect(revoked).toEqual([firstA.url]);

    b.release();
    expect(revoked).toContain(b.url);
    expect(new Set(revoked).size).toBe(revoked.length);

    secondA.release();
    acquire("c");
    expect(cache.size()).toBe(1);
  });

  it("never re-serves an evicted or marked entry", () => {
    const { created, acquire } = harness(1);

    const first = acquire("a");
    acquire("b");
    const second = acquire("a");

    expect(second.url).not.toBe(first.url);
    expect(created).toHaveLength(3);
    expect(created.filter(url => url.startsWith("a-"))).toHaveLength(2);
  });

  it("makes release idempotent and never revokes one URL twice", () => {
    const { cache, revoked, acquire } = harness(2);

    const a = acquire("a");
    a.release();
    a.release();

    acquire("b");
    acquire("c");

    expect(revoked.filter(url => url === a.url)).toHaveLength(1);
    a.release();
    expect(revoked.filter(url => url === a.url)).toHaveLength(1);
    expect(cache.size()).toBe(2);
  });

  it("dispose revokes unreferenced entries and marks referenced ones", () => {
    const { cache, revoked, acquire } = harness(3);

    const a = acquire("a");
    const b = acquire("b");
    b.release();
    const c = acquire("c");

    cache.dispose();
    expect(cache.size()).toBe(0);
    expect(revoked).toEqual([b.url]);

    a.release();
    c.release();
    expect(revoked).toContain(a.url);
    expect(revoked).toContain(c.url);
    expect(new Set(revoked).size).toBe(revoked.length);

    cache.dispose();
    expect(revoked).toHaveLength(3);
  });

  it("exports the default cache limit", () => {
    expect(LIGHTBURN_URL_CACHE_LIMIT).toBe(8);
  });
});
