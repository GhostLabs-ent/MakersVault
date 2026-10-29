import initOcctFactory from "occt-import-js";
import occtWasmUrl from "occt-import-js/dist/occt-import-js.wasm?url";
import occtWorkerUrl from "occt-import-js/dist/occt-import-js-worker.js?url";

export type OcctMesh = {
  color?: [number, number, number];
  attributes?: {
    position?: { array: ArrayLike<number> };
    normal?: { array: ArrayLike<number> };
  };
  index?: { array: ArrayLike<number> };
};

export type OcctStepResult = { meshes?: OcctMesh[] };

export type OcctModule = {
  ReadStepFile(buffer: Uint8Array, params: null): Promise<OcctStepResult>;
};

type OcctInitOptions = { locateFile: (file: string) => string };
type OcctInit = (options: OcctInitOptions) => Promise<OcctModule>;

let initPromise: Promise<OcctModule> | null = null;

/**
 * occt resolves its WASM binary and its pthread helper relative to the bundle
 * URL, which does not survive Vite's dev server or a hashed production build.
 * Pointing both at the URLs Vite emitted is the only thing the module needs.
 */
function locateFile(file: string): string {
  if (file.endsWith(".wasm")) return occtWasmUrl;
  if (file.endsWith(".worker.js")) return occtWorkerUrl;
  return file;
}

async function initOcct(): Promise<OcctModule> {
  try {
    // The import is static on purpose: a dynamic one would force Vite to
    // code-split the STEP worker, which it cannot do with the iife format it
    // uses for workers. Laziness lives in `parseStepInWorker` instead.
    const init = initOcctFactory as unknown as OcctInit;
    return await init({ locateFile });
  } catch (error) {
    // Never memoise a rejected init: a failed WASM fetch is usually transient,
    // and the next caller should retry instead of inheriting the failure.
    initPromise = null;
    throw error;
  }
}

/**
 * One WASM module per worker. Concurrent callers share the same promise so
 * occt is instantiated once, not once per preview.
 */
export function getOcct(): Promise<OcctModule> {
  if (!initPromise) initPromise = initOcct();
  return initPromise;
}

export function resetOcctForTests(): void {
  initPromise = null;
}
