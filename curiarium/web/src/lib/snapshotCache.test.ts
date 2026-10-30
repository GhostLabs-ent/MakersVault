import { describe, expect, it } from "vitest";

import {
  SNAPSHOT_CACHE_MAX_BYTES,
  SNAPSHOT_CACHE_MAX_ENTRIES,
  SnapshotCache,
  snapshotEntryBytes,
} from "./snapshotCache";

/** A string of `chars` UTF-16 units, i.e. `2 * chars` cached bytes. */
function payload(chars: number): string {
  return "x".repeat(chars);
}

describe("snapshotEntryBytes", () => {
  it("charges two bytes per UTF-16 unit of the data URL", () => {
    expect(snapshotEntryBytes("")).toBe(0);
    expect(snapshotEntryBytes("abc")).toBe(6);
    expect(snapshotEntryBytes(payload(50))).toBe(100);
  });
});

describe("SnapshotCache byte budget", () => {
  it("never exceeds maxBytes and evicts the oldest entries", () => {
    const cache = new SnapshotCache({ maxBytes: 1000, maxEntries: 100 });

    for (let i = 0; i < 10; i += 1) {
      expect(cache.set(`key-${i}`, payload(100))).toBe(true);
      expect(cache.bytes()).toBeLessThanOrEqual(1000);
    }

    expect(cache.size()).toBe(5);
    expect(cache.bytes()).toBe(1000);
    expect(cache.has("key-0")).toBe(false);
    expect(cache.has("key-4")).toBe(false);
    expect(cache.has("key-5")).toBe(true);
    expect(cache.has("key-9")).toBe(true);
  });

  it("replaces an existing entry without double-counting its bytes", () => {
    const cache = new SnapshotCache({ maxBytes: 1000, maxEntries: 10 });

    cache.set("key", payload(100));
    cache.set("key", payload(200));

    expect(cache.size()).toBe(1);
    expect(cache.bytes()).toBe(400);
    expect(cache.get("key")).toBe(payload(200));
  });
});

describe("SnapshotCache entry cap", () => {
  it("keeps only the most recent entries when maxEntries is exceeded", () => {
    const cache = new SnapshotCache({ maxBytes: 1_000_000, maxEntries: 3 });

    for (let i = 0; i < 10; i += 1) {
      cache.set(`key-${i}`, payload(10));
    }

    expect(cache.size()).toBe(3);
    expect(cache.has("key-6")).toBe(false);
    expect(cache.has("key-7")).toBe(true);
    expect(cache.has("key-8")).toBe(true);
    expect(cache.has("key-9")).toBe(true);
  });
});

describe("SnapshotCache oversize refusal", () => {
  it("refuses an entry larger than the whole budget instead of flushing the cache", () => {
    const cache = new SnapshotCache({ maxBytes: 100, maxEntries: 10 });
    cache.set("small-a", payload(10));
    cache.set("small-b", payload(10));

    const beforeSize = cache.size();
    const beforeBytes = cache.bytes();
    const admitted = cache.set("huge", payload(200));

    expect(admitted).toBe(false);
    expect(cache.size()).toBe(beforeSize);
    expect(cache.bytes()).toBe(beforeBytes);
    expect(cache.has("huge")).toBe(false);
    expect(cache.get("small-a")).toBe(payload(10));
    expect(cache.get("small-b")).toBe(payload(10));
  });

  it("refuses everything when the entry budget is zero", () => {
    const cache = new SnapshotCache({ maxBytes: 100, maxEntries: 0 });

    expect(cache.set("key", payload(1))).toBe(false);
    expect(cache.size()).toBe(0);
    expect(cache.bytes()).toBe(0);
  });
});

describe("SnapshotCache LRU order", () => {
  it("serves a touched key and evicts the untouched oldest one instead", () => {
    const cache = new SnapshotCache({ maxBytes: 1_000_000, maxEntries: 2 });
    cache.set("a", payload(10));
    cache.set("b", payload(10));

    expect(cache.get("a")).toBe(payload(10));
    cache.set("c", payload(10));

    expect(cache.has("a")).toBe(true);
    expect(cache.has("b")).toBe(false);
    expect(cache.has("c")).toBe(true);
  });

  it("returns undefined for a missing key", () => {
    const cache = new SnapshotCache();

    expect(cache.get("nope")).toBeUndefined();
  });

  it("clear() empties both size and bytes", () => {
    const cache = new SnapshotCache();
    cache.set("a", payload(10));
    cache.set("b", payload(20));

    cache.clear();

    expect(cache.size()).toBe(0);
    expect(cache.bytes()).toBe(0);
    expect(cache.get("a")).toBeUndefined();
  });

  it("delete() subtracts the entry's bytes", () => {
    const cache = new SnapshotCache();
    cache.set("a", payload(10));
    cache.set("b", payload(20));
    cache.delete("a");

    expect(cache.size()).toBe(1);
    expect(cache.bytes()).toBe(40);
  });
});

describe("SnapshotCache long-run bounds", () => {
  it("500 inserts of varying sizes never exceed the byte or entry bound", () => {
    const maxBytes = 5000;
    const maxEntries = 8;
    const cache = new SnapshotCache({ maxBytes, maxEntries });

    for (let i = 0; i < 500; i += 1) {
      // Sizes cycle so some entries are evicted for bytes and some for count.
      const chars = 1 + ((i * 37) % 400);
      cache.set(`key-${i}`, payload(chars));
      expect(cache.bytes()).toBeLessThanOrEqual(maxBytes);
      expect(cache.size()).toBeLessThanOrEqual(maxEntries);
    }
  });
});

describe("SnapshotCache defaults", () => {
  it("exposes the documented capacity constants", () => {
    expect(SNAPSHOT_CACHE_MAX_BYTES).toBe(8 * 1024 * 1024);
    expect(SNAPSHOT_CACHE_MAX_ENTRIES).toBe(32);
  });

  it("holds exactly 32 small entries with default options", () => {
    const cache = new SnapshotCache();

    for (let i = 0; i < 33; i += 1) {
      cache.set(`key-${i}`, payload(10));
    }

    expect(cache.size()).toBe(32);
    expect(cache.has("key-0")).toBe(false);
    expect(cache.has("key-32")).toBe(true);
  });
});
