// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import * as api from "./api";
import { assetFilePreviewUrl, fileUrl, getApiBase } from "./api";
import { clearToken, storeToken } from "./auth";
import {
  configureGrantMinter,
  evictGrant,
  primeGrants,
  rememberGrants,
  resetFileGrants,
  type Grant,
} from "./fileGrants";

/**
 * jsdom reports a `window.localStorage` getter but, under Node's experimental
 * global localStorage, it resolves to `undefined`; install a real in-memory
 * Storage so the code under test finds a working store.
 */
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

function parseRendered(src: string): URL {
  return new URL(src, "http://localhost");
}

const GRANT_TTL_SECONDS = 60;

/** The URL shape the server returns: the requested rel plus a `sig` parameter. */
function signedUrlFor(rel: string): string {
  return `${rel}${rel.includes("?") ? "&" : "?"}sig=signed-grant`;
}

function grantFor(rel: string): Grant {
  return {
    path: rel,
    url: signedUrlFor(rel),
    expires_at: Math.floor(Date.now() / 1000) + GRANT_TTL_SECONDS,
  };
}

/** Records what the client asked to mint; answers every path with a grant. */
function installGrantMinter(): string[][] {
  const calls: string[][] = [];
  configureGrantMinter(async paths => {
    calls.push([...paths]);
    rememberGrants(paths.map(grantFor));
  });
  return calls;
}

let minterCalls: string[][];

beforeEach(() => {
  installMemoryStorage();
  window.localStorage.clear();
  resetFileGrants();
  minterCalls = installGrantMinter();
});

afterEach(() => {
  configureGrantMinter(null);
  resetFileGrants();
  clearToken();
});

/**
 * `fileUrl` resolves through the grant cache. There is no session token in a
 * URL any more: ungranted paths are the plain API join, granted ones are the
 * signed URL the server minted for exactly that path.
 */
describe("fileUrl grants", () => {
  it("emits no token and no signature when nothing is cached", () => {
    const url = fileUrl("/file/abc123/logo.png");

    expect(url).toBe(`${getApiBase()}/file/abc123/logo.png`);
    expect(url).not.toContain("token=");
    expect(url).not.toContain("sig=");
    expect(minterCalls).toEqual([]);
  });

  it("resolves a primed path to the minted, absolute URL", async () => {
    await primeGrants(["/file/abc123/logo.png"]);

    const url = fileUrl("/file/abc123/logo.png");

    expect(url).toBe(`${getApiBase()}/file/abc123/logo.png?sig=signed-grant`);
    expect(parseRendered(url).searchParams.get("sig")).toBe("signed-grant");
    expect(parseRendered(url).searchParams.has("token")).toBe(false);
  });

  it("joins the API base even for an ungranted path (the server answers 401)", () => {
    expect(fileUrl("/thumb/abc123.jpg")).toBe(`${getApiBase()}/thumb/abc123.jpg`);
  });

  it("passes a falsy rel through untouched", () => {
    expect(fileUrl("")).toBe("");
  });

  it("falls back to the plain URL once the grant has been evicted", async () => {
    await primeGrants(["/file/abc123/logo.png"]);
    expect(fileUrl("/file/abc123/logo.png")).toContain("sig=");

    evictGrant("/file/abc123/logo.png");

    expect(fileUrl("/file/abc123/logo.png")).toBe(`${getApiBase()}/file/abc123/logo.png`);
  });

  it("never forwards an author-injected credential into a grant", async () => {
    const rel = "/file/abc123/logo.png?token=attacker";

    await primeGrants([rel]);
    const url = fileUrl(rel);

    // The server only signs its four path shapes with `v`/`inline`; the foreign
    // credential is not grantable, so nothing is minted for it and no viewer
    // credential is appended — the URL simply carries no grant and 401s.
    expect(minterCalls).toEqual([]);
    expect(parseRendered(url).searchParams.has("sig")).toBe(false);
    expect(url).toBe(`${getApiBase()}${rel}`);
  });
});

/** A signed-in session must still contribute no credential to a file URL. */
describe("fileUrl without grants", () => {
  it("never appends the session token, even when signed in", () => {
    storeToken("session-token");

    const url = fileUrl("/file/abc123/logo.png");

    expect(url).toBe(`${getApiBase()}/file/abc123/logo.png`);
    expect(url).not.toContain("session-token");
    expect(parseRendered(url).searchParams.has("token")).toBe(false);
  });
});

describe("assetFilePreviewUrl grants", () => {
  it("resolves the inline grant for a supporting file", async () => {
    await primeGrants(["/asset/a1/files/sf1"]);

    const url = assetFilePreviewUrl("/asset/a1/files/sf1");

    expect(url).toBe(`${getApiBase()}/asset/a1/files/sf1?inline=1&sig=signed-grant`);
    expect(parseRendered(url).searchParams.get("inline")).toBe("1");
    expect(parseRendered(url).searchParams.has("token")).toBe(false);
  });

  it("keeps an existing cache-buster and signs the inline variant", async () => {
    await primeGrants(["/asset/a1/files/sf1?v=2&inline=1"]);

    const url = assetFilePreviewUrl("/asset/a1/files/sf1?v=2");

    expect(url).toBe(`${getApiBase()}/asset/a1/files/sf1?v=2&inline=1&sig=signed-grant`);
    expect(parseRendered(url).searchParams.get("v")).toBe("2");
  });
});

describe("token-in-URL helpers", () => {
  it("no longer exports renderFileUrl", () => {
    expect("renderFileUrl" in api).toBe(false);
  });
});
