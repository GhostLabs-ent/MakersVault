// @vitest-environment jsdom
import { createElement, type ReactElement } from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as auth from "./auth";
import { getApiBase } from "./api";
import {
  configureGrantMinter,
  evictGrant,
  grantedFileUrl,
  grantExpiry,
  isGrantable,
  primeGrants,
  rememberGrants,
  resetFileGrants,
  useGrantedFileUrl,
  type Grant,
} from "./fileGrants";

const GRANT_TTL_SECONDS = 60;

function grantFor(rel: string): Grant {
  return {
    path: rel,
    url: `${rel}${rel.includes("?") ? "&" : "?"}sig=signed-grant`,
    expires_at: Math.floor(Date.now() / 1000) + GRANT_TTL_SECONDS,
  };
}

let minterCalls: string[][];

/** Installs a minter that records its batches and signs everything it is given. */
function installGrantMinter(): void {
  configureGrantMinter(async paths => {
    minterCalls.push([...paths]);
    rememberGrants(paths.map(grantFor));
  });
}

beforeEach(() => {
  resetFileGrants();
  minterCalls = [];
  installGrantMinter();
});

afterEach(() => {
  cleanup();
  configureGrantMinter(null);
  resetFileGrants();
});

describe("isGrantable", () => {
  it("accepts the four paths the server signs", () => {
    expect(isGrantable("/file/a1/model.stl")).toBe(true);
    expect(isGrantable("/asset/a1/files/sf1")).toBe(true);
    expect(isGrantable("/thumb/a1.jpg")).toBe(true);
    expect(isGrantable("/asset/a1/prepared-print")).toBe(true);
  });

  it("accepts only the v and inline query parameters", () => {
    expect(isGrantable("/thumb/a1.jpg?v=2")).toBe(true);
    expect(isGrantable("/asset/a1/files/sf1?inline=1")).toBe(true);
    expect(isGrantable("/asset/a1/files/sf1?v=2&inline=1")).toBe(true);
    expect(isGrantable("/asset/a1/files/sf1?sig=abc")).toBe(false);
    expect(isGrantable("/file/a1/model.stl?token=abc")).toBe(false);
  });

  it("rejects every other shape", () => {
    expect(isGrantable("/asset/a1/download")).toBe(false);
    expect(isGrantable("/files/a1/x")).toBe(false);
    expect(isGrantable("/thumb/a1.png")).toBe(false);
    expect(isGrantable("/file/a1")).toBe(false);
    expect(isGrantable("https://example.com/x.png")).toBe(false);
    expect(isGrantable("/api/file/a1/model.stl")).toBe(false);
    expect(isGrantable("")).toBe(false);
  });
});

describe("primeGrants", () => {
  it("coalesces calls from the same tick into one minter call", async () => {
    const first = primeGrants(["/file/a1/logo.png"]);
    const second = primeGrants(["/thumb/a2.jpg"]);
    const third = primeGrants(["/asset/a3/files/sf1"]);

    await Promise.all([first, second, third]);

    expect(minterCalls).toHaveLength(1);
    expect([...minterCalls[0]].sort()).toEqual([
      "/asset/a3/files/sf1",
      "/asset/a3/files/sf1?inline=1",
      "/file/a1/logo.png",
      "/thumb/a2.jpg",
    ]);
  });

  it("primes the inline variant for a supporting file without a query", async () => {
    await primeGrants(["/asset/a1/files/sf1"]);

    expect(minterCalls).toEqual([["/asset/a1/files/sf1", "/asset/a1/files/sf1?inline=1"]]);
  });

  it("dedupes the same path requested twice", async () => {
    await primeGrants(["/file/a1/logo.png", "/file/a1/logo.png"]);

    expect(minterCalls).toEqual([["/file/a1/logo.png"]]);
  });

  it("chunks batches larger than fifty paths", async () => {
    const paths = Array.from({ length: 120 }, (_, index) => `/file/a${index}/model.stl`);

    await primeGrants(paths);

    expect(minterCalls.map(chunk => chunk.length)).toEqual([50, 50, 20]);
    expect(minterCalls.flat()).toHaveLength(120);
  });

  it("never sends a path the server would reject", async () => {
    await primeGrants([
      "/file/a1/logo.png",
      "/asset/a1/download",
      "https://example.com/x.png",
      "/file/a1/logo.png?token=attacker",
      "/thumb/a1.png",
      "/asset/a1/prepared-print",
    ]);

    expect(minterCalls).toEqual([["/file/a1/logo.png", "/asset/a1/prepared-print"]]);
  });

  it("does not re-mint a path whose grant is still fresh", async () => {
    await primeGrants(["/file/a1/logo.png"]);
    await primeGrants(["/file/a1/logo.png"]);

    expect(minterCalls).toHaveLength(1);
    expect(grantedFileUrl("/file/a1/logo.png")).toContain("sig=");
  });

  it("re-mints after the grant was evicted", async () => {
    await primeGrants(["/file/a1/logo.png"]);
    evictGrant("/file/a1/logo.png");
    await primeGrants(["/file/a1/logo.png"]);

    expect(minterCalls).toHaveLength(2);
  });

  it("leaves the cache empty and still resolves when the minter rejects", async () => {
    configureGrantMinter(async () => {
      throw new Error("401");
    });

    await expect(primeGrants(["/file/a1/logo.png"])).resolves.toBeUndefined();

    expect(grantedFileUrl("/file/a1/logo.png")).toBeNull();
  });

  it("does nothing when no minter is configured", async () => {
    configureGrantMinter(null);

    await expect(primeGrants(["/file/a1/logo.png"])).resolves.toBeUndefined();

    expect(minterCalls).toEqual([]);
    expect(grantedFileUrl("/file/a1/logo.png")).toBeNull();
  });
});

describe("rememberGrants", () => {
  it("drops an already expired grant", () => {
    rememberGrants([
      {
        path: "/file/a1/logo.png",
        url: "/file/a1/logo.png?sig=stale",
        expires_at: Math.floor(Date.now() / 1000) - 10,
      },
    ]);

    expect(grantedFileUrl("/file/a1/logo.png")).toBeNull();
  });

  it("accepts an ISO-8601 expiry", () => {
    const expires = new Date(Date.now() + 60_000).toISOString();
    rememberGrants([{ path: "/thumb/a1.jpg", url: "/thumb/a1.jpg?sig=abc", expires_at: expires }]);

    expect(grantedFileUrl("/thumb/a1.jpg")).toBe("/thumb/a1.jpg?sig=abc");
  });

  it("ignores a grant for a path the server never signs", () => {
    const expires_at = Math.floor(Date.now() / 1000) + 60;
    rememberGrants([
      { path: "/asset/a1/download", url: "/asset/a1/download?sig=abc", expires_at },
    ]);

    expect(grantedFileUrl("/asset/a1/download")).toBeNull();
  });
});

/** Renders the hook's answer straight onto an `<img src>`. */
function Probe({ src }: { src: string }): ReactElement {
  const resolved = useGrantedFileUrl(src);
  return createElement("img", { alt: "probe", src: resolved });
}

describe("useGrantedFileUrl", () => {
  it("renders the fallback first, then the granted URL", async () => {
    const { getByRole } = render(createElement(Probe, { src: "/api/file/a1/logo.png" }));

    expect(getByRole("img").getAttribute("src")).toBe("/api/file/a1/logo.png");

    await waitFor(() => {
      expect(getByRole("img").getAttribute("src")).toBe(
        `${getApiBase()}/file/a1/logo.png?sig=signed-grant`,
      );
    });
    expect(minterCalls).toEqual([["/file/a1/logo.png"]]);
  });

  it("passes a foreign or non-api src through untouched", async () => {
    const { getByRole } = render(createElement(Probe, { src: "https://example.com/x.png" }));

    expect(getByRole("img").getAttribute("src")).toBe("https://example.com/x.png");

    await new Promise(resolve => setTimeout(resolve, 0));
    expect(minterCalls).toEqual([]);
  });

  it("re-mints a grant shortly before it expires while the image stays mounted", async () => {
    vi.useFakeTimers();
    try {
      const { getByRole } = render(createElement(Probe, { src: "/api/thumb/a1.jpg" }));
      await act(async () => {
        await Promise.resolve();
      });
      expect(minterCalls).toEqual([["/thumb/a1.jpg"]]);
      const first = getByRole("img").getAttribute("src");

      // The grant lives 60 s and the hook re-mints 5 s early, so a mounted image
      // never keeps a dead src past its deadline.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(GRANT_TTL_SECONDS * 1000);
      });

      expect(minterCalls).toEqual([["/thumb/a1.jpg"], ["/thumb/a1.jpg"]]);
      expect(grantExpiry("/thumb/a1.jpg")).toBeGreaterThan(Date.now());
      expect(getByRole("img").getAttribute("src")).toBe(first);
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves the fallback intact when no minter is configured", async () => {
    configureGrantMinter(null);

    const { getByRole } = render(createElement(Probe, { src: "/api/file/a1/logo.png" }));

    await new Promise(resolve => setTimeout(resolve, 0));
    expect(getByRole("img").getAttribute("src")).toBe("/api/file/a1/logo.png");
  });
});

describe("token-in-URL helpers", () => {
  it("has no appendTokenToUrl left in the auth module", () => {
    expect(Object.keys(auth)).not.toContain("appendTokenToUrl");
    expect((auth as Record<string, unknown>).appendTokenToUrl).toBeUndefined();
  });
});
