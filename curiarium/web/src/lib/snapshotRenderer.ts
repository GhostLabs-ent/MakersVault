import * as THREE from "three";

/**
 * One PERSISTENT WebGL renderer for all preview snapshots, behind a mutex.
 *
 * Building and tearing down a `WebGLRenderer` per snapshot churns a WebGL
 * context per card, which is both slow and a real driver limit (browsers cap
 * live contexts). The renderer is therefore created lazily exactly once and
 * reused; only the per-job render lists are released after each snapshot.
 *
 * The pool object itself is cheap and created at import time. The *renderer* is
 * the lazy part: React StrictMode double-invokes effects and jsdom/vitest has
 * no real WebGL, so nothing may touch `new THREE.WebGLRenderer` until work is
 * actually requested.
 */

/**
 * Copied verbatim from the original per-snapshot renderer.
 *
 * `preserveDrawingBuffer` in particular is load-bearing: without it the drawing
 * buffer is cleared after the draw call and `toDataURL` returns an empty image.
 */
export const SNAPSHOT_RENDERER_OPTIONS = {
  antialias: true,
  alpha: true,
  preserveDrawingBuffer: true,
} as const;

export type SnapshotRendererHandle = {
  renderer: THREE.WebGLRenderer;
  release: () => void;
};

export type SnapshotRendererFactory = () => THREE.WebGLRenderer;

function defaultCreateRenderer(): THREE.WebGLRenderer {
  const renderer = new THREE.WebGLRenderer({ ...SNAPSHOT_RENDERER_OPTIONS });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  return renderer;
}

export type SnapshotRendererPoolOptions = {
  createRenderer?: SnapshotRendererFactory;
};

export class SnapshotRendererPool {
  private readonly createRenderer: SnapshotRendererFactory;
  private renderer: THREE.WebGLRenderer | null = null;
  private detachContextLoss: (() => void) | null = null;
  private lock: Promise<void> = Promise.resolve();
  private releaseLock: (() => void) | null = null;

  constructor(options: SnapshotRendererPoolOptions = {}) {
    this.createRenderer = options.createRenderer ?? defaultCreateRenderer;
  }

  /**
   * Waits for the exclusive renderer, then hands out a handle.
   *
   * The wait is a plain, non-interruptible promise chain on purpose: the abort
   * signal is only observed by the caller immediately before and after this
   * await. A cancelled waiter still acquires the lock, renders nothing, and
   * releases it.
   */
  async acquire(): Promise<SnapshotRendererHandle> {
    const wait = this.lock;
    this.lock = wait.then(
      () =>
        new Promise<void>(resolve => {
          this.releaseLock = resolve;
        }),
    );
    await wait;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = this.getRenderer();
    } catch (error) {
      // A renderer that cannot be created must not poison the lock: the next job
      // gets a fresh attempt instead of waiting on a chain that will never resolve.
      this.unlock();
      throw error;
    }

    let released = false;
    const release = (): void => {
      if (released) return;
      released = true;
      // Free the per-job render lists; the context itself is kept for the next job.
      try {
        renderer.renderLists.dispose();
      } catch {}
      this.unlock();
    };
    return { renderer, release };
  }

  /**
   * Resolves the current lock holder, if any. Safe to call when no one holds the
   * lock: the same failure path can reach it twice.
   */
  private unlock(): void {
    const unlock = this.releaseLock;
    this.releaseLock = null;
    if (!unlock) return;
    unlock();
  }

  /**
   * Drops the renderer after a lost context so the next `acquire()` builds a
   * fresh one. Without this every later snapshot would silently render blank.
   */
  dispose(): void {
    this.detach();
    const renderer = this.renderer;
    this.renderer = null;
    if (!renderer) return;
    try {
      renderer.forceContextLoss?.();
      renderer.dispose();
    } catch {}
  }

  private getRenderer(): THREE.WebGLRenderer {
    if (this.renderer) return this.renderer;
    const renderer = this.createRenderer();
    const onLost = (): void => this.handleContextLost(renderer);
    renderer.domElement.addEventListener("webglcontextlost", onLost);
    this.renderer = renderer;
    this.detachContextLoss = () => renderer.domElement.removeEventListener("webglcontextlost", onLost);
    return renderer;
  }

  private handleContextLost(renderer: THREE.WebGLRenderer): void {
    if (this.renderer !== renderer) return;
    this.detach();
    this.renderer = null;
    try {
      // `forceContextLoss` is deliberately not called: the context is already
      // gone, and forcing it again on a lost context is pointless at best.
      renderer.dispose();
    } catch {}
  }

  private detach(): void {
    const detach = this.detachContextLoss;
    this.detachContextLoss = null;
    if (detach) detach();
  }
}

const snapshotRendererPool = new SnapshotRendererPool();

export function acquireSnapshotRenderer(): Promise<SnapshotRendererHandle> {
  return snapshotRendererPool.acquire();
}

export function disposeSnapshotRenderer(): void {
  snapshotRendererPool.dispose();
}

if (import.meta.hot) {
  // Without this a hot edit leaks one live WebGL context per module reload.
  import.meta.hot.dispose(() => disposeSnapshotRenderer());
}
