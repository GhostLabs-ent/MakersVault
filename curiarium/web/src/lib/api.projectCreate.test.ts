// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { UnauthorizedError, createProject } from "./api";

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

const created = {
  id: "p9",
  name: "Hydra",
  description: null,
  creator: null,
  source_url: null,
  licence: null,
  licence_url: null,
  origin: "own",
  cover_asset_id: null,
  cover_thumb_url: null,
  asset_count: 0,
  metadata_json: {},
  total_size: 0,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("createProject API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts one create request and parses the 201 response", async () => {
    const fetchMock = installFetch(respond(created, { status: 201 }));

    await expect(createProject({ name: "Hydra" })).resolves.toEqual(created);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/projects")).toBe(true);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ name: "Hydra" });
  });

  it("surfaces the server detail on a 403", async () => {
    installFetch(
      respond(null, {
        ok: false,
        status: 403,
        body: JSON.stringify({ detail: "Editor or administrator access required" }),
      }),
    );

    const error = await createProject({ name: "Hydra" }).catch((err: unknown) => err);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("Editor or administrator access required");
  });

  it("throws UnauthorizedError on 401", async () => {
    installFetch(respond(null, { ok: false, status: 401, body: "" }));

    await expect(createProject({ name: "Hydra" })).rejects.toBeInstanceOf(UnauthorizedError);
  });
});
