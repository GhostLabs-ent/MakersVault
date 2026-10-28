// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  assetFilePreviewUrl,
  listAssetFileLimits,
  renameAssetFile,
  reorderAssetFiles,
  type AssetFile,
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

const supportingFile: AssetFile = {
  id: "sf1",
  filename: "instructions.pdf",
  mime: "application/pdf",
  size: 1024,
  position: 0,
  url: "/asset/a1/files/sf1",
};

const limits = {
  count: 1,
  total_bytes: 1024,
  max_count: 5,
  max_file_bytes: 10_000_000,
  max_total_bytes: 50_000_000,
};

describe("asset-file API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the supporting-file limits for one asset", async () => {
    const fetchMock = installFetch(respond(limits));

    await expect(listAssetFileLimits("a1")).resolves.toEqual(limits);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/asset/a1/files/limits")).toBe(true);
    expect(init.method).toBeUndefined();
  });

  it("renames one supporting file with a JSON PATCH and parses the row", async () => {
    const renamed = { ...supportingFile, filename: "guide.pdf" };
    const fetchMock = installFetch(respond(renamed));

    await expect(renameAssetFile("a1", "sf1", "guide.pdf")).resolves.toEqual(renamed);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/asset/a1/files/sf1")).toBe(true);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({ filename: "guide.pdf" });
  });

  it("reorders supporting files with a JSON PUT and parses the ordered list", async () => {
    const reordered = [
      { ...supportingFile, id: "sf2", filename: "notes.txt", position: 0 },
      { ...supportingFile, position: 1 },
    ];
    const fetchMock = installFetch(respond(reordered));

    await expect(reorderAssetFiles("a1", ["sf2", "sf1"])).resolves.toEqual(reordered);

    const { url, init } = onlyCall(fetchMock);
    expect(url.endsWith("/asset/a1/files/order")).toBe(true);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body))).toEqual({ file_ids: ["sf2", "sf1"] });
  });

  it("rejects a rename with the server's detail on a 409", async () => {
    installFetch(
      respond(null, { ok: false, status: 409, body: JSON.stringify({ detail: "name already used" }) }),
    );

    await expect(renameAssetFile("a1", "sf1", "taken.pdf")).rejects.toThrow("name already used");
  });

  it("rejects a stale reorder with the server's reload message on a 409", async () => {
    installFetch(
      respond(null, {
        ok: false,
        status: 409,
        body: JSON.stringify({ detail: "Supporting file list changed; reload and try again" }),
      }),
    );

    await expect(reorderAssetFiles("a1", ["sf1"])).rejects.toThrow(
      "Supporting file list changed; reload and try again",
    );
  });

  it("appends inline=1 to the preview URL without dropping existing params", () => {
    expect(assetFilePreviewUrl("/asset/a1/files/sf1")).toMatch(
      /\/asset\/a1\/files\/sf1\?inline=1$/,
    );
    expect(assetFilePreviewUrl("/asset/a1/files/sf1?v=2")).toMatch(
      /\/asset\/a1\/files\/sf1\?v=2&inline=1$/,
    );
  });
});
