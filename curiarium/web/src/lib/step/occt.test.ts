import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { init } = vi.hoisted(() => ({ init: vi.fn() }));

vi.mock("occt-import-js", () => ({ default: init }));
vi.mock("occt-import-js/dist/occt-import-js.wasm?url", () => ({ default: "/occt.wasm" }));
vi.mock("occt-import-js/dist/occt-import-js-worker.js?url", () => ({
  default: "/occt-worker.js",
}));

import { getOcct, resetOcctForTests } from "./occt";

type InitOptions = { locateFile: (file: string) => string };

function occtModule(): { ReadStepFile: ReturnType<typeof vi.fn> } {
  return { ReadStepFile: vi.fn() };
}

function initOptions(call: number): InitOptions {
  const options = init.mock.calls[call]?.[0] as InitOptions | undefined;
  if (!options) throw new Error(`occt init call ${call} never happened`);
  return options;
}

beforeEach(() => {
  resetOcctForTests();
  init.mockReset();
  init.mockResolvedValue(occtModule());
});

afterEach(() => {
  resetOcctForTests();
  vi.restoreAllMocks();
});

describe("getOcct", () => {
  it("initialises occt once for concurrent and later callers", async () => {
    const module = occtModule();
    init.mockResolvedValue(module);

    const [first, second] = await Promise.all([getOcct(), getOcct()]);
    const third = await getOcct();

    expect(init).toHaveBeenCalledTimes(1);
    expect(first).toBe(module);
    expect(second).toBe(module);
    expect(third).toBe(module);
  });

  it("points occt's wasm and worker files at the bundler URLs", async () => {
    await getOcct();

    const { locateFile } = initOptions(0);
    expect(locateFile("occt-import-js.wasm")).toBe("/occt.wasm");
    expect(locateFile("occt-import-js.worker.js")).toBe("/occt-worker.js");
    expect(locateFile("something-else.js")).toBe("something-else.js");
  });

  it("initialises again after resetOcctForTests", async () => {
    const module = occtModule();
    init.mockResolvedValue(module);

    await getOcct();
    await getOcct();
    expect(init).toHaveBeenCalledTimes(1);

    resetOcctForTests();
    await expect(getOcct()).resolves.toBe(module);
    expect(init).toHaveBeenCalledTimes(2);
  });

  it("does not memoise a failed initialisation", async () => {
    const module = occtModule();
    init.mockRejectedValueOnce(new Error("wasm fetch failed")).mockResolvedValue(module);

    await expect(getOcct()).rejects.toThrow("wasm fetch failed");
    await expect(getOcct()).resolves.toBe(module);

    expect(init).toHaveBeenCalledTimes(2);
  });
});
