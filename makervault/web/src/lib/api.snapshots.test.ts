// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  UnauthorizedError,
  browseSnapshot,
  deleteSnapshot,
  getSnapshotRetention,
  listSnapshots,
  restoreSnapshot,
  takeSnapshot,
  updateSnapshotRetention,
  type SnapshotRetention,
} from "./api";

type MockResponse = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
  text: () => Promise<string>;
  headers: Headers;
};

type MockFetch = ReturnType<typeof vi.fn<(input: string, init?: RequestInit) => Promise<MockResponse>>>;

function respond(
  payload: unknown,
  init: { ok?: boolean; status?: number; body?: string } = {},
): MockResponse {
  const body = init.body ?? JSON.stringify(payload);
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    json: async () => payload,
    text: async () => body,
    headers: new Headers(),
  };
}

function installFetch(response: MockResponse): MockFetch {
  const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<MockResponse>>(
    async () => response,
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function onlyCall(fetchMock: MockFetch): { url: string; init: RequestInit } {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0];
  if (!init) throw new Error("fetch was called without an init object");
  return { url, init };
}

/** jsdom's localStorage can resolve to `undefined` under Node's global; install a real one. */
function installMemoryStorage(): void {
  const store = new Map<string, string>();
  const storage: Storage = {
    get length(): number {
      return store.size;
    },
    clear(): void {
      store.clear();
    },
    getItem(key: string): string | null {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number): string | null {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string): void {
      store.delete(key);
    },
    setItem(key: string, value: string): void {
      store.set(key, String(value));
    },
  };
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
}

const snapshot = {
  name: "snap-1",
  created_at: "2024-01-01T00:00:00Z",
  age_seconds: 120,
  reason: "manual",
};

const snapshotList = {
  snapshots: [snapshot],
  method: "cephfs_snapdir",
  supports_browse: true,
  supports_restore: true,
};

const retention: SnapshotRetention = {
  keep_last_n: 5,
  keep_daily: 7,
  max_age_days: 30,
  hard_cap: 20,
};

const created = {
  snapshot,
  prune: { pruned: 2, kept: 5, names: ["snap-0", "snap--1"] },
};

const browse = {
  snapshot: "snap-1",
  path: "Props",
  entries: [
    { name: "Cable clip", path: "Props/Cable clip", is_dir: true, size: null, modified_at: null },
    { name: "readme.txt", path: "Props/readme.txt", is_dir: false, size: 42, modified_at: null },
  ],
};

const restored = {
  snapshot: "snap-1",
  path: "Props/readme.txt",
  destination: "/srv/makervault/library/Props/readme.txt",
  files: 1,
  bytes: 42,
  scan_started: true,
};

const deleted = { ok: true, name: "snap-1" };

describe("snapshot API client", () => {
  beforeEach(() => {
    installMemoryStorage();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists snapshots with a GET and parses the payload", async () => {
    const fetchMock = installFetch(respond(snapshotList));

    await expect(listSnapshots()).resolves.toEqual(snapshotList);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/snapshots")).toBe(true);
    expect(init.method).toBeUndefined();
  });

  it("takes a snapshot with a POST that carries no body and no content type", async () => {
    const fetchMock = installFetch(respond(created, { status: 201 }));

    await expect(takeSnapshot()).resolves.toEqual(created);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/snapshots")).toBe(true);
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
    expect(new Headers(init.headers).get("Content-Type")).toBeNull();
  });

  it("reads and writes the retention policy, echoing all four fields", async () => {
    const readMock = installFetch(respond(retention));
    await expect(getSnapshotRetention()).resolves.toEqual(retention);
    const read = onlyCall(readMock);
    expect(read.url.endsWith("/snapshots/retention")).toBe(true);
    expect(read.init.method).toBeUndefined();

    vi.unstubAllGlobals();
    const writeMock = installFetch(respond(retention));
    await expect(updateSnapshotRetention(retention)).resolves.toEqual(retention);
    const write = onlyCall(writeMock);
    expect(write.init.method).toBe("POST");
    expect(JSON.parse(String(write.init.body))).toEqual({
      keep_last_n: 5,
      keep_daily: 7,
      max_age_days: 30,
      hard_cap: 20,
    });
  });

  it("encodes the snapshot name and the nested browse path", async () => {
    const fetchMock = installFetch(respond(browse));

    await expect(browseSnapshot("snap-1", "Props/Cable clip")).resolves.toEqual(browse);

    const { url } = onlyCall(fetchMock);
    expect(url.endsWith("/snapshots/snap-1/browse?path=Props%2FCable+clip")).toBe(true);
  });

  it("posts the restore path and percent-encodes the snapshot name", async () => {
    const fetchMock = installFetch(respond(restored, { status: 201 }));

    await expect(restoreSnapshot("snap/../1 2", "Props/Cable clip.3mf")).resolves.toEqual(
      restored,
    );

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/snapshots/snap%2F..%2F1%202/restore")).toBe(true);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ path: "Props/Cable clip.3mf" });
  });

  it("deletes a snapshot with DELETE", async () => {
    const fetchMock = installFetch(respond(deleted));

    await expect(deleteSnapshot("snap-1")).resolves.toEqual(deleted);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/snapshots/snap-1")).toBe(true);
    expect(init.method).toBe("DELETE");
  });

  it("throws UnauthorizedError on a 401 from the list and the take", async () => {
    installFetch(respond(null, { ok: false, status: 401, body: "" }));
    await expect(listSnapshots()).rejects.toBeInstanceOf(UnauthorizedError);

    vi.unstubAllGlobals();
    installFetch(respond(null, { ok: false, status: 401, body: "" }));
    await expect(takeSnapshot()).rejects.toBeInstanceOf(UnauthorizedError);
  });

  it("surfaces the server detail verbatim on a rejected retention update", async () => {
    installFetch(
      respond(null, {
        ok: false,
        status: 400,
        body: JSON.stringify({ detail: "keep_last_n must not exceed hard_cap" }),
      }),
    );

    const error = await updateSnapshotRetention(retention).catch((err: unknown) => err);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("keep_last_n must not exceed hard_cap");
  });
});
