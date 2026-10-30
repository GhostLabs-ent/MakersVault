/**
 * Wire contract between the main thread and the STEP worker.
 *
 * The worker owns the occt WASM heap; everything it hands back is a fresh
 * typed array copied out of that heap, because the heap dies with the worker.
 * Keeping the payload this small (three typed arrays + a colour) means the
 * main thread never has to know what occt is.
 */

export const STEP_SIZE_WARN_BYTES = 20 * 1024 * 1024;
export const STEP_MAX_BYTES = 150 * 1024 * 1024;
export const STEP_INLINE_FALLBACK_BYTES = 4 * 1024 * 1024;
export const STEP_MAX_GEOMETRY_BYTES = 256 * 1024 * 1024;

export type StepMeshPayload = {
  positions: Float32Array;
  normals: Float32Array | null;
  indices: Uint32Array | null;
  color: [number, number, number] | null;
};

export type StepGeometryPayload = { meshes: StepMeshPayload[] };

export type StepWorkerRequest = { id: number; bytes: ArrayBuffer };

export type StepWorkerResponse =
  | { id: number; ok: true; geometry: StepGeometryPayload }
  | { id: number; ok: false; error: string };

/**
 * Lives here, next to the wire contract, so the main thread and the worker
 * share one class identity. `protocol` stays import-free so neither side pulls
 * the occt graph in just to name a failure.
 */
export class StepParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StepParseError";
  }
}

/** Every buffer in the payload, deduped, for a complete postMessage transfer list. */
export function collectTransferables(geometry: StepGeometryPayload): Transferable[] {
  const seen = new Set<ArrayBuffer>();
  const transferables: Transferable[] = [];
  for (const mesh of geometry.meshes) {
    for (const array of [mesh.positions, mesh.normals, mesh.indices]) {
      if (!array) continue;
      const buffer = array.buffer as ArrayBuffer;
      if (seen.has(buffer)) continue;
      seen.add(buffer);
      transferables.push(buffer);
    }
  }
  return transferables;
}
