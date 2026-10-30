/**
 * Parser for LightBurn projects (`.lbrn` / `.lbrn2`).
 *
 * Both formats are plain UTF-8 XML. `.lbrn` (FormatVersion 0) stores path
 * geometry as verbose `<V>` / `<P>` elements; `.lbrn2` (FormatVersion 1)
 * stores it compactly in `<VertList>` / `<PrimList>` text and may deduplicate
 * geometry behind `VertID` / `PrimID` references.
 *
 * The parser is deliberately defensive: it never throws for malformed shape
 * data, only for things that cannot be a LightBurn project at all (bad header,
 * unsafe DOCTYPE/ENTITY, wrong root element). Budget overruns and missing
 * deduplicated geometry degrade to a partial model with `truncated = true`.
 */

export type LightBurnLayer = {
  index: number;
  name: string;
  kind: string;
  color: string;
  isTool: boolean;
  isHidden: boolean;
  shapeCount: number;
};

export type LightBurnLayerPath = { layer: number; d: string };

export type LightBurnThumbnail = { data: Uint8Array; mime: string };

export type LightBurnModel = {
  layers: LightBurnLayer[];
  paths: LightBurnLayerPath[];
  bounds: { minX: number; minY: number; maxX: number; maxY: number } | null;
  thumbnail: LightBurnThumbnail | null;
  truncated: boolean;
  stats: { shapes: number; skippedShapes: number; segments: number };
};

export type LightBurnLimits = { maxShapes: number; maxSegments: number };

export const DEFAULT_LIGHTBURN_LIMITS: LightBurnLimits = {
  maxShapes: 100_000,
  maxSegments: 40_000,
};

export const REDUCED_LIGHTBURN_LIMITS: LightBurnLimits = {
  maxShapes: 50_000,
  maxSegments: 20_000,
};

export const LIGHTBURN_MAX_BYTES = 32 * 1024 * 1024;
export const LIGHTBURN_WARN_BYTES = 8 * 1024 * 1024;
export const LIGHTBURN_INLINE_FALLBACK_BYTES = 2 * 1024 * 1024;

const MAX_XML_NODES = 200_000;
const MAX_XML_DEPTH = 64;
const MAX_THUMBNAIL_BASE64 = 8_000_000;
const MAX_GROUP_DEPTH = 32;
const ELLIPSE_SEGMENTS = 48;
const BEZIER_SEGMENTS = 12;
const FALLBACK_LAYER_COLOR = "#9CA3AF";

const LAYER_COLORS: readonly string[] = [
  "#000000",
  "#0000FF",
  "#FF0000",
  "#00E000",
  "#D0D000",
  "#FF8000",
  "#00E0E0",
  "#FF00FF",
  "#B4B4B4",
  "#0000A0",
  "#A00000",
  "#00A000",
  "#A0A000",
  "#C08000",
  "#00A0FF",
  "#A000A0",
  "#808080",
  "#7D87B9",
  "#BB7784",
  "#4A6FE3",
  "#D33F6A",
  "#8CD78C",
  "#F0B98D",
  "#F6C4E1",
  "#FA9ED4",
  "#500A78",
  "#B45A00",
  "#004754",
  "#86FA88",
  "#FFDB66",
  "#F36926",
  "#0C96D9",
];

export class LightBurnParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LightBurnParseError";
  }
}

type XmlNode = {
  name: string;
  attrs: Record<string, string>;
  children: XmlNode[];
  text: string;
};

type Transform = [number, number, number, number, number, number];

type XY = { x: number; y: number };

type Vertex = {
  x: number;
  y: number;
  c0x: number | null;
  c0y: number | null;
  c1x: number | null;
  c1y: number | null;
};

type Prim = { type: "L" | "B"; from: number; to: number };

type Budget = { remaining: number };

type Rendered = { d: string; segments: number; points: XY[]; complete: boolean };

type ParseState = {
  limits: LightBurnLimits;
  declared: Map<number, LightBurnLayer>;
  implicit: Map<number, LightBurnLayer>;
  paths: LightBurnLayerPath[];
  bounds: { minX: number; minY: number; maxX: number; maxY: number } | null;
  truncated: boolean;
  stopped: boolean;
  stats: { shapes: number; skippedShapes: number; segments: number };
  vertCache: Map<number, Vertex[]>;
  primCache: Map<number, Prim[]>;
};

function decodeEntities(value: string): string {
  if (value.indexOf("&") === -1) return value;
  return value.replace(
    /&(?:#x([0-9a-fA-F]+)|#(\d+)|(amp|lt|gt|quot|apos));/g,
    (match: string, hex?: string, dec?: string, named?: string): string => {
      if (named === "amp") return "&";
      if (named === "lt") return "<";
      if (named === "gt") return ">";
      if (named === "quot") return '"';
      if (named === "apos") return "'";
      const code = hex !== undefined ? Number.parseInt(hex, 16) : Number.parseInt(dec ?? "", 10);
      if (!Number.isFinite(code) || code < 0 || code > 0x10ffff) return match;
      try {
        return String.fromCodePoint(code);
      } catch {
        return match;
      }
    },
  );
}

function parseXmlDocument(text: string): { root: XmlNode; truncated: boolean } {
  const document: XmlNode = { name: "#document", attrs: {}, children: [], text: "" };
  const stack: Array<{ name: string; node: XmlNode | null }> = [{ name: "#document", node: document }];
  let index = 0;
  let nodes = 0;
  let truncated = false;

  const appendText = (raw: string): void => {
    if (!raw) return;
    const top = stack[stack.length - 1];
    if (!top.node) return;
    top.node.text += decodeEntities(raw);
  };

  while (index < text.length) {
    const lt = text.indexOf("<", index);
    if (lt === -1) {
      appendText(text.slice(index));
      break;
    }
    if (lt > index) appendText(text.slice(index, lt));
    index = lt;

    if (text.startsWith("<!--", index)) {
      const end = text.indexOf("-->", index + 4);
      if (end === -1) throw new LightBurnParseError("Unterminated XML comment");
      index = end + 3;
      continue;
    }
    if (text.startsWith("<![CDATA[", index)) {
      const end = text.indexOf("]]>", index + 9);
      if (end === -1) throw new LightBurnParseError("Unterminated CDATA section");
      appendText(text.slice(index + 9, end));
      index = end + 3;
      continue;
    }
    if (text.startsWith("<?", index)) {
      const end = text.indexOf("?>", index + 2);
      if (end === -1) throw new LightBurnParseError("Unterminated XML declaration");
      index = end + 2;
      continue;
    }
    if (text.startsWith("<!", index)) {
      const end = text.indexOf(">", index + 2);
      if (end === -1) throw new LightBurnParseError("Unterminated XML declaration");
      index = end + 1;
      continue;
    }
    if (text.startsWith("</", index)) {
      const end = text.indexOf(">", index + 2);
      if (end === -1) throw new LightBurnParseError("Unterminated end tag");
      const name = text.slice(index + 2, end).trim();
      let matches = -1;
      for (let depth = stack.length - 1; depth > 0; depth -= 1) {
        if (stack[depth].name === name) {
          matches = depth;
          break;
        }
      }
      if (matches === -1) throw new LightBurnParseError(`Unexpected end tag </${name}>`);
      stack.length = matches;
      index = end + 1;
      continue;
    }

    index += 1;
    const nameStart = index;
    while (index < text.length && !/[\s/>]/.test(text[index])) index += 1;
    const name = text.slice(nameStart, index);
    if (!name) throw new LightBurnParseError("Invalid XML tag");

    const attrs: Record<string, string> = {};
    let selfClosing = false;
    while (index < text.length) {
      while (index < text.length && /\s/.test(text[index])) index += 1;
      if (index >= text.length) throw new LightBurnParseError("Unterminated XML tag");
      if (text[index] === ">") {
        index += 1;
        break;
      }
      if (text[index] === "/") {
        if (text[index + 1] === ">") {
          selfClosing = true;
          index += 2;
          break;
        }
        index += 1;
        continue;
      }
      const attrStart = index;
      while (index < text.length && !/[\s=/>]/.test(text[index])) index += 1;
      const attrName = text.slice(attrStart, index);
      while (index < text.length && /\s/.test(text[index])) index += 1;
      if (text[index] !== "=") {
        if (attrName) attrs[attrName] = "";
        continue;
      }
      index += 1;
      while (index < text.length && /\s/.test(text[index])) index += 1;
      const quote = text[index];
      if (quote !== '"' && quote !== "'") {
        throw new LightBurnParseError(`Unquoted attribute ${attrName}`);
      }
      index += 1;
      const valueStart = index;
      while (index < text.length && text[index] !== quote) index += 1;
      if (index >= text.length) throw new LightBurnParseError(`Unterminated attribute ${attrName}`);
      attrs[attrName] = decodeEntities(text.slice(valueStart, index));
      index += 1;
    }

    const parent = stack[stack.length - 1];
    let node: XmlNode | null = null;
    if (parent.node) {
      nodes += 1;
      if (nodes > MAX_XML_NODES || stack.length > MAX_XML_DEPTH) {
        truncated = true;
      } else {
        node = { name, attrs, children: [], text: "" };
        parent.node.children.push(node);
      }
    }
    if (!selfClosing) stack.push({ name, node });
  }

  if (stack.length > 1) throw new LightBurnParseError("Unclosed XML element");
  const root = document.children[0];
  if (!root) throw new LightBurnParseError("LightBurn file has no root element");
  return { root, truncated };
}

function findChild(node: XmlNode, name: string): XmlNode | undefined {
  return node.children.find(child => child.name === name);
}

function findDescendant(node: XmlNode, name: string, predicate?: (node: XmlNode) => boolean): XmlNode | undefined {
  for (const child of node.children) {
    if (child.name === name && (!predicate || predicate(child))) return child;
    const nested = findDescendant(child, name, predicate);
    if (nested) return nested;
  }
  return undefined;
}

function childValue(node: XmlNode, name: string): string | undefined {
  const child = findChild(node, name);
  return child ? child.attrs.Value : undefined;
}

function numberValue(value: string | undefined, fallback: number): number {
  if (value === undefined) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function numberAttr(node: XmlNode, name: string, fallback: number): number {
  return numberValue(node.attrs[name], fallback);
}

function colorForIndex(index: number): string {
  if (index >= 0 && index < LAYER_COLORS.length) return LAYER_COLORS[index];
  return FALLBACK_LAYER_COLOR;
}

function defaultLayerName(index: number): string {
  if (index >= 0 && index < 30) return `C${String(index).padStart(2, "0")}`;
  if (index === 30) return "T1";
  if (index === 31) return "T2";
  return `Layer ${index}`;
}

function ensureLayer(state: ParseState, index: number): LightBurnLayer {
  const declared = state.declared.get(index);
  if (declared) return declared;
  let implicit = state.implicit.get(index);
  if (!implicit) {
    implicit = {
      index,
      name: `Layer ${index}`,
      kind: "Cut",
      color: FALLBACK_LAYER_COLOR,
      isTool: index >= 30,
      isHidden: false,
      shapeCount: 0,
    };
    state.implicit.set(index, implicit);
  }
  return implicit;
}

function roundCoordinate(value: number): number {
  const rounded = Math.round(value * 1000) / 1000;
  return Object.is(rounded, -0) ? 0 : rounded;
}

function formatCoordinate(value: number): string {
  return String(roundCoordinate(value));
}

function applyTransform(x: number, y: number, transform: Transform | null): { x: number; y: number } {
  if (!transform) return { x, y };
  const [a, b, c, d, e, f] = transform;
  return { x: a * x + c * y + e, y: b * x + d * y + f };
}

function composeTransforms(parent: Transform | null, child: Transform | null): Transform | null {
  if (!parent) return child;
  if (!child) return parent;
  const [ap, bp, cp, dp, ep, fp] = parent;
  const [ac, bc, cc, dc, ce, cf] = child;
  return [
    ap * ac + cp * bc,
    bp * ac + dp * bc,
    ap * cc + cp * dc,
    bp * cc + dp * dc,
    ap * ce + cp * cf + ep,
    bp * ce + dp * cf + fp,
  ];
}

function toSvgPoint(x: number, y: number, transform: Transform | null): XY {
  const point = applyTransform(x, y, transform);
  return { x: roundCoordinate(point.x), y: roundCoordinate(-point.y) };
}

function samePoint(a: XY, b: XY): boolean {
  return a.x === b.x && a.y === b.y;
}

function parseXForm(node: XmlNode): Transform | null {
  const form = findChild(node, "XForm");
  if (!form) return null;
  const values = form.text
    .trim()
    .split(/\s+/)
    .map(Number)
    .filter(value => Number.isFinite(value));
  if (values.length < 6) return null;
  return [values[0], values[1], values[2], values[3], values[4], values[5]];
}

function buildPathData(subpaths: XY[][], closed: boolean[]): string {
  const chunks: string[] = [];
  for (let i = 0; i < subpaths.length; i += 1) {
    const points = subpaths[i];
    if (points.length < 2) continue;
    const parts: string[] = [`M ${formatCoordinate(points[0].x)} ${formatCoordinate(points[0].y)}`];
    for (let p = 1; p < points.length; p += 1) {
      parts.push(`L ${formatCoordinate(points[p].x)} ${formatCoordinate(points[p].y)}`);
    }
    if (closed[i]) parts.push("Z");
    chunks.push(parts.join(" "));
  }
  return chunks.join(" ");
}

function numberToken(value: string | undefined): number | null {
  if (value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseVertListText(text: string): Vertex[] {
  const vertices: Vertex[] = [];
  const chunks = text.split("V");
  for (const chunk of chunks) {
    const trimmed = chunk.trim();
    if (!trimmed) continue;
    const match = /^(-?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+(-?\d*\.?\d+(?:[eE][-+]?\d+)?)([\s\S]*)$/.exec(
      trimmed,
    );
    if (!match) continue;
    const x = Number(match[1]);
    const y = Number(match[2]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    const handles: Record<string, number> = {};
    const handlePattern = /c([01])([xy])(-?\d*\.?\d+(?:[eE][-+]?\d+)?)/g;
    let handle = handlePattern.exec(match[3]);
    while (handle) {
      handles[`c${handle[1]}${handle[2]}`] = Number(handle[3]);
      handle = handlePattern.exec(match[3]);
    }
    vertices.push({
      x,
      y,
      c0x: handles.c0x ?? null,
      c0y: handles.c0y ?? null,
      c1x: handles.c1x ?? null,
      c1y: handles.c1y ?? null,
    });
  }
  return vertices;
}

function parseLegacyVertex(node: XmlNode): Vertex {
  return {
    x: numberAttr(node, "vx", 0),
    y: numberAttr(node, "vy", 0),
    c0x: numberToken(node.attrs.c0x),
    c0y: numberToken(node.attrs.c0y),
    c1x: numberToken(node.attrs.c1x),
    c1y: numberToken(node.attrs.c1y),
  };
}

function parsePrimListText(text: string, vertexCount: number): Prim[] {
  const trimmed = text.trim();
  if (trimmed === "LineClosed" || trimmed === "LineOpen") {
    const prims: Prim[] = [];
    for (let i = 0; i + 1 < vertexCount; i += 1) {
      prims.push({ type: "L", from: i, to: i + 1 });
    }
    if (trimmed === "LineClosed" && vertexCount > 1) {
      prims.push({ type: "L", from: vertexCount - 1, to: 0 });
    }
    return prims;
  }
  const prims: Prim[] = [];
  const pattern = /([LB])\s*(\d+)\s+(\d+)/g;
  let match = pattern.exec(text);
  while (match) {
    prims.push({ type: match[1] === "B" ? "B" : "L", from: Number(match[2]), to: Number(match[3]) });
    match = pattern.exec(text);
  }
  return prims;
}

function parseLegacyPrim(node: XmlNode): Prim {
  return {
    type: node.attrs.T === "B" ? "B" : "L",
    from: numberAttr(node, "p0", 0),
    to: numberAttr(node, "p1", 0),
  };
}

type GeometryResult =
  | { ok: true; vertices: Vertex[]; prims: Prim[] }
  | { ok: false; missing: boolean };

function collectGeometry(shape: XmlNode, state: ParseState): GeometryResult {
  const vertId = numberToken(shape.attrs.VertID);
  const primId = numberToken(shape.attrs.PrimID);

  let vertices: Vertex[] | null = null;
  let missingVertices = false;
  const vertList = findChild(shape, "VertList");
  if (vertList) {
    vertices = parseVertListText(vertList.text);
    if (vertId !== null) state.vertCache.set(vertId, vertices);
  } else if (vertId !== null) {
    const cached = state.vertCache.get(vertId);
    if (cached) vertices = cached;
    else missingVertices = true;
  } else {
    const legacy = shape.children.filter(child => child.name === "V").map(parseLegacyVertex);
    if (legacy.length > 0) vertices = legacy;
  }

  const vertexCount = vertices ? vertices.length : 0;
  let prims: Prim[] | null = null;
  let missingPrims = false;
  const primList = findChild(shape, "PrimList");
  if (primList) {
    prims = parsePrimListText(primList.text, vertexCount);
    if (primId !== null) state.primCache.set(primId, prims);
  } else if (primId !== null) {
    const cached = state.primCache.get(primId);
    if (cached) prims = cached;
    else missingPrims = true;
  } else {
    const legacy = shape.children.filter(child => child.name === "P").map(parseLegacyPrim);
    if (legacy.length > 0) prims = legacy;
  }

  if (missingVertices || missingPrims) return { ok: false, missing: true };
  if (!vertices || vertices.length === 0 || !prims || prims.length === 0) {
    return { ok: false, missing: false };
  }
  return { ok: true, vertices, prims };
}

function cubicPoint(p0: XY, p1: XY, p2: XY, p3: XY, t: number): XY {
  const mt = 1 - t;
  const a = mt * mt * mt;
  const b = 3 * mt * mt * t;
  const c = 3 * mt * t * t;
  const d = t * t * t;
  return {
    x: p0.x * a + p1.x * b + p2.x * c + p3.x * d,
    y: p0.y * a + p1.y * b + p2.y * c + p3.y * d,
  };
}

function renderPrims(vertices: Vertex[], prims: Prim[], transform: Transform | null, budget: Budget): Rendered {
  const subpaths: XY[][] = [];
  const allPoints: XY[] = [];
  const cursor: { current: XY[] | null } = { current: null };
  let segments = 0;
  let complete = true;

  const startSubpath = (point: XY): void => {
    const created = [point];
    subpaths.push(created);
    allPoints.push(point);
    cursor.current = created;
  };

  const appendPoint = (point: XY): boolean => {
    const active = cursor.current;
    if (!active) {
      startSubpath(point);
      return true;
    }
    const last = active[active.length - 1];
    if (samePoint(last, point)) return true;
    if (budget.remaining <= 0) {
      complete = false;
      return false;
    }
    active.push(point);
    allPoints.push(point);
    budget.remaining -= 1;
    segments += 1;
    return true;
  };

  for (const prim of prims) {
    if (!complete) break;
    const from = vertices[prim.from];
    const to = vertices[prim.to];
    if (!from || !to) continue;

    const start = toSvgPoint(from.x, from.y, transform);
    const active = cursor.current;
    if (!active || !samePoint(active[active.length - 1], start)) {
      startSubpath(start);
    }
    const end = toSvgPoint(to.x, to.y, transform);

    if (prim.type === "B") {
      const hasOutgoing = from.c0x !== null && from.c0y !== null;
      const hasIncoming = to.c1x !== null && to.c1y !== null;
      if (!hasOutgoing || !hasIncoming) {
        if (!appendPoint(end)) break;
        continue;
      }
      const control1 = toSvgPoint(from.c0x as number, from.c0y as number, transform);
      const control2 = toSvgPoint(to.c1x as number, to.c1y as number, transform);
      for (let step = 1; step <= BEZIER_SEGMENTS; step += 1) {
        const point =
          step === BEZIER_SEGMENTS
            ? end
            : cubicPoint(start, control1, control2, end, step / BEZIER_SEGMENTS);
        if (!appendPoint(point)) break;
      }
    } else if (!appendPoint(end)) {
      break;
    }
  }

  const closed = subpaths.map(subpath => {
    if (subpath.length >= 3 && samePoint(subpath[0], subpath[subpath.length - 1])) {
      subpath.pop();
      return true;
    }
    return false;
  });

  return {
    d: buildPathData(subpaths, closed),
    segments,
    points: allPoints,
    complete,
  };
}

function renderPolygon(
  localPoints: XY[],
  closed: boolean,
  transform: Transform | null,
  budget: Budget,
): Rendered {
  if (localPoints.length === 0) return { d: "", segments: 0, points: [], complete: true };
  const first = toSvgPoint(localPoints[0].x, localPoints[0].y, transform);
  const subpath: XY[] = [first];
  const points: XY[] = [first];
  let segments = 0;
  let complete = true;

  for (let i = 1; i < localPoints.length; i += 1) {
    const point = toSvgPoint(localPoints[i].x, localPoints[i].y, transform);
    const last = subpath[subpath.length - 1];
    if (samePoint(last, point)) continue;
    if (budget.remaining <= 0) {
      complete = false;
      break;
    }
    subpath.push(point);
    points.push(point);
    budget.remaining -= 1;
    segments += 1;
  }

  const isClosed = closed && complete && subpath.length >= 3;
  return {
    d: buildPathData([subpath], [isClosed]),
    segments,
    points,
    complete,
  };
}

function recordPath(state: ParseState, layerIndex: number, rendered: Rendered): void {
  if (rendered.points.length < 2 || !rendered.d) return;
  const layer = ensureLayer(state, layerIndex);
  layer.shapeCount += 1;
  state.paths.push({ layer: layerIndex, d: rendered.d });
  state.stats.segments += rendered.segments;
  if (!rendered.complete) state.truncated = true;

  let bounds = state.bounds;
  for (const point of rendered.points) {
    if (!bounds) {
      bounds = { minX: point.x, minY: point.y, maxX: point.x, maxY: point.y };
    } else {
      if (point.x < bounds.minX) bounds.minX = point.x;
      if (point.y < bounds.minY) bounds.minY = point.y;
      if (point.x > bounds.maxX) bounds.maxX = point.x;
      if (point.y > bounds.maxY) bounds.maxY = point.y;
    }
  }
  state.bounds = bounds;
}

function emitRect(state: ParseState, node: XmlNode, cutIndex: number, transform: Transform | null): void {
  const width = Math.abs(numberAttr(node, "W", 0));
  const height = Math.abs(numberAttr(node, "H", 0));
  if (!Number.isFinite(width) || !Number.isFinite(height) || width === 0 || height === 0) return;
  const halfWidth = width / 2;
  const halfHeight = height / 2;
  const local: XY[] = [
    { x: -halfWidth, y: -halfHeight },
    { x: halfWidth, y: -halfHeight },
    { x: halfWidth, y: halfHeight },
    { x: -halfWidth, y: halfHeight },
  ];
  const budget: Budget = { remaining: state.limits.maxSegments - state.stats.segments };
  recordPath(state, cutIndex, renderPolygon(local, true, transform, budget));
}

function emitEllipse(state: ParseState, node: XmlNode, cutIndex: number, transform: Transform | null): void {
  const rx = Math.abs(numberAttr(node, "Rx", 0));
  const ry = Math.abs(numberAttr(node, "Ry", 0));
  if (!Number.isFinite(rx) || !Number.isFinite(ry) || rx === 0 || ry === 0) return;
  const local: XY[] = [];
  for (let i = 0; i < ELLIPSE_SEGMENTS; i += 1) {
    const angle = (Math.PI * 2 * i) / ELLIPSE_SEGMENTS;
    local.push({ x: Math.cos(angle) * rx, y: Math.sin(angle) * ry });
  }
  const budget: Budget = { remaining: state.limits.maxSegments - state.stats.segments };
  recordPath(state, cutIndex, renderPolygon(local, true, transform, budget));
}

function emitBitmap(state: ParseState, node: XmlNode, cutIndex: number, transform: Transform | null): void {
  const width = Math.abs(numberAttr(node, "W", 0));
  const height = Math.abs(numberAttr(node, "H", 0));
  if (!Number.isFinite(width) || !Number.isFinite(height) || width === 0 || height === 0) return;
  const halfWidth = width / 2;
  const halfHeight = height / 2;
  const local: XY[] = [
    { x: -halfWidth, y: -halfHeight },
    { x: halfWidth, y: -halfHeight },
    { x: halfWidth, y: halfHeight },
    { x: -halfWidth, y: halfHeight },
  ];
  const budget: Budget = { remaining: state.limits.maxSegments - state.stats.segments };
  recordPath(state, cutIndex, renderPolygon(local, true, transform, budget));
}

function emitPath(
  state: ParseState,
  shape: XmlNode,
  cutIndex: number,
  transform: Transform | null,
): void {
  const geometry = collectGeometry(shape, state);
  if (!geometry.ok) {
    if (geometry.missing) {
      state.stats.skippedShapes += 1;
      state.truncated = true;
    }
    return;
  }
  const budget: Budget = { remaining: state.limits.maxSegments - state.stats.segments };
  recordPath(
    state,
    cutIndex,
    renderPrims(geometry.vertices, geometry.prims, transform, budget),
  );
}

function emitText(state: ParseState, node: XmlNode, cutIndex: number, transform: Transform | null): void {
  const backup = findDescendant(node, "BackupPath");
  if (!backup) return;
  const pathShape = findDescendant(backup, "Shape", candidate => candidate.attrs.Type === "Path");
  if (!pathShape) return;
  const backupTransform = composeTransforms(transform, parseXForm(pathShape));
  const backupCut =
    pathShape.attrs.CutIndex !== undefined ? numberAttr(pathShape, "CutIndex", cutIndex) : cutIndex;
  ensureLayer(state, backupCut);
  emitPath(state, pathShape, backupCut, backupTransform);
}

function processShape(
  state: ParseState,
  node: XmlNode,
  parentTransform: Transform | null,
  inheritedCut: number | null,
  depth: number,
): boolean {
  if (state.stopped) return true;
  if (state.stats.shapes >= state.limits.maxShapes) {
    state.truncated = true;
    state.stopped = true;
    return true;
  }
  if (state.limits.maxSegments - state.stats.segments <= 0) {
    state.truncated = true;
    state.stopped = true;
    return true;
  }

  state.stats.shapes += 1;
  const cutIndex =
    node.attrs.CutIndex !== undefined ? numberAttr(node, "CutIndex", inheritedCut ?? 0) : inheritedCut ?? 0;
  ensureLayer(state, cutIndex);
  const transform = composeTransforms(parentTransform, parseXForm(node));

  switch (node.attrs.Type) {
    case "Group": {
      if (depth >= MAX_GROUP_DEPTH) return false;
      const children = findChild(node, "Children");
      if (!children) return false;
      for (const child of children.children) {
        if (child.name !== "Shape") continue;
        if (processShape(state, child, transform, cutIndex, depth + 1)) return true;
      }
      return false;
    }
    case "Rect":
      emitRect(state, node, cutIndex, transform);
      return state.stopped;
    case "Ellipse":
      emitEllipse(state, node, cutIndex, transform);
      return state.stopped;
    case "Bitmap":
      emitBitmap(state, node, cutIndex, transform);
      return state.stopped;
    case "Path":
      emitPath(state, node, cutIndex, transform);
      return state.stopped;
    case "Text":
      emitText(state, node, cutIndex, transform);
      return state.stopped;
    default:
      return false;
  }
}

function parseLayers(root: XmlNode): Map<number, LightBurnLayer> {
  const layers = new Map<number, LightBurnLayer>();
  for (const node of root.children) {
    if (node.name !== "CutSetting") continue;
    const index = Math.trunc(numberValue(childValue(node, "index"), 0));
    if (layers.has(index)) continue;
    const kind = node.attrs.type ?? "Cut";
    const name = childValue(node, "name") ?? defaultLayerName(index);
    const doOutput = childValue(node, "doOutput");
    const hide = childValue(node, "hide");
    layers.set(index, {
      index,
      name,
      kind,
      color: colorForIndex(index),
      isTool: kind === "Tool" || index >= 30,
      isHidden: doOutput === "0" || hide === "1",
      shapeCount: 0,
    });
  }
  return layers;
}

function detectImageMime(data: Uint8Array): string | null {
  if (
    data.length >= 8 &&
    data[0] === 0x89 &&
    data[1] === 0x50 &&
    data[2] === 0x4e &&
    data[3] === 0x47 &&
    data[4] === 0x0d &&
    data[5] === 0x0a &&
    data[6] === 0x1a &&
    data[7] === 0x0a
  ) {
    return "image/png";
  }
  if (data.length >= 2 && data[0] === 0xff && data[1] === 0xd8) return "image/jpeg";
  if (
    data.length >= 12 &&
    data[0] === 0x52 &&
    data[1] === 0x49 &&
    data[2] === 0x46 &&
    data[3] === 0x46 &&
    data[8] === 0x57 &&
    data[9] === 0x45 &&
    data[10] === 0x42 &&
    data[11] === 0x50
  ) {
    return "image/webp";
  }
  return null;
}

function parseThumbnail(root: XmlNode): LightBurnThumbnail | null {
  const node = findChild(root, "Thumbnail");
  const source = node?.attrs.Source;
  if (!source) return null;
  // Truncating base64 would only ever yield an undecodable image, so drop the
  // oversized thumbnail entirely and let the vector/raster fallbacks take over.
  if (source.length > MAX_THUMBNAIL_BASE64) return null;
  let binary: string;
  try {
    binary = atob(source.replace(/\s+/g, ""));
  } catch {
    return null;
  }
  const data = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) data[i] = binary.charCodeAt(i);
  const mime = detectImageMime(data);
  if (!mime) return null;
  return { data, mime };
}

export function parseLightBurn(bytes: Uint8Array, limits?: Partial<LightBurnLimits>): LightBurnModel {
  if (bytes.length > LIGHTBURN_MAX_BYTES) {
    throw new LightBurnParseError(
      `LightBurn preview is limited to ${Math.floor(LIGHTBURN_MAX_BYTES / (1024 * 1024))} MB`,
    );
  }

  const text = new TextDecoder("utf-8").decode(bytes);
  const leading = text.replace(/^\uFEFF/, "").trimStart();
  if (!leading) throw new LightBurnParseError("LightBurn file is empty");
  if (leading[0] !== "<") throw new LightBurnParseError("LightBurn file is not XML");
  const header = text.slice(0, 4096);
  if (/<!DOCTYPE/i.test(header) || /<!ENTITY/i.test(header)) {
    throw new LightBurnParseError("LightBurn XML must not contain DOCTYPE or ENTITY declarations");
  }

  const parsed = parseXmlDocument(text);
  if (parsed.root.name !== "LightBurnProject") {
    throw new LightBurnParseError(`Unexpected LightBurn root element <${parsed.root.name}>`);
  }

  const declared = parseLayers(parsed.root);
  const state: ParseState = {
    limits: {
      maxShapes: limits?.maxShapes ?? DEFAULT_LIGHTBURN_LIMITS.maxShapes,
      maxSegments: limits?.maxSegments ?? DEFAULT_LIGHTBURN_LIMITS.maxSegments,
    },
    declared,
    implicit: new Map(),
    paths: [],
    bounds: null,
    truncated: parsed.truncated,
    stopped: false,
    stats: { shapes: 0, skippedShapes: 0, segments: 0 },
    vertCache: new Map(),
    primCache: new Map(),
  };

  for (const node of parsed.root.children) {
    if (node.name !== "Shape") continue;
    if (processShape(state, node, null, null, 0)) break;
  }

  // Implicit layers can sit on indices below declared ones (a shape before a
  // CutSetting), so sort the combined list, not each source independently.
  const layers = [...declared.values(), ...state.implicit.values()].sort(
    (a, b) => a.index - b.index,
  );

  return {
    layers,
    paths: state.paths,
    bounds: state.bounds,
    thumbnail: parseThumbnail(parsed.root),
    truncated: state.truncated,
    stats: state.stats,
  };
}
