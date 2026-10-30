export const LIGHTBURN_URL_CACHE_LIMIT = 8;

type CacheEntry = {
  url: string;
  refs: number;
  pendingRevoke: boolean;
  revoked: boolean;
};

type CacheHandle = { url: string; release: () => void };

export class PreviewUrlCache {
  private readonly limit: number;
  private readonly createObjectUrl: (blob: Blob) => string;
  private readonly revokeObjectUrl: (url: string) => void;
  private readonly entries = new Map<string, CacheEntry>();

  constructor(
    limit = LIGHTBURN_URL_CACHE_LIMIT,
    createObjectUrl: (blob: Blob) => string = blob => URL.createObjectURL(blob),
    revokeObjectUrl: (url: string) => void = url => URL.revokeObjectURL(url),
  ) {
    this.limit = Math.max(0, Math.trunc(limit));
    this.createObjectUrl = createObjectUrl;
    this.revokeObjectUrl = revokeObjectUrl;
  }

  acquire(key: string, create: () => string): CacheHandle {
    const existing = this.entries.get(key);
    if (existing && !existing.pendingRevoke) {
      existing.refs += 1;
      // Touch: reinsert to move the entry to the most-recently-used end.
      this.entries.delete(key);
      this.entries.set(key, existing);
      return this.handle(key, existing);
    }

    if (existing) {
      // A marked entry must never be served again. Detach it; its existing
      // holders keep the URL until they release, then it is revoked.
      this.entries.delete(key);
      existing.pendingRevoke = true;
      if (existing.refs === 0) this.revoke(existing);
    }

    const entry: CacheEntry = {
      url: create(),
      refs: 1,
      pendingRevoke: false,
      revoked: false,
    };
    this.entries.set(key, entry);
    this.enforceLimit();
    return this.handle(key, entry);
  }

  size(): number {
    return this.entries.size;
  }

  dispose(): void {
    for (const [key, entry] of this.entries) {
      this.entries.delete(key);
      if (entry.refs === 0) {
        this.revoke(entry);
      } else {
        entry.pendingRevoke = true;
      }
    }
  }

  private handle(key: string, entry: CacheEntry): CacheHandle {
    let released = false;
    const release = (): void => {
      if (released) return;
      released = true;
      if (entry.refs > 0) entry.refs -= 1;
      const tracked = this.entries.get(key) === entry;
      if (entry.refs === 0) {
        if (!tracked) {
          this.revoke(entry);
          return;
        }
        if (entry.pendingRevoke) {
          this.entries.delete(key);
          this.revoke(entry);
          return;
        }
      }
      if (tracked) this.enforceLimit();
    };
    return { url: entry.url, release };
  }

  private enforceLimit(): void {
    while (this.entries.size > this.limit) {
      let evicted = false;
      for (const [key, entry] of this.entries) {
        if (entry.refs === 0) {
          this.entries.delete(key);
          this.revoke(entry);
          evicted = true;
          break;
        }
      }
      if (!evicted) {
        // Everything left is mounted. Allow a temporary overshoot and mark the
        // oldest entry so it is revoked as soon as its last holder releases.
        const oldest = this.entries.values().next().value;
        if (!oldest) break;
        oldest.pendingRevoke = true;
        break;
      }
    }
  }

  private revoke(entry: CacheEntry): void {
    if (entry.revoked) return;
    entry.revoked = true;
    this.revokeObjectUrl(entry.url);
  }
}

export const lightBurnUrlCache = new PreviewUrlCache();
