// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";

import LightBurnPreview from "./LightBurnPreview";

/**
 * 45-byte minimal PNG: signature, IHDR chunk (13-byte payload), IEND chunk.
 * `extractPng` walks exactly these chunks, so the embedded-image path succeeds
 * without ever reaching the zip/fflate fallback.
 */
const PNG_FIXTURE = new Uint8Array([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
  0x00, 0x00, 0x00, 0x0d,
  0x49, 0x48, 0x44, 0x52,
  0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00,
  0x49, 0x45, 0x4e, 0x44,
  0x00, 0x00, 0x00, 0x00,
]);

let observerCallback: IntersectionObserverCallback | null = null;
const observedTargets: Element[] = [];

class FakeIntersectionObserver {
  constructor(callback: IntersectionObserverCallback) {
    observerCallback = callback;
  }
  observe(target: Element) {
    observedTargets.push(target);
  }
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

function fireIntersect() {
  if (!observerCallback) throw new Error("IntersectionObserver was never constructed");
  act(() => {
    observerCallback?.(
      [{ isIntersecting: true } as IntersectionObserverEntry],
      {} as IntersectionObserver,
    );
  });
}

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

let fetchMock: ReturnType<typeof vi.fn>;
let objectUrlCount = 0;

beforeEach(() => {
  observerCallback = null;
  observedTargets.length = 0;
  objectUrlCount = 0;

  fetchMock = vi.fn(async () => ({
    ok: true,
    status: 200,
    arrayBuffer: async () => PNG_FIXTURE.buffer.slice(0),
  }));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);

  URL.createObjectURL = vi.fn(
    () => `blob:mock-${(objectUrlCount += 1)}`,
  ) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  URL.createObjectURL = originalCreateObjectURL;
  URL.revokeObjectURL = originalRevokeObjectURL;
});

describe("LightBurnPreview lazy loading", () => {
  it("does not fetch until the card is near the viewport", async () => {
    render(
      <LightBurnPreview
        url="/api/assets/lb-lazy/file"
        assetId="lb-lazy"
        filename="lazy.lbrn2"
        imgClass="w-full h-full object-cover"
      />,
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText("Waiting to generate preview...")).toBeTruthy();
    expect(observedTargets.length).toBe(1);

    fireIntersect();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await screen.findByAltText("lazy.lbrn2");
  });

  it("renders the preview with async decoding once loaded", async () => {
    render(
      <LightBurnPreview
        url="/api/assets/lb-decoding/file"
        assetId="lb-decoding"
        filename="decoding.lbrn2"
        imgClass="w-full h-full object-cover"
      />,
    );

    fireIntersect();

    const img = await screen.findByAltText("decoding.lbrn2");
    expect(img.getAttribute("decoding")).toBe("async");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("loads immediately when IntersectionObserver is unavailable", async () => {
    vi.stubGlobal("IntersectionObserver", undefined);

    render(
      <LightBurnPreview
        url="/api/assets/lb-no-io/file"
        assetId="lb-no-io"
        filename="no-io.lbrn"
        imgClass="w-full h-full object-cover"
      />,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await screen.findByAltText("no-io.lbrn");
  });
});
