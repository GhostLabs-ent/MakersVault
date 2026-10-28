// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { UnauthorizedError, getImportRun, getImportRuns } from "./api";
import { storeToken } from "./auth";

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

const runSummary = {
  id: "run-1",
  status: "succeeded",
  mode: "copy",
  root: "/mnt/models",
  reason: null,
  started_at: 1_700_000_000,
  finished_at: 1_700_000_042,
  registered: 4,
  known: 2,
  ignored: 1,
  failed: 0,
  rejected: 0,
  discovered: 7,
  skipped: 3,
};

const runList = { runs: [runSummary], total: 1, limit: 20, offset: 0 };
const runDetail = { ...runSummary, errors: ["broken.stl: unreadable"] };

describe("getImportRuns API client", () => {
  beforeEach(() => {
    installMemoryStorage();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests the newest runs with the default paging and parses the page", async () => {
    const fetchMock = installFetch(respond(runList));

    await expect(getImportRuns()).resolves.toEqual(runList);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/imports/runs?limit=20&offset=0")).toBe(true);
    expect(init.method).toBeUndefined();
  });

  it("encodes a custom limit and offset", async () => {
    const fetchMock = installFetch(respond(runList));

    await getImportRuns(5, 40);

    const { url } = onlyCall(fetchMock);
    expect(url.endsWith("/imports/runs?limit=5&offset=40")).toBe(true);
  });

  it("sends the bearer token like the other read endpoints", async () => {
    storeToken("token-1");
    const fetchMock = installFetch(respond(runList));

    await getImportRuns();

    const { init } = onlyCall(fetchMock);
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer token-1");
  });

  it("throws UnauthorizedError on 401", async () => {
    installFetch(respond(null, { ok: false, status: 401, body: "" }));

    await expect(getImportRuns()).rejects.toBeInstanceOf(UnauthorizedError);
  });

  it("surfaces the server detail on a failing read", async () => {
    installFetch(
      respond(null, {
        ok: false,
        status: 500,
        body: JSON.stringify({ detail: "Run history is unavailable" }),
      }),
    );

    const error = await getImportRuns().catch((err: unknown) => err);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("Run history is unavailable");
  });
});

describe("getImportRun API client", () => {
  beforeEach(() => {
    installMemoryStorage();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches one run by id and parses its errors", async () => {
    const fetchMock = installFetch(respond(runDetail));

    await expect(getImportRun("run-1")).resolves.toEqual(runDetail);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/imports/runs/run-1")).toBe(true);
    expect(new Headers(init.headers).get("Authorization")).toBeNull();
  });

  it("percent-encodes the run id", async () => {
    const fetchMock = installFetch(respond(runDetail));

    await getImportRun("run/../1 2");

    const { url } = onlyCall(fetchMock);
    expect(url.endsWith("/imports/runs/run%2F..%2F1%202")).toBe(true);
  });

  it("propagates the 404 detail", async () => {
    installFetch(
      respond(null, {
        ok: false,
        status: 404,
        body: JSON.stringify({ detail: "Import run not found" }),
      }),
    );

    const error = await getImportRun("missing").catch((err: unknown) => err);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("Import run not found");
  });
});
