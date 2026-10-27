// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  UnauthorizedError,
  batchDeleteAssets,
  batchMoveAssets,
  batchSetTags,
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

describe("bulk API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts one request for a bulk tag change", async () => {
    const payload = { updated: [], failed: [] };
    const fetchMock = installFetch(respond(payload));

    await expect(
      batchSetTags(["a1", "b2"], { add: ["pla"], remove: ["old"] }),
    ).resolves.toEqual(payload);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/assets/batch/tags")).toBe(true);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      asset_ids: ["a1", "b2"],
      add_tags: ["pla"],
      remove_tags: ["old"],
    });
  });

  it("sends empty tag arrays when only one side of the change is given", async () => {
    const fetchMock = installFetch(respond({ updated: [], failed: [] }));

    await batchSetTags(["a1"], { add: ["pla"] });

    const { init } = onlyCall(fetchMock);
    expect(JSON.parse(String(init.body))).toEqual({
      asset_ids: ["a1"],
      add_tags: ["pla"],
      remove_tags: [],
    });
  });

  it("posts one request for a bulk folder move", async () => {
    const payload = { updated: [], failed: [] };
    const fetchMock = installFetch(respond(payload));

    await expect(batchMoveAssets(["a1", "b2"], "f1")).resolves.toEqual(payload);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/assets/batch/folder")).toBe(true);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ asset_ids: ["a1", "b2"], folder_id: "f1" });
  });

  it("can move assets to unassigned with a null folder", async () => {
    const fetchMock = installFetch(respond({ updated: [], failed: [] }));

    await batchMoveAssets(["a1"], null);

    const { init } = onlyCall(fetchMock);
    expect(JSON.parse(String(init.body))).toEqual({ asset_ids: ["a1"], folder_id: null });
  });

  it("posts one request for a bulk delete", async () => {
    const payload = { deleted: ["a1"], failed: [] };
    const fetchMock = installFetch(respond(payload));

    await expect(batchDeleteAssets(["a1", "b2"])).resolves.toEqual(payload);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/assets/batch/delete")).toBe(true);
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ asset_ids: ["a1", "b2"] });
  });

  it("throws UnauthorizedError on 401", async () => {
    installFetch(respond(null, { ok: false, status: 401, body: "" }));

    await expect(batchDeleteAssets(["a1"])).rejects.toBeInstanceOf(UnauthorizedError);
  });

  it("surfaces the server detail on a whole-request 400", async () => {
    installFetch(
      respond(null, { ok: false, status: 400, body: JSON.stringify({ detail: "asset_ids is required" }) }),
    );

    const error = await batchSetTags([], { add: ["pla"] }).catch((err: unknown) => err);
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toBe("asset_ids is required");
  });
});
