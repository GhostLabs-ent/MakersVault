import { describe, expect, it } from "vitest";

import { extOf, is3mfAsset, isImageAsset, isModelAsset, typeLabelFor } from "./assetKinds";
import { formatDate } from "./format";

describe("extOf", () => {
  it("extracts the lowercase extension", () => {
    expect(extOf("photo.JPG")).toBe("jpg");
    expect(extOf("archive.tar.gz")).toBe("gz");
    expect(extOf("model.StL")).toBe("stl");
  });

  it("returns an empty string for dotless, trailing-dot and dotfile names", () => {
    expect(extOf("README")).toBe("");
    expect(extOf("backup.")).toBe("");
    expect(extOf(".gitignore")).toBe("");
  });
});

describe("isImageAsset", () => {
  it("detects browser-renderable image extensions, case-insensitively", () => {
    for (const filename of [
      "a.png",
      "b.jpg",
      "c.jpeg",
      "d.webp",
      "e.gif",
      "f.avif",
      "g.bmp",
      "H.PNG",
    ]) {
      expect(isImageAsset({ filename, mime: "" })).toBe(true);
    }
  });

  it("falls back to the mime type for dotless filenames", () => {
    expect(isImageAsset({ filename: "README", mime: "image/png" })).toBe(true);
    expect(isImageAsset({ filename: "README", mime: "" })).toBe(false);
  });

  it("rejects models and documents", () => {
    expect(isImageAsset({ filename: "benchy.stl", mime: "model/stl" })).toBe(false);
    expect(isImageAsset({ filename: "doc.pdf", mime: "application/pdf" })).toBe(false);
  });
});

describe("is3mfAsset", () => {
  it("detects 3MF by extension, case-insensitively", () => {
    expect(is3mfAsset({ filename: "benchy.3mf", mime: "" })).toBe(true);
    expect(is3mfAsset({ filename: "BENCHY.3MF", mime: "" })).toBe(true);
    expect(is3mfAsset({ filename: "benchy.stl", mime: "" })).toBe(false);
  });

  it("detects 3MF by mime when the filename is dotless", () => {
    expect(
      is3mfAsset({
        filename: "benchy",
        mime: "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
      }),
    ).toBe(true);
  });
});

describe("isModelAsset", () => {
  it("matches the slicer-openable extensions, case-insensitively", () => {
    for (const filename of ["a.stl", "b.3mf", "c.step", "d.stp", "e.obj", "F.STL"]) {
      expect(isModelAsset({ filename, mime: "" })).toBe(true);
    }
  });

  it("rejects images, documents and dotless names", () => {
    expect(isModelAsset({ filename: "a.png", mime: "image/png" })).toBe(false);
    expect(isModelAsset({ filename: "doc.pdf", mime: "application/pdf" })).toBe(false);
    expect(isModelAsset({ filename: "README", mime: "" })).toBe(false);
  });
});

describe("typeLabelFor", () => {
  it("uppercases the extension and falls back to FILE", () => {
    expect(typeLabelFor({ filename: "body.stl", mime: "" })).toBe("STL");
    expect(typeLabelFor({ filename: "photo.webp", mime: "" })).toBe("WEBP");
    expect(typeLabelFor({ filename: "README", mime: "" })).toBe("FILE");
  });
});

describe("formatDate", () => {
  it("formats an ISO timestamp as a short human date", () => {
    const out = formatDate("2026-01-02T10:20:30Z");
    expect(out).toBeTruthy();
    expect(out).toContain("2026");
    expect(out).not.toContain("Invalid");
  });

  it("returns an empty string for nonsense input", () => {
    expect(formatDate("not-a-date")).toBe("");
    expect(formatDate("")).toBe("");
  });
});
