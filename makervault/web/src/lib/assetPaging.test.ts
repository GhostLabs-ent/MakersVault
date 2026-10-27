import { describe, expect, it } from "vitest";

import { MAX_ASSET_PAGE_LIMIT, refreshWindow } from "./assetPaging";


describe("asset list refresh windows", () => {
  it("loads a single page from the top for a plain refresh", () => {
    expect(refreshWindow(120, 20)).toEqual({ limit: 20, offset: 0 });
  });

  it("still loads a single page when preserving pages but nothing is loaded", () => {
    expect(refreshWindow(0, 20, true)).toEqual({ limit: 20, offset: 0 });
  });

  it("re-requests every loaded page when preserving pages", () => {
    expect(refreshWindow(120, 20, true)).toEqual({ limit: 120, offset: 0 });
  });

  it("clamps the preserved window at the API page limit", () => {
    expect(refreshWindow(5000, 20, true)).toEqual({
      limit: MAX_ASSET_PAGE_LIMIT,
      offset: 0,
    });
  });

  it("never requests a non-zero offset", () => {
    expect(refreshWindow(0, 20).offset).toBe(0);
    expect(refreshWindow(7, 20).offset).toBe(0);
    expect(refreshWindow(7, 20, true).offset).toBe(0);
    expect(refreshWindow(9999, 20, true).offset).toBe(0);
  });
});
