import * as THREE from "three";
import { describe, expect, it } from "vitest";

import { buildStepGroup } from "./buildStepGroup";
import type { StepGeometryPayload, StepMeshPayload } from "./protocol";

function mesh(overrides: Partial<StepMeshPayload> = {}): StepMeshPayload {
  return {
    positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]),
    normals: null,
    indices: null,
    color: null,
    ...overrides,
  };
}

function payload(meshes: StepMeshPayload[]): StepGeometryPayload {
  return { meshes };
}

function materialOf(group: THREE.Group, index: number): THREE.MeshStandardMaterial {
  const child = group.children[index] as THREE.Mesh;
  return child.material as THREE.MeshStandardMaterial;
}

function geometryOf(group: THREE.Group, index: number): THREE.BufferGeometry {
  const child = group.children[index] as THREE.Mesh;
  return child.geometry;
}

describe("buildStepGroup", () => {
  it("builds one mesh per payload entry", () => {
    const group = buildStepGroup(payload([mesh(), mesh()]));

    expect(group).toBeInstanceOf(THREE.Group);
    expect(group.children).toHaveLength(2);
    for (const child of group.children) expect(child).toBeInstanceOf(THREE.Mesh);
  });

  it("preserves positions, normals and indices byte for byte", () => {
    const positions = new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]);
    const normals = new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1]);
    const indices = new Uint32Array([0, 1, 2]);

    const group = buildStepGroup(payload([mesh({ positions, normals, indices })]));
    const geometry = geometryOf(group, 0);

    const positionAttribute = geometry.getAttribute("position");
    expect(positionAttribute.itemSize).toBe(3);
    expect(Array.from(positionAttribute.array)).toEqual(Array.from(positions));

    const normalAttribute = geometry.getAttribute("normal");
    expect(normalAttribute.itemSize).toBe(3);
    expect(Array.from(normalAttribute.array)).toEqual(Array.from(normals));

    expect(geometry.index).not.toBeNull();
    expect(Array.from(geometry.index?.array ?? [])).toEqual([0, 1, 2]);
    expect(geometry.index?.array).toBeInstanceOf(Uint32Array);
    expect(geometry.boundingSphere).not.toBeNull();
  });

  it("computes normals when the payload has no indices", () => {
    const group = buildStepGroup(payload([mesh()]));
    const geometry = geometryOf(group, 0);

    const normals = geometry.getAttribute("normal");
    expect(normals).toBeDefined();
    expect(Array.from(normals.array)).toEqual([0, 0, 1, 0, 0, 1, 0, 0, 1]);
  });

  it("falls back to the default colour when the mesh has none", () => {
    const group = buildStepGroup(payload([mesh()]));

    expect(materialOf(group, 0).color.getHex()).toBe(0xf1f5f9);
    expect(materialOf(group, 0).metalness).toBe(0.2);
    expect(materialOf(group, 0).roughness).toBe(0.8);
  });

  it("uses the mesh colour when the payload provides one", () => {
    const group = buildStepGroup(payload([mesh({ color: [255, 128, 0] })]));
    const { color } = materialOf(group, 0);

    expect(color.r).toBeCloseTo(1, 6);
    expect(color.g).toBeCloseTo(128 / 255, 6);
    expect(color.b).toBeCloseTo(0, 6);
  });

  it("skips meshes without positions", () => {
    const group = buildStepGroup(
      payload([mesh({ positions: new Float32Array(0) }), mesh()]),
    );

    expect(group.children).toHaveLength(1);
  });

  it("throws when no mesh survives", () => {
    expect(() => buildStepGroup(payload([]))).toThrow("STEP preview produced no meshes");
    expect(() => buildStepGroup(payload([mesh({ positions: new Float32Array(0) })]))).toThrow(
      "STEP preview produced no meshes",
    );
  });
});
