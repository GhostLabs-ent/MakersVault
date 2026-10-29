import { beforeEach, describe, expect, it, vi } from "vitest";

const { getOcctMock } = vi.hoisted(() => ({ getOcctMock: vi.fn() }));

vi.mock("./occt", () => ({ getOcct: getOcctMock }));

import type { OcctMesh, OcctModule } from "./occt";
import { collectTransferables, StepParseError, type StepGeometryPayload } from "./protocol";
import { readStepMeshes } from "./readStep";

function triangle(): Float32Array {
  return new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
}

function meshWith(overrides: Partial<OcctMesh> = {}): OcctMesh {
  return { attributes: { position: { array: triangle() } }, ...overrides };
}

function useOcctResult(ReadStepFile: ReturnType<typeof vi.fn>, result: unknown): void {
  getOcctMock.mockResolvedValue({ ReadStepFile } as unknown as OcctModule);
  ReadStepFile.mockResolvedValue(result);
}

/** Returns a `ReadStepFile` spy wired into the fake occt module. */
function prepareOcct(): ReturnType<typeof vi.fn> {
  const ReadStepFile = vi.fn();
  getOcctMock.mockResolvedValue({ ReadStepFile } as unknown as OcctModule);
  return ReadStepFile;
}

beforeEach(() => {
  getOcctMock.mockReset();
});

describe("readStepMeshes", () => {
  it("copies every array out of the occt heap", async () => {
    const ReadStepFile = prepareOcct();
    const positions = triangle();
    const normals = new Float64Array([0, 0, 1, 0, 0, 1, 0, 0, 1]);
    const indices = new Uint16Array([0, 1, 2]);
    const color: [number, number, number] = [10, 20, 30];
    useOcctResult(ReadStepFile, {
      meshes: [
        {
          color,
          attributes: { position: { array: positions }, normal: { array: normals } },
          index: { array: indices },
        },
      ],
    });

    const geometry = await readStepMeshes(new Uint8Array([1]));
    expect(geometry.meshes).toHaveLength(1);
    const mesh = geometry.meshes[0];

    expect(mesh.positions).toBeInstanceOf(Float32Array);
    expect(mesh.positions.buffer).not.toBe(positions.buffer);
    expect(mesh.normals).toBeInstanceOf(Float32Array);
    expect(mesh.normals?.buffer).not.toBe(normals.buffer);
    expect(mesh.indices).toBeInstanceOf(Uint32Array);
    expect(mesh.indices?.buffer).not.toBe(indices.buffer);

    positions[0] = 99;
    normals[0] = 99;
    indices[0] = 99;
    color[0] = 99;

    expect(Array.from(mesh.positions)).toEqual([0, 0, 0, 1, 0, 0, 0, 1, 0]);
    expect(Array.from(mesh.normals ?? [])).toEqual([0, 0, 1, 0, 0, 1, 0, 0, 1]);
    expect(Array.from(mesh.indices ?? [])).toEqual([0, 1, 2]);
    expect(mesh.color).toEqual([10, 20, 30]);
  });

  it("reports absent normals, indices and colour as null", async () => {
    const ReadStepFile = prepareOcct();
    useOcctResult(ReadStepFile, {
      meshes: [
        meshWith({
          attributes: { position: { array: triangle() }, normal: { array: [] } },
        }),
      ],
    });

    const geometry = await readStepMeshes(new Uint8Array([1]));

    expect(geometry.meshes[0].normals).toBeNull();
    expect(geometry.meshes[0].indices).toBeNull();
    expect(geometry.meshes[0].color).toBeNull();
  });

  it("skips meshes without positions", async () => {
    const ReadStepFile = prepareOcct();
    useOcctResult(ReadStepFile, {
      meshes: [{}, { attributes: { position: { array: [] } } }, meshWith()],
    });

    const geometry = await readStepMeshes(new Uint8Array([1]));

    expect(geometry.meshes).toHaveLength(1);
    expect(Array.from(geometry.meshes[0].positions)).toEqual([0, 0, 0, 1, 0, 0, 0, 1, 0]);
  });

  it("returns an empty payload when occt finds nothing", async () => {
    const ReadStepFile = prepareOcct();
    ReadStepFile.mockResolvedValue({});
    await expect(readStepMeshes(new Uint8Array([1]))).resolves.toEqual({ meshes: [] });

    ReadStepFile.mockResolvedValue({ meshes: [] });
    await expect(readStepMeshes(new Uint8Array([1]))).resolves.toEqual({ meshes: [] });
  });

  it("throws a StepParseError when the geometry limit is exceeded", async () => {
    // The real cap is 256 MB; shrink it instead of allocating a quarter gigabyte.
    vi.resetModules();
    vi.doMock("./protocol", async importOriginal => {
      const actual = await importOriginal<typeof import("./protocol")>();
      return { ...actual, STEP_MAX_GEOMETRY_BYTES: 8 };
    });
    try {
      const fresh = await import("./readStep");
      // The class is re-created with the module registry, so the assertion has
      // to look at the same `./protocol` instance the fresh `readStep` saw.
      const freshProtocol = await import("./protocol");
      const ReadStepFile = prepareOcct();
      ReadStepFile.mockResolvedValue({ meshes: [meshWith()] });

      await expect(fresh.readStepMeshes(new Uint8Array([1]))).rejects.toBeInstanceOf(
        freshProtocol.StepParseError,
      );
      await expect(fresh.readStepMeshes(new Uint8Array([1]))).rejects.toThrow(/limited to \d+ MB/);
    } finally {
      vi.doUnmock("./protocol");
      vi.resetModules();
    }
  });

  it("propagates a failing parse", async () => {
    const ReadStepFile = prepareOcct();
    ReadStepFile.mockRejectedValue(new Error("occt exploded"));

    await expect(readStepMeshes(new Uint8Array([1]))).rejects.toThrow("occt exploded");
  });
});

describe("collectTransferables", () => {
  it("lists every distinct buffer exactly once", () => {
    const shared = triangle();
    const sharedIndices = new Uint32Array([0, 1, 2]);
    const payload: StepGeometryPayload = {
      meshes: [
        { positions: shared, normals: new Float32Array(9), indices: sharedIndices, color: null },
        { positions: shared, normals: null, indices: sharedIndices, color: null },
      ],
    };

    const transferables = collectTransferables(payload);

    expect(transferables).toHaveLength(3);
    expect(new Set(transferables).size).toBe(3);
    expect(transferables).toContain(shared.buffer);
    expect(transferables).toContain(sharedIndices.buffer);
    for (const entry of transferables) {
      expect(entry).toBeInstanceOf(ArrayBuffer);
    }
  });

  it("returns an empty list for an empty payload", () => {
    expect(collectTransferables({ meshes: [] })).toEqual([]);
  });
});

describe("StepParseError", () => {
  it("carries a distinctive name", () => {
    expect(new StepParseError("nope").name).toBe("StepParseError");
  });
});
