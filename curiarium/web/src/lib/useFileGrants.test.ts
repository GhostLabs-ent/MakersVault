// @vitest-environment jsdom
//
// Unit tests for the grant-keeping hooks (`Mf-1vxh`). The grant machinery is
// real: `mintFileGrants` from `../lib/api/grants` installs itself as the minter
// on import and only `fetch` is stubbed, so `useFileGrants` is exercised
// through the same `primeGrants` -> `POST /file-grants` -> cache path the app
// uses. Nothing mocks `../lib/api` or `../lib/fileGrants`.
import { Fragment, createElement, type ReactElement } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mintFileGrants } from "../lib/api/grants";
import {
  configureGrantMinter,
  grantedFileUrl,
  resetFileGrants,
} from "../lib/fileGrants";

import { useFileGrants, useLiveFileGrants, GRANT_RETRY_MS } from "./useFileGrants";

/** The server's `FILE_GRANT_TTL_SECONDS`. */
const GRANT_TTL_SECONDS = 60;

const REL = "/thumb/a1.jpg";

/** Every path batch `POST /file-grants` was asked for, one entry per request. */
let mintRequests: string[][] = [];

/** Every minted URL gets a fresh `sig`, so a re-mint is distinguishable. */
let sigCounter = 0;

/** The status the stubbed mint answers with; 500 exercises the failure path. */
let mintStatus = 200;

/** Total transport calls, so "no fetch at all" is assertable. */
let fetchCalls = 0;

/** Every value each probe rendered, in order — the render counter. */
let renders: boolean[] = [];

function sigOf(url: string | null | undefined): string | null {
  if (!url) return null;
  const match = /[?&]sig=([^&]+)/.exec(url);
  return match ? match[1] : null;
}

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  };
}

function installFetchStub(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: unknown, init?: RequestInit) => {
      fetchCalls += 1;
      const url = String(input);
      const path = url.split("?")[0];
      if ((init?.method ?? "GET").toUpperCase() === "POST" && path.endsWith("/file-grants")) {
        const body = JSON.parse(String(init?.body ?? "{}")) as { paths?: string[] };
        const paths = Array.isArray(body.paths) ? body.paths : [];
        mintRequests.push([...paths]);
        if (mintStatus !== 200) return jsonResponse({ detail: "mint failed" }, mintStatus);
        return jsonResponse({
          grants: paths.map(grantPath => ({
            path: grantPath,
            url: `${grantPath}${grantPath.includes("?") ? "&" : "?"}sig=${sigCounter++}`,
            expires_at: Math.floor(Date.now() / 1000) + GRANT_TTL_SECONDS,
          })),
        });
      }
      return jsonResponse({});
    }),
  );
}

/** Flushes the mint -> cache -> repaint chain without polling timers. */
async function flush(): Promise<void> {
  await act(async () => {
    for (let round = 0; round < 12; round += 1) {
      await Promise.resolve();
    }
  });
}

/** Advances the fake clock past the grant TTL, letting every armed timer fire. */
async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  await flush();
}

/** Records one render and returns the probe's markup. */
function probeOutput(ready: boolean): ReactElement {
  renders.push(ready);
  // A `.ts` test file cannot hold JSX; `createElement` keeps the probe tiny.
  return createElement("output", { "data-testid": "ready" }, ready ? "ready" : "pending");
}

/** The silent variant: one hook, one recorded value per render. */
function Probe({ rels }: { rels: string[] }): ReactElement {
  return probeOutput(useFileGrants(rels));
}

/** The live variant, a separate component so each calls exactly one hook. */
function LiveProbe({ rels }: { rels: string[] }): ReactElement {
  return probeOutput(useLiveFileGrants(rels));
}

beforeEach(() => {
  vi.useFakeTimers();
  mintRequests = [];
  sigCounter = 0;
  mintStatus = 200;
  fetchCalls = 0;
  renders = [];
  resetFileGrants();
  configureGrantMinter(mintFileGrants);
  installFetchStub();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

afterAll(() => {
  configureGrantMinter(null);
  resetFileGrants();
});

describe("useFileGrants", () => {
  it("renders pending on a cold mount, mints once, then renders ready", async () => {
    render(createElement(Probe, { rels: [REL] }));

    expect(renders).toEqual([false]);
    expect(mintRequests).toHaveLength(0);

    await flush();

    expect(renders).toEqual([false, true]);
    expect(screen.getByTestId("ready").textContent).toBe("ready");
    expect(mintRequests).toEqual([[REL]]);
  });

  it("renders ready on the very first paint when the cache is already warm", async () => {
    render(createElement(Probe, { rels: [REL] }));
    await flush();

    cleanup();
    renders = [];
    const mintsBefore = mintRequests.length;

    render(createElement(Probe, { rels: [REL] }));

    expect(renders[0]).toBe(true);
    await flush();

    expect(mintRequests).toHaveLength(mintsBefore);
    // Settling is a state change even on a warm cache, so the mount costs one
    // more render; the intent is that the first paint was already ready and
    // that no paint of this mount was ever pending.
    expect(renders.every(value => value)).toBe(true);
  });

  it("refreshes silently: the cache holds a new grant and the component does not repaint", async () => {
    render(createElement(Probe, { rels: [REL] }));
    await flush();

    const firstSig = sigOf(grantedFileUrl(REL));
    expect(firstSig).not.toBeNull();
    const rendersBefore = renders.length;

    await advance(61_000);

    const refreshedUrl = grantedFileUrl(REL);
    expect(refreshedUrl).not.toBeNull();
    expect(sigOf(refreshedUrl)).not.toBe(firstSig);
    expect(renders.length).toBe(rendersBefore);
  });

  it("useLiveFileGrants repaints on the same refresh", async () => {
    render(createElement(LiveProbe, { rels: [REL] }));
    await flush();

    const firstSig = sigOf(grantedFileUrl(REL));
    expect(firstSig).not.toBeNull();
    const rendersBefore = renders.length;

    await advance(61_000);

    expect(renders.length).toBeGreaterThan(rendersBefore);
    expect(sigOf(grantedFileUrl(REL))).not.toBe(firstSig);
  });

  it("a failed renewal is retried instead of leaving the element stale", async () => {
    render(createElement(LiveProbe, { rels: [REL] }));
    await flush();

    const firstUrl = grantedFileUrl(REL);
    const firstSig = sigOf(firstUrl);
    expect(firstSig).not.toBeNull();
    const mintsBeforeRenewal = mintRequests.length;

    // The scheduled renewal fires five seconds before expiry; the mint fails.
    mintStatus = 500;
    await advance(56_000);

    expect(mintRequests.length).toBeGreaterThan(mintsBeforeRenewal);
    // A failed mint moved no expiry, so the old URL is still what a href renders.
    expect(grantedFileUrl(REL)).toBe(firstUrl);
    // The value never flipped: the live variant renders again on every refresh,
    // but with the same ready/pending answer it painted before the failure.
    expect(screen.getByTestId("ready").textContent).toBe("ready");
    // The keeper must be armed for another attempt, not disarmed for the mount.
    expect(vi.getTimerCount()).toBeGreaterThan(0);

    const rendersAfterFailure = renders.length;

    mintStatus = 200;
    await advance(GRANT_RETRY_MS);

    const healedUrl = grantedFileUrl(REL);
    expect(healedUrl).not.toBeNull();
    expect(sigOf(healedUrl)).not.toBe(firstSig);
    // The live variant must repaint so a mounted anchor picks the new href up.
    expect(renders.length).toBeGreaterThan(rendersAfterFailure);
  });

  it("a mint that fails and then heals never drops a gated view to pending", async () => {
    // Warm the cache under a first probe, then watch a second mount: it starts
    // ready, and a grant that expires under a failed renewal must not re-close
    // the gate while it is mounted.
    render(createElement(Probe, { rels: [REL] }));
    await flush();
    cleanup();

    renders = [];
    const view = render(createElement(Probe, { rels: [REL] }));
    expect(renders[0]).toBe(true);
    await flush();

    // The renewal fails, the grant expires, and the one retry fails too.
    mintStatus = 500;
    await advance(56_000);
    await advance(GRANT_RETRY_MS);
    expect(grantedFileUrl(REL)).toBeNull();

    // Forcing a paint while the cache is cold is what probes the gate: it must
    // not re-close just because the grant expired and the mints are failing.
    view.rerender(createElement(Probe, { rels: [REL] }));
    expect(screen.getByTestId("ready").textContent).toBe("ready");

    // A healed minter must reach the keeper even though nothing is cached: this
    // mount held a grant once, so it keeps retrying until one comes back.
    mintStatus = 200;
    const mintsBeforeHeal = mintRequests.length;
    await advance(GRANT_RETRY_MS);

    expect(mintRequests.length).toBeGreaterThan(mintsBeforeHeal);
    expect(grantedFileUrl(REL)).not.toBeNull();
    expect(renders.every(value => value)).toBe(true);

    // The gate is per rels key, not per instance: an instance that swaps to a
    // URL it holds no grant for (a renamed asset, or a previewed asset updated
    // in place) must paint that URL gated instead of unsigned.
    const renamed = "/thumb/a1-renamed.jpg";
    view.rerender(createElement(Probe, { rels: [renamed] }));
    expect(screen.getByTestId("ready").textContent).toBe("pending");
    await flush();
    expect(grantedFileUrl(renamed)).not.toBeNull();
    expect(screen.getByTestId("ready").textContent).toBe("ready");
  });
});

describe("useFileGrants degradation", () => {
  it("with no minter it is ready on the first render, fetches nothing and schedules nothing", async () => {
    configureGrantMinter(null);

    render(createElement(Probe, { rels: [REL] }));

    expect(renders).toEqual([true]);
    expect(fetchCalls).toBe(0);
    expect(vi.getTimerCount()).toBe(0);

    await flush();

    expect(renders).toEqual([true]);
    expect(fetchCalls).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("a mint that answers 500 still settles to ready and leaves no timer armed", async () => {
    mintStatus = 500;

    render(createElement(Probe, { rels: [REL] }));

    expect(renders).toEqual([false]);

    await flush();

    expect(renders).toEqual([false, true]);
    expect(screen.getByTestId("ready").textContent).toBe("ready");
    // The mint was attempted (and rejected); the hook still settled, and with no
    // cached grant there is no expiry to arm a refresh against.
    expect(mintRequests).toEqual([[REL]]);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("useFileGrants coalescing", () => {
  it("two components sharing one rel make a single mint request", async () => {
    render(
      createElement(
        Fragment,
        null,
        createElement(Probe, { rels: [REL] }),
        createElement(Probe, { rels: [REL] }),
      ),
    );
    await flush();

    expect(mintRequests).toHaveLength(1);
    expect(mintRequests[0]).toEqual([REL]);
    expect(grantedFileUrl(REL)).not.toBeNull();
  });
});
