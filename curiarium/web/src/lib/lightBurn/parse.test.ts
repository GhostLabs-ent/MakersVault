import { describe, expect, it } from "vitest";

import {
  DEFAULT_LIGHTBURN_LIMITS,
  LIGHTBURN_MAX_BYTES,
  LightBurnParseError,
  parseLightBurn,
} from "./parse";

function encode(xml: string): Uint8Array {
  return new TextEncoder().encode(xml);
}

function project(body: string, formatVersion = 1): Uint8Array {
  return encode(
    `<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="1.7" FormatVersion="${formatVersion}">${body}</LightBurnProject>`,
  );
}

const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=";

function cutSetting(index: number, name: string, extra = ""): string {
  return `<CutSetting type="Cut"><index Value="${index}"/><name Value="${name}"/>${extra}</CutSetting>`;
}

function pathNumbers(d: string): number[] {
  return d
    .split(/\s+/)
    .filter(token => token !== "M" && token !== "L" && token !== "Z")
    .map(Number);
}

function pointCommandCount(d: string): number {
  return d.split(/\s+/).filter(token => token === "M" || token === "L").length;
}

describe("parseLightBurn", () => {
  it("parses a compact .lbrn2 project with thumbnail, layers and geometry", () => {
    const xml = project(
      [
        `<Thumbnail Source="${PNG_BASE64}"/>`,
        cutSetting(0, "Outer Cut", '<minPower Value="3"/><maxPower Value="80"/><speed Value="10"/>'),
        `<CutSetting type="Scan"><index Value="1"/><name Value="Filled"/><doOutput Value="0"/><hide Value="1"/></CutSetting>`,
        `<Shape Type="Rect" CutIndex="0" W="10" H="20"><XForm>1 0 0 1 5 5</XForm></Shape>`,
        `<Shape Type="Ellipse" CutIndex="1" Rx="4" Ry="2"><XForm>1 0 0 1 0 0</XForm></Shape>`,
        `<Shape Type="Path" CutIndex="0" VertID="5" PrimID="5">`,
        `<VertList>V0 0 V10 0 V10 10</VertList>`,
        `<PrimList>L0 1L1 2L2 0</PrimList>`,
        `</Shape>`,
      ].join(""),
    );

    const model = parseLightBurn(xml);

    expect(model.layers).toHaveLength(2);
    expect(model.layers[0]).toMatchObject({
      index: 0,
      name: "Outer Cut",
      kind: "Cut",
      color: "#000000",
      isTool: false,
      isHidden: false,
      shapeCount: 2,
    });
    expect(model.layers[1]).toMatchObject({
      index: 1,
      name: "Filled",
      kind: "Scan",
      color: "#0000FF",
      isHidden: true,
      shapeCount: 1,
    });
    expect(model.paths).toHaveLength(3);
    expect(model.paths.every(path => path.d.length > 0)).toBe(true);
    expect(model.paths.some(path => path.d.includes("Z"))).toBe(true);
    expect(model.bounds).not.toBeNull();
    const bounds = model.bounds!;
    expect([bounds.minX, bounds.minY, bounds.maxX, bounds.maxY].every(Number.isFinite)).toBe(true);
    expect(model.truncated).toBe(false);
    expect(model.thumbnail?.mime).toBe("image/png");
    expect(Array.from(model.thumbnail!.data.slice(0, 8))).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  });

  it("parses legacy verbose .lbrn vertex and primitive elements", () => {
    const xml = project(
      [
        cutSetting(0, "Legacy"),
        `<Shape Type="Path" CutIndex="0">`,
        `<XForm>1 0 0 1 0 0</XForm>`,
        `<V vx="0" vy="0" c0x="1" c0y="2" c1x="3" c1y="4"/>`,
        `<V vx="10" vy="0" c0x="5" c0y="6" c1x="7" c1y="8"/>`,
        `<V vx="10" vy="10"/>`,
        `<P T="B" p0="0" p1="1"/>`,
        `<P T="L" p0="1" p1="2"/>`,
        `<P T="L" p0="2" p1="0"/>`,
        `</Shape>`,
      ].join(""),
      0,
    );

    const model = parseLightBurn(xml);

    expect(model.paths).toHaveLength(1);
    expect(model.paths[0].d).toMatch(/^M /);
    expect(model.paths[0].d).toContain("L ");
    expect(model.paths[0].d.endsWith("Z")).toBe(true);
    expect(model.stats.segments).toBeGreaterThan(0);
  });

  it("reuses deduplicated VertID/PrimID caches independently and skips missing ids", () => {
    const xml = project(
      [
        cutSetting(0, "Dedup"),
        // Defines both caches.
        `<Shape Type="Path" CutIndex="0" VertID="10" PrimID="20">`,
        `<VertList>V0 0 V10 0 V10 10</VertList>`,
        `<PrimList>L0 1L1 2L2 0</PrimList>`,
        `</Shape>`,
        // Defines only the prim cache; geometry-less shapes may still register ids.
        `<Shape Type="Path" CutIndex="0" PrimID="21">`,
        `<PrimList>L0 2L2 1L1 0</PrimList>`,
        `</Shape>`,
        // Reuses both ids.
        `<Shape Type="Path" CutIndex="0" VertID="10" PrimID="20"/>`,
        // Reuses a vertex id and a prim id defined by different shapes.
        `<Shape Type="Path" CutIndex="0" VertID="10" PrimID="21"/>`,
        // References a missing vertex id.
        `<Shape Type="Path" CutIndex="0" VertID="99" PrimID="20"/>`,
      ].join(""),
    );

    const model = parseLightBurn(xml);

    expect(model.paths).toHaveLength(3);
    expect(model.stats.shapes).toBe(5);
    expect(model.stats.skippedShapes).toBe(1);
    expect(model.truncated).toBe(true);
  });

  it("composes group and child XForms in parent-after-child order with Y negation", () => {
    const xml = project(
      [
        cutSetting(0, "Groups"),
        `<Shape Type="Group" CutIndex="0">`,
        `<XForm>0 1 -1 0 10 20</XForm>`,
        `<Children>`,
        `<Shape Type="Rect" CutIndex="0" W="2" H="4">`,
        `<XForm>1 0 0 1 5 0</XForm>`,
        `</Shape>`,
        `</Children>`,
        `</Shape>`,
      ].join(""),
    );

    const model = parseLightBurn(xml);
    expect(model.paths).toHaveLength(1);
    const d = model.paths[0].d;
    expect(d.endsWith("Z")).toBe(true);
    const numbers = pathNumbers(d);
    expect(numbers).toHaveLength(8);
    const expected = [12, -24, 12, -26, 8, -26, 8, -24];
    for (let i = 0; i < expected.length; i += 1) {
      expect(numbers[i]).toBeCloseTo(expected[i], 3);
    }
  });

  it("keeps every vertex of a closed rectangle after the Y flip", () => {
    const xml = project(
      [
        cutSetting(0, "Rect"),
        `<Shape Type="Rect" CutIndex="0" W="10" H="20"><XForm>1 0 0 1 0 0</XForm></Shape>`,
      ].join(""),
    );

    const model = parseLightBurn(xml);

    expect(model.paths).toHaveLength(1);
    expect(model.paths[0].d).toBe("M -5 10 L 5 10 L 5 -10 L -5 -10 Z");
    expect(pointCommandCount(model.paths[0].d)).toBe(4);
  });

  it("keeps every vertex of an explicit closing prim loop", () => {
    const xml = project(
      [
        cutSetting(0, "Loop"),
        `<Shape Type="Path" CutIndex="0"><VertList>V0 0 V10 0 V10 -10</VertList><PrimList>L0 1L1 2L2 0</PrimList></Shape>`,
      ].join(""),
    );

    const model = parseLightBurn(xml);

    expect(model.paths).toHaveLength(1);
    expect(model.paths[0].d).toBe("M 0 0 L 10 0 L 10 10 Z");
    expect(pointCommandCount(model.paths[0].d)).toBe(3);
  });

  it("rejects unsafe or non-LightBurn documents", () => {
    expect(() => parseLightBurn(encode("<!DOCTYPE foo><LightBurnProject/>"))).toThrow(LightBurnParseError);
    expect(() => parseLightBurn(encode('<!ENTITY x "y"><LightBurnProject/>'))).toThrow(LightBurnParseError);
    expect(() => parseLightBurn(encode("this is not xml"))).toThrow(LightBurnParseError);
    expect(() => parseLightBurn(encode("<NotALightBurnProject/>"))).toThrow(LightBurnParseError);
  });

  it("decodes numeric XML entities in attributes", () => {
    const xml = project(cutSetting(0, "a&#10;b"));
    const model = parseLightBurn(xml);
    expect(model.layers[0].name).toBe("a\nb");
  });

  it("falls back to grey for undeclared layers and keeps palette and hidden flags", () => {
    const xml = project(
      [
        `<CutSetting type="Cut"><index Value="7"/><name Value="Magenta"/><doOutput Value="0"/></CutSetting>`,
        `<Shape Type="Rect" CutIndex="42" W="1" H="1"/>`,
        `<Shape Type="Rect" CutIndex="7" W="1" H="1"/>`,
      ].join(""),
    );

    const model = parseLightBurn(xml);
    const magenta = model.layers.find(layer => layer.index === 7)!;
    const implicit = model.layers.find(layer => layer.index === 42)!;

    expect(magenta.color).toBe("#FF00FF");
    expect(magenta.isHidden).toBe(true);
    expect(implicit).toMatchObject({
      name: "Layer 42",
      color: "#9CA3AF",
      isTool: true,
      isHidden: false,
      shapeCount: 1,
    });
  });

  it("stops at the segment budget and stays valid", () => {
    const xml = project(
      [
        cutSetting(0, "Budget"),
        `<Shape Type="Ellipse" CutIndex="0" Rx="5" Ry="3"/>`,
        `<Shape Type="Rect" CutIndex="0" W="2" H="2"/>`,
      ].join(""),
    );

    const model = parseLightBurn(xml, { maxSegments: 5 });

    expect(model.truncated).toBe(true);
    expect(model.stats.segments).toBeLessThanOrEqual(6);
    expect(model.paths.length).toBe(1);
    expect(model.paths[0].d.length).toBeGreaterThan(0);
  });

  it("rejects inputs over the byte limit before parsing", () => {
    const oversized = new Uint8Array(LIGHTBURN_MAX_BYTES + 1);
    expect(() => parseLightBurn(oversized)).toThrow(LightBurnParseError);
  });

  it("honours LineClosed and LineOpen shorthand primitives", () => {
    const xml = project(
      [
        cutSetting(0, "Shorthand"),
        `<Shape Type="Path" CutIndex="0"><VertList>V0 0 V10 0 V10 -10</VertList><PrimList>LineClosed</PrimList></Shape>`,
        `<Shape Type="Path" CutIndex="0"><VertList>V0 0 V10 0 V10 -10</VertList><PrimList>LineOpen</PrimList></Shape>`,
      ].join(""),
    );

    const model = parseLightBurn(xml, DEFAULT_LIGHTBURN_LIMITS);

    expect(model.paths).toHaveLength(2);
    expect(model.paths[0].d).toBe("M 0 0 L 10 0 L 10 10 Z");
    expect(model.paths[1].d).toBe("M 0 0 L 10 0 L 10 10");
    expect(pointCommandCount(model.paths[0].d)).toBe(3);
  });
});
