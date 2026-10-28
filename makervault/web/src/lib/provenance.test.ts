import { describe, expect, it } from "vitest";

import { sourceChipLabel, sourceHostLabel } from "./provenance";

describe("sourceHostLabel", () => {
  it("names the well-known print repositories", () => {
    expect(sourceHostLabel("https://www.printables.com/model/123-hydra")).toBe("Printables");
    expect(sourceHostLabel("https://www.thingiverse.com/thing:456")).toBe("Thingiverse");
    expect(sourceHostLabel("https://makerworld.com/en/models/789")).toBe("MakerWorld");
  });

  it("returns null for an unknown host so the caller can fall back", () => {
    expect(sourceHostLabel("https://cults3d.com/en/3d-model/hydra")).toBeNull();
  });

  it("returns null for an unparsable URL", () => {
    expect(sourceHostLabel("not a url")).toBeNull();
    expect(sourceHostLabel("")).toBeNull();
  });
});

describe("sourceChipLabel", () => {
  it("prefers the well-known host name", () => {
    expect(sourceChipLabel("https://www.printables.com/model/123-hydra")).toBe("Printables");
    expect(sourceChipLabel("https://makerworld.com/en/models/789")).toBe("MakerWorld");
  });

  it("falls back to the hostname of an unknown host", () => {
    expect(sourceChipLabel("https://cults3d.com/en/3d-model/hydra")).toBe("cults3d.com");
  });

  it("strips a leading www.", () => {
    expect(sourceChipLabel("https://www.example.org/thing")).toBe("example.org");
  });

  it("falls back to a generic label when the URL cannot be parsed", () => {
    expect(sourceChipLabel("not a url")).toBe("Source");
    expect(sourceChipLabel("")).toBe("Source");
  });
});
