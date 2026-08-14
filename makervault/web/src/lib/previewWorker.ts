import { unzipSync } from "fflate";

type Limits = {
  maxBytes: number;
  maxTriangles: number;
  maxExpandedBytes: number;
  maxEntries: number;
  maxMemoryBytes: number;
};

type RequestMessage = {
  id: string;
  buffer: ArrayBuffer;
  ext: string;
  width: number;
  height: number;
  limits: Limits;
  mode: "thumbnail" | "geometry";
};

type ParsedGeometry = {
  positions: Float32Array;
  indices: Uint32Array;
  triangleCount: number;
};

class PreviewParseError extends Error {
  reason: string;

  constructor(reason: string, message: string) {
    super(message);
    this.reason = reason;
  }
}

const attribute = (source: string, name: string) => {
  const match = new RegExp(`(?:^|\\s)${name}=["']([^"']+)["']`, "i").exec(source);
  return match?.[1] ?? null;
};

function ensureMemory(positions: number, indices: number, limits: Limits) {
  const estimated = positions * 4 + indices * 4;
  if (estimated > limits.maxMemoryBytes) {
    throw new PreviewParseError("memory_budget", "Preview geometry exceeds the memory budget");
  }
}

function validateGeometry(geometry: ParsedGeometry) {
  if (!geometry.triangleCount || !geometry.positions.length || !geometry.indices.length) {
    throw new PreviewParseError("invalid_geometry", "Preview contains no readable triangles");
  }
  for (let index = 0; index < geometry.positions.length; index += 1) {
    if (!Number.isFinite(geometry.positions[index])) {
      throw new PreviewParseError("invalid_geometry", "Preview contains invalid coordinates");
    }
  }
  return geometry;
}

function parseStl(buffer: ArrayBuffer, limits: Limits): ParsedGeometry {
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength < 15) {
    throw new PreviewParseError("malformed_stl", "STL is truncated");
  }
  const view = new DataView(buffer);
  if (bytes.byteLength >= 84) {
    const declared = view.getUint32(80, true);
    const expected = 84 + declared * 50;
    if (declared > 0 && expected <= bytes.byteLength) {
      if (declared > limits.maxTriangles) {
        throw new PreviewParseError("too_many_triangles", "STL exceeds the triangle budget");
      }
      ensureMemory(declared * 9, declared * 3, limits);
      const positions = new Float32Array(declared * 9);
      const indices = new Uint32Array(declared * 3);
      for (let triangle = 0; triangle < declared; triangle += 1) {
        const base = 84 + triangle * 50 + 12;
        for (let vertex = 0; vertex < 3; vertex += 1) {
          const source = base + vertex * 12;
          const target = triangle * 9 + vertex * 3;
          positions[target] = view.getFloat32(source, true);
          positions[target + 1] = view.getFloat32(source + 4, true);
          positions[target + 2] = view.getFloat32(source + 8, true);
          indices[triangle * 3 + vertex] = triangle * 3 + vertex;
        }
      }
      return validateGeometry({ positions, indices, triangleCount: declared });
    }
  }

  const text = new TextDecoder().decode(bytes);
  const values: number[] = [];
  const vertexPattern = /\bvertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)/gi;
  let match: RegExpExecArray | null;
  while ((match = vertexPattern.exec(text))) {
    values.push(Number(match[1]), Number(match[2]), Number(match[3]));
    if (values.length / 9 > limits.maxTriangles) {
      throw new PreviewParseError("too_many_triangles", "STL exceeds the triangle budget");
    }
  }
  const triangleCount = Math.floor(values.length / 9);
  if (values.length % 9 !== 0) {
    throw new PreviewParseError("malformed_stl", "STL facets are incomplete");
  }
  if (!triangleCount) {
    throw new PreviewParseError("malformed_stl", "STL contains no readable facets");
  }
  ensureMemory(values.length, triangleCount * 3, limits);
  const positions = Float32Array.from(values);
  const indices = Uint32Array.from({ length: triangleCount * 3 }, (_, index) => index);
  return validateGeometry({ positions, indices, triangleCount });
}

function parseObj(buffer: ArrayBuffer, limits: Limits): ParsedGeometry {
  const text = new TextDecoder().decode(buffer);
  const vertices: number[] = [];
  const indices: number[] = [];
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line.startsWith("v ")) {
      const parts = line.slice(2).trim().split(/\s+/).slice(0, 3).map(Number);
      if (parts.length !== 3 || parts.some(value => !Number.isFinite(value))) {
        throw new PreviewParseError("malformed_obj", "OBJ contains an invalid vertex");
      }
      vertices.push(parts[0], parts[1], parts[2]);
    } else if (line.startsWith("f ")) {
      const face = line.slice(2).trim().split(/\s+/).map(token => Number(token.split("/")[0]));
      if (face.length < 3 || face.some(value => !Number.isInteger(value) || value === 0)) {
        throw new PreviewParseError("malformed_obj", "OBJ contains an invalid face");
      }
      const normalize = (value: number) => value > 0 ? value - 1 : vertices.length / 3 + value;
      const root = normalize(face[0]);
      for (let index = 1; index < face.length - 1; index += 1) {
        indices.push(root, normalize(face[index]), normalize(face[index + 1]));
        if (indices.length / 3 > limits.maxTriangles) {
          throw new PreviewParseError("too_many_triangles", "OBJ exceeds the face budget");
        }
      }
    }
  }
  if (indices.some(index => index < 0 || index * 3 + 2 >= vertices.length)) {
    throw new PreviewParseError("malformed_obj", "OBJ face references a missing vertex");
  }
  if (!indices.length) {
    throw new PreviewParseError("malformed_obj", "OBJ contains no readable faces");
  }
  ensureMemory(vertices.length, indices.length, limits);
  return validateGeometry({
    positions: Float32Array.from(vertices),
    indices: Uint32Array.from(indices),
    triangleCount: indices.length / 3,
  });
}

function parse3mf(buffer: ArrayBuffer, limits: Limits): ParsedGeometry {
  let entries: Record<string, Uint8Array>;
  try {
    entries = unzipSync(new Uint8Array(buffer));
  } catch {
    throw new PreviewParseError("malformed_3mf", "3MF archive could not be read");
  }
  const names = Object.keys(entries);
  if (names.length > limits.maxEntries) {
    throw new PreviewParseError("archive_entries", "3MF exceeds the archive-entry budget");
  }
  const expandedBytes = Object.values(entries).reduce((sum, value) => sum + value.byteLength, 0);
  if (expandedBytes > limits.maxExpandedBytes) {
    throw new PreviewParseError("archive_expanded", "3MF exceeds the expanded-data budget");
  }

  const positions: number[] = [];
  const indices: number[] = [];
  for (const [name, bytes] of Object.entries(entries)) {
    if (!name.toLowerCase().endsWith(".model")) continue;
    const xml = new TextDecoder().decode(bytes);
    const localVertices: number[] = [];
    const vertexPattern = /<(?:[a-z\d_-]+:)?vertex\b([^>]*)\/?\s*>/gi;
    const trianglePattern = /<(?:[a-z\d_-]+:)?triangle\b([^>]*)\/?\s*>/gi;
    let match: RegExpExecArray | null;
    while ((match = vertexPattern.exec(xml))) {
      const x = Number(attribute(match[1], "x"));
      const y = Number(attribute(match[1], "y"));
      const z = Number(attribute(match[1], "z"));
      if (![x, y, z].every(Number.isFinite)) {
        throw new PreviewParseError("malformed_3mf", "3MF contains an invalid vertex");
      }
      localVertices.push(x, y, z);
    }
    const vertexOffset = positions.length / 3;
    positions.push(...localVertices);
    while ((match = trianglePattern.exec(xml))) {
      const face = ["v1", "v2", "v3"].map(namePart => Number(attribute(match![1], namePart)));
      if (face.some(value => !Number.isInteger(value) || value < 0 || value * 3 + 2 >= localVertices.length)) {
        throw new PreviewParseError("malformed_3mf", "3MF triangle references a missing vertex");
      }
      indices.push(vertexOffset + face[0], vertexOffset + face[1], vertexOffset + face[2]);
      if (indices.length / 3 > limits.maxTriangles) {
        throw new PreviewParseError("too_many_triangles", "3MF exceeds the triangle budget");
      }
    }
    ensureMemory(positions.length, indices.length, limits);
  }
  if (!indices.length) {
    throw new PreviewParseError("malformed_3mf", "3MF contains no readable triangles");
  }
  return validateGeometry({
    positions: Float32Array.from(positions),
    indices: Uint32Array.from(indices),
    triangleCount: indices.length / 3,
  });
}

function parseGeometry(message: RequestMessage): ParsedGeometry {
  if (message.buffer.byteLength > message.limits.maxBytes) {
    throw new PreviewParseError("file_too_large", "Model exceeds the preview file-size budget");
  }
  switch (message.ext.toLowerCase()) {
    case "stl": return parseStl(message.buffer, message.limits);
    case "obj": return parseObj(message.buffer, message.limits);
    case "3mf": return parse3mf(message.buffer, message.limits);
    default: throw new PreviewParseError("browser_unsupported", "This format has no isolated preview parser");
  }
}

function buildVertexNormals(geometry: ParsedGeometry, limits: Limits) {
  ensureMemory(geometry.positions.length * 2, geometry.indices.length, limits);
  const normals = new Float32Array(geometry.positions.length);
  const { positions, indices } = geometry;
  for (let triangle = 0; triangle < geometry.triangleCount; triangle += 1) {
    const ia = indices[triangle * 3] * 3;
    const ib = indices[triangle * 3 + 1] * 3;
    const ic = indices[triangle * 3 + 2] * 3;
    const abx = positions[ib] - positions[ia];
    const aby = positions[ib + 1] - positions[ia + 1];
    const abz = positions[ib + 2] - positions[ia + 2];
    const acx = positions[ic] - positions[ia];
    const acy = positions[ic + 1] - positions[ia + 1];
    const acz = positions[ic + 2] - positions[ia + 2];
    const nx = aby * acz - abz * acy;
    const ny = abz * acx - abx * acz;
    const nz = abx * acy - aby * acx;
    for (const offset of [ia, ib, ic]) {
      normals[offset] += nx;
      normals[offset + 1] += ny;
      normals[offset + 2] += nz;
    }
  }
  for (let index = 0; index < normals.length; index += 3) {
    const length = Math.hypot(normals[index], normals[index + 1], normals[index + 2]) || 1;
    normals[index] /= length;
    normals[index + 1] /= length;
    normals[index + 2] /= length;
  }
  return normals;
}

type ProjectedTriangle = {
  points: [number, number, number, number, number, number];
  depth: number;
  shade: number;
};

async function renderThumbnail(geometry: ParsedGeometry, width: number, height: number): Promise<Blob> {
  if (typeof OffscreenCanvas === "undefined") {
    throw new PreviewParseError("browser_unsupported", "Offscreen preview rendering is unavailable");
  }
  const canvas = new OffscreenCanvas(Math.max(120, width), Math.max(120, height));
  const context = canvas.getContext("2d");
  if (!context) throw new PreviewParseError("browser_unsupported", "Offscreen 2D rendering is unavailable");
  const positions = geometry.positions;
  const indices = geometry.indices;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const projected = new Float32Array((positions.length / 3) * 2);
  for (let vertex = 0; vertex < positions.length / 3; vertex += 1) {
    const x = positions[vertex * 3];
    const y = positions[vertex * 3 + 1];
    const z = positions[vertex * 3 + 2];
    const px = (x - z) * 0.7071;
    const py = y * 0.82 - (x + z) * 0.35;
    projected[vertex * 2] = px;
    projected[vertex * 2 + 1] = py;
    minX = Math.min(minX, px); maxX = Math.max(maxX, px);
    minY = Math.min(minY, py); maxY = Math.max(maxY, py);
  }
  const padding = 10;
  const scale = Math.min(
    (canvas.width - padding * 2) / Math.max(1e-6, maxX - minX),
    (canvas.height - padding * 2) / Math.max(1e-6, maxY - minY),
  );
  const offsetX = (canvas.width - (maxX - minX) * scale) / 2 - minX * scale;
  const offsetY = (canvas.height - (maxY - minY) * scale) / 2 - minY * scale;
  const maxDrawn = 15_000;
  const step = Math.max(1, Math.ceil(geometry.triangleCount / maxDrawn));
  const triangles: ProjectedTriangle[] = [];
  for (let triangle = 0; triangle < geometry.triangleCount; triangle += step) {
    const ia = indices[triangle * 3], ib = indices[triangle * 3 + 1], ic = indices[triangle * 3 + 2];
    const ax = positions[ia * 3], ay = positions[ia * 3 + 1], az = positions[ia * 3 + 2];
    const bx = positions[ib * 3], by = positions[ib * 3 + 1], bz = positions[ib * 3 + 2];
    const cx = positions[ic * 3], cy = positions[ic * 3 + 1], cz = positions[ic * 3 + 2];
    const ux = bx - ax, uy = by - ay, uz = bz - az;
    const vx = cx - ax, vy = cy - ay, vz = cz - az;
    const nz = ux * vy - uy * vx;
    const nx = uy * vz - uz * vy;
    const ny = uz * vx - ux * vz;
    const length = Math.hypot(nx, ny, nz) || 1;
    const shade = Math.max(0.18, Math.min(1, 0.55 + (nx * 0.35 + ny * 0.45 + nz * 0.8) / length * 0.45));
    triangles.push({
      points: [
        projected[ia * 2] * scale + offsetX, projected[ia * 2 + 1] * scale + offsetY,
        projected[ib * 2] * scale + offsetX, projected[ib * 2 + 1] * scale + offsetY,
        projected[ic * 2] * scale + offsetX, projected[ic * 2 + 1] * scale + offsetY,
      ],
      depth: (ax + ay + az + bx + by + bz + cx + cy + cz) / 9,
      shade,
    });
  }
  triangles.sort((left, right) => left.depth - right.depth);
  context.clearRect(0, 0, canvas.width, canvas.height);
  for (const triangle of triangles) {
    const lightness = Math.round(35 + triangle.shade * 45);
    context.fillStyle = `hsl(210 28% ${lightness}%)`;
    context.strokeStyle = `hsl(215 25% ${Math.max(20, lightness - 15)}%)`;
    context.lineWidth = 0.35;
    context.beginPath();
    context.moveTo(triangle.points[0], triangle.points[1]);
    context.lineTo(triangle.points[2], triangle.points[3]);
    context.lineTo(triangle.points[4], triangle.points[5]);
    context.closePath();
    context.fill();
    context.stroke();
  }
  return canvas.convertToBlob({ type: "image/png" });
}

self.onmessage = async (event: MessageEvent<RequestMessage>) => {
  const message = event.data;
  try {
    const geometry = parseGeometry(message);
    if (message.mode === "geometry") {
      const normals = buildVertexNormals(geometry, message.limits);
      self.postMessage(
        { id: message.id, ok: true, geometry: { ...geometry, normals } },
        { transfer: [geometry.positions.buffer, geometry.indices.buffer, normals.buffer] },
      );
      return;
    }
    const blob = await renderThumbnail(geometry, message.width, message.height);
    self.postMessage({ id: message.id, ok: true, blob, triangleCount: geometry.triangleCount });
  } catch (error) {
    const reason = error instanceof PreviewParseError ? error.reason : "invalid_geometry";
    const detail = error instanceof Error ? error.message : "Preview generation failed";
    self.postMessage({ id: message.id, ok: false, reason, detail });
  }
};
