import { getOcct } from "./occt";
import {
  STEP_MAX_GEOMETRY_BYTES,
  StepParseError,
  type StepGeometryPayload,
  type StepMeshPayload,
} from "./protocol";

/**
 * occt returns views onto its WASM heap. The heap is freed when the worker
 * goes away (and gets reused by the next parse), so every array has to be
 * copied out before it can be transferred to the main thread.
 */
function copyPositions(source: ArrayLike<number>): Float32Array {
  if (source instanceof Float32Array) return source.slice();
  return Float32Array.from(source);
}

function copyIndices(source: ArrayLike<number>): Uint32Array {
  if (source instanceof Uint32Array) return source.slice();
  return Uint32Array.from(source);
}

function copyColor(
  color: [number, number, number] | undefined,
): [number, number, number] | null {
  if (!color || color.length < 3) return null;
  return [color[0], color[1], color[2]];
}

function hasValues(source: ArrayLike<number> | undefined): source is ArrayLike<number> {
  return !!source && source.length > 0;
}

function geometryLimitMb(): number {
  return Math.floor(STEP_MAX_GEOMETRY_BYTES / (1024 * 1024));
}

/**
 * Parse a STEP file into transferable geometry. This is the synchronous-heavy
 * part of the pipeline and is meant to run inside the worker; the inline
 * fallback paths in `parseStepInWorker` reuse it unchanged.
 *
 * An empty result is not an error here: "no meshes at all" is reported by
 * `buildStepGroup` once the payload reaches the scene.
 */
export async function readStepMeshes(bytes: Uint8Array): Promise<StepGeometryPayload> {
  const occt = await getOcct();
  const result = await occt.ReadStepFile(bytes, null);
  const meshes: StepMeshPayload[] = [];
  let totalBytes = 0;

  for (const source of result.meshes ?? []) {
    const positions = source.attributes?.position?.array;
    if (!hasValues(positions)) continue;

    const normals = source.attributes?.normal?.array;
    const indices = source.index?.array;

    const positionsPayload = copyPositions(positions);
    const normalsPayload = hasValues(normals) ? copyPositions(normals) : null;
    const indicesPayload = hasValues(indices) ? copyIndices(indices) : null;

    totalBytes += positionsPayload.byteLength;
    if (normalsPayload) totalBytes += normalsPayload.byteLength;
    if (indicesPayload) totalBytes += indicesPayload.byteLength;

    if (totalBytes > STEP_MAX_GEOMETRY_BYTES) {
      throw new StepParseError(
        `STEP geometry is limited to ${geometryLimitMb()} MB; this model is too detailed ` +
          "to preview",
      );
    }

    meshes.push({
      positions: positionsPayload,
      normals: normalsPayload,
      indices: indicesPayload,
      color: copyColor(source.color),
    });
  }

  return { meshes };
}
