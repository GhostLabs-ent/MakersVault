// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import * as THREE from "three";

import { SNAPSHOT_RENDERER_OPTIONS, SnapshotRendererPool } from "./snapshotRenderer";

type FakeRenderer = {
  domElement: HTMLCanvasElement;
  setPixelRatio: ReturnType<typeof vi.fn>;
  setSize: ReturnType<typeof vi.fn>;
  render: ReturnType<typeof vi.fn>;
  renderLists: { dispose: ReturnType<typeof vi.fn> };
  forceContextLoss: ReturnType<typeof vi.fn>;
  dispose: ReturnType<typeof vi.fn>;
};

function createFakeRenderer(): FakeRenderer {
  return {
    domElement: document.createElement("canvas"),
    setPixelRatio: vi.fn(),
    setSize: vi.fn(),
    render: vi.fn(),
    renderLists: { dispose: vi.fn() },
    forceContextLoss: vi.fn(),
    dispose: vi.fn(),
  };
}

/** The pool only touches the members above; a real renderer needs a live GL context. */
function asRenderer(fake: FakeRenderer): THREE.WebGLRenderer {
  return fake as unknown as THREE.WebGLRenderer;
}

type Harness = {
  pool: SnapshotRendererPool;
  factory: ReturnType<typeof vi.fn>;
  created: FakeRenderer[];
};

function harness(): Harness {
  const created: FakeRenderer[] = [];
  const factory = vi.fn((): THREE.WebGLRenderer => {
    const fake = createFakeRenderer();
    created.push(fake);
    return asRenderer(fake);
  });
  const pool = new SnapshotRendererPool({ createRenderer: factory });
  return { pool, factory, created };
}

function flush(): Promise<void> {
  return new Promise(resolve => {
    setTimeout(resolve, 0);
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SnapshotRendererPool renderer reuse", () => {
  it("reuses one renderer across 50 sequential previews", async () => {
    const { pool, factory } = harness();
    const seen = new Set<THREE.WebGLRenderer>();

    for (let i = 0; i < 50; i += 1) {
      const handle = await pool.acquire();
      seen.add(handle.renderer);
      handle.release();
    }

    expect(factory).toHaveBeenCalledTimes(1);
    expect(seen.size).toBe(1);
    pool.dispose();
  });

  it("creates the renderer lazily, not when the pool is constructed", async () => {
    const { pool, factory } = harness();

    expect(factory).not.toHaveBeenCalled();

    const handle = await pool.acquire();
    expect(factory).toHaveBeenCalledTimes(1);
    handle.release();
    pool.dispose();
  });

  it("frees the per-job render lists on release without disposing the renderer", async () => {
    const { pool, created } = harness();

    for (let i = 0; i < 3; i += 1) {
      const handle = await pool.acquire();
      handle.release();
    }

    const renderer = created[0];
    expect(renderer.renderLists.dispose).toHaveBeenCalledTimes(3);
    expect(renderer.forceContextLoss).not.toHaveBeenCalled();
    expect(renderer.dispose).not.toHaveBeenCalled();
    pool.dispose();
  });

  it("makes release idempotent", async () => {
    const { pool, created } = harness();
    const handle = await pool.acquire();

    handle.release();
    handle.release();

    expect(created[0].renderLists.dispose).toHaveBeenCalledTimes(1);

    // The lock chain still works after the double release.
    const next = await pool.acquire();
    expect(next.renderer).toBe(handle.renderer);
    next.release();
    pool.dispose();
  });
});

describe("SnapshotRendererPool lock", () => {
  it("serialises concurrent jobs so only one holds the renderer at a time", async () => {
    const { pool } = harness();
    let live = 0;
    let maxLive = 0;

    const acquireTracked = async () => {
      const handle = await pool.acquire();
      live += 1;
      maxLive = Math.max(maxLive, live);
      return {
        renderer: handle.renderer,
        release: () => {
          live -= 1;
          handle.release();
        },
      };
    };

    const first = await acquireTracked();
    let secondResolved = false;
    let thirdResolved = false;
    const secondPromise = acquireTracked().then(handle => {
      secondResolved = true;
      return handle;
    });
    const thirdPromise = acquireTracked().then(handle => {
      thirdResolved = true;
      return handle;
    });

    await flush();
    expect(secondResolved).toBe(false);
    expect(thirdResolved).toBe(false);

    first.release();
    const second = await secondPromise;
    expect(secondResolved).toBe(true);
    expect(thirdResolved).toBe(false);

    second.release();
    const third = await thirdPromise;
    expect(thirdResolved).toBe(true);
    third.release();

    expect(maxLive).toBe(1);
    pool.dispose();
  });

  it("does not poison the lock when the renderer cannot be created", async () => {
    const creationError = new Error("snapshot renderer could not be created");
    const created: FakeRenderer[] = [];
    let attempts = 0;
    const factory = vi.fn((): THREE.WebGLRenderer => {
      attempts += 1;
      if (attempts === 1) throw creationError;
      const fake = createFakeRenderer();
      created.push(fake);
      return asRenderer(fake);
    });
    const pool = new SnapshotRendererPool({ createRenderer: factory });

    await expect(pool.acquire()).rejects.toThrow(creationError.message);

    // Without the fix the second acquire waits on a lock chain that never
    // resolves. Race it against a real timer so a regression fails the test
    // instead of hanging the suite.
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    const hung = new Promise<never>((_, reject) => {
      timeoutId = setTimeout(() => {
        reject(new Error("acquire() hung after a failed renderer creation"));
      }, 1000);
    });

    let handle: Awaited<ReturnType<SnapshotRendererPool["acquire"]>>;
    try {
      handle = await Promise.race([pool.acquire(), hung]);
    } finally {
      clearTimeout(timeoutId);
    }

    expect(factory).toHaveBeenCalledTimes(2);
    expect(handle.renderer).toBe(asRenderer(created[0]));
    handle.release();
    pool.dispose();
  });
});

describe("SnapshotRendererPool context loss", () => {
  it("builds a fresh renderer after the WebGL context is lost", async () => {
    const { pool, factory, created } = harness();
    const first = await pool.acquire();
    first.release();

    created[0].domElement.dispatchEvent(new Event("webglcontextlost"));

    // The dropped renderer is disposed, but never force-lost (already gone).
    expect(created[0].dispose).toHaveBeenCalledTimes(1);
    expect(created[0].forceContextLoss).not.toHaveBeenCalled();

    const second = await pool.acquire();
    expect(factory).toHaveBeenCalledTimes(2);
    expect(second.renderer).not.toBe(first.renderer);
    second.release();
    pool.dispose();
  });
});

describe("SnapshotRendererPool dispose", () => {
  it("tears the renderer down, ignores later context loss, and can start over", async () => {
    const { pool, factory, created } = harness();
    const handle = await pool.acquire();
    handle.release();
    const renderer = created[0];

    pool.dispose();
    expect(renderer.forceContextLoss).toHaveBeenCalledTimes(1);
    expect(renderer.dispose).toHaveBeenCalledTimes(1);

    // The listener is detached: a stray event must not reach the pool.
    renderer.domElement.dispatchEvent(new Event("webglcontextlost"));
    expect(renderer.dispose).toHaveBeenCalledTimes(1);

    const fresh = await pool.acquire();
    expect(factory).toHaveBeenCalledTimes(2);
    expect(fresh.renderer).not.toBe(handle.renderer);
    fresh.release();
    pool.dispose();
  });
});

describe("SNAPSHOT_RENDERER_OPTIONS", () => {
  it("keeps the three factory options verbatim", () => {
    expect(SNAPSHOT_RENDERER_OPTIONS).toEqual({
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: true,
    });
  });
});
