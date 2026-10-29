import * as THREE from "three";

import type { StepGeometryPayload } from "./protocol";

const DEFAULT_STEP_COLOR = 0xf1f5f9;

function colorFor(color: [number, number, number] | null): THREE.Color {
  if (!color) return new THREE.Color(DEFAULT_STEP_COLOR);
  return new THREE.Color(color[0] / 255, color[1] / 255, color[2] / 255);
}

/**
 * Rebuild the worker's payload into a scene graph. The typed arrays arrive as
 * transferred buffers, so they are handed to three as-is: nothing else holds
 * a reference to them and copying here would double the peak memory of a
 * large STEP model.
 */
export function buildStepGroup(geometry: StepGeometryPayload): THREE.Group {
  const group = new THREE.Group();

  for (const mesh of geometry.meshes) {
    if (mesh.positions.length === 0) continue;

    const geom = new THREE.BufferGeometry();
    geom.setAttribute("position", new THREE.Float32BufferAttribute(mesh.positions, 3));
    if (mesh.normals && mesh.normals.length > 0) {
      geom.setAttribute("normal", new THREE.Float32BufferAttribute(mesh.normals, 3));
    }
    if (mesh.indices && mesh.indices.length > 0) {
      geom.setIndex(new THREE.Uint32BufferAttribute(mesh.indices, 1));
    } else {
      geom.computeVertexNormals();
    }
    geom.computeBoundingSphere();

    const material = new THREE.MeshStandardMaterial({
      color: colorFor(mesh.color),
      metalness: 0.2,
      roughness: 0.8,
    });
    group.add(new THREE.Mesh(geom, material));
  }

  if (group.children.length === 0) {
    throw new Error("STEP preview produced no meshes");
  }
  return group;
}
