/**
 * Bounded LRU of rendered preview snapshots (data URLs).
 *
 * Previews are expensive to produce but tiny to keep: a card that scrolls back
 * into view should be served from memory rather than queued behind the (single)
 * preview slot again. The bound that actually matters is BYTES, not entries:
 * one 4K snapshot can weigh more than dozens of thumbnails, so an entry count
 * alone cannot keep the cache from hoarding tens of megabytes.
 */

/**
 * Byte budget for cached snapshots. The real bound on retained memory.
 */
export const SNAPSHOT_CACHE_MAX_BYTES = 8 * 1024 * 1024;

/**
 * Entry cap. A coarse second bound so a flood of tiny images cannot turn the
 * cache into a long-lived leak of small entries.
 */
export const SNAPSHOT_CACHE_MAX_ENTRIES = 32;

/**
 * Conservative cost of one cached snapshot: a data URL lives as a JS string, so
 * charging 2 bytes per UTF-16 code unit is an upper bound on what it retains.
 * A V8 one-byte string may hold a base64 payload in half that, but a memory
 * budget must never undercount. The decoded PNG size would understate the
 * retained memory far more.
 */
export function snapshotEntryBytes(value: string): number {
  return value.length * 2;
}

type SnapshotEntry = {
  value: string;
  bytes: number;
};

export type SnapshotCacheOptions = {
  maxBytes?: number;
  maxEntries?: number;
};

export class SnapshotCache {
  private readonly maxBytes: number;
  private readonly maxEntries: number;
  /** Map insertion order IS the LRU order: oldest first. */
  private readonly entries = new Map<string, SnapshotEntry>();
  private bytesUsed = 0;

  constructor(options: SnapshotCacheOptions = {}) {
    this.maxBytes = Math.max(0, Math.trunc(options.maxBytes ?? SNAPSHOT_CACHE_MAX_BYTES));
    this.maxEntries = Math.max(0, Math.trunc(options.maxEntries ?? SNAPSHOT_CACHE_MAX_ENTRIES));
  }

  /** Returns the cached value and marks it as most recently used. */
  get(key: string): string | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    this.entries.delete(key);
    this.entries.set(key, entry);
    return entry.value;
  }

  /**
   * Stores `value` and returns whether it was admitted.
   *
   * An entry larger than the whole budget is REFUSED rather than inserted:
   * admitting it would evict every other snapshot just to hold one image, so
   * one oversized preview would flush the entire working set.
   */
  set(key: string, value: string): boolean {
    const bytes = snapshotEntryBytes(value);
    if (bytes > this.maxBytes || this.maxEntries === 0) return false;

    const existing = this.entries.get(key);
    if (existing) {
      this.entries.delete(key);
      this.bytesUsed -= existing.bytes;
    }

    // Evict before inserting so the fresh entry can never be its own victim.
    while (this.entries.size > 0 && this.isOverCapacity(bytes)) {
      const oldestKey = this.entries.keys().next().value;
      if (oldestKey === undefined) break;
      this.delete(oldestKey);
    }

    this.entries.set(key, { value, bytes });
    this.bytesUsed += bytes;
    return true;
  }

  /** Whether inserting one more entry of `bytes` would break either bound. */
  private isOverCapacity(bytes: number): boolean {
    return this.entries.size + 1 > this.maxEntries || this.bytesUsed + bytes > this.maxBytes;
  }

  /** Presence check that does not disturb the LRU order. */
  has(key: string): boolean {
    return this.entries.has(key);
  }

  delete(key: string): void {
    const entry = this.entries.get(key);
    if (!entry) return;
    this.entries.delete(key);
    this.bytesUsed -= entry.bytes;
  }

  clear(): void {
    this.entries.clear();
    this.bytesUsed = 0;
  }

  size(): number {
    return this.entries.size;
  }

  bytes(): number {
    return this.bytesUsed;
  }
}

/** The app-wide snapshot cache; snapshots are session-scoped, not persisted. */
export const snapshotCache = new SnapshotCache();
