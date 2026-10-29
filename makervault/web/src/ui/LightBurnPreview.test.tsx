// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import LightBurnPreview, { clearLightBurnModelCacheForTests } from "./LightBurnPreview";
import { lightBurnUrlCache } from "../lib/lightBurn/urlCache";

/**
 * 45-byte minimal PNG: signature, IHDR chunk (13-byte payload), IEND chunk.
 * Enough for the parser's magic-number sniff to recognise `image/png`.
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

const PNG_BASE64 = btoa(String.fromCharCode(...PNG_FIXTURE));

function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  if (bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength) {
    return bytes.buffer as ArrayBuffer;
  }
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}

function project(body: string): string {
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<LightBurnProject AppVersion="1.7" FormatVersion="1">',
    body,
    "</LightBurnProject>",
  ].join("");
}

const VECTOR_XML = project(
  [
    '<CutSetting type="Cut"><index Value="0"/><name Value="Outer Cut"/></CutSetting>',
    '<CutSetting type="Cut"><index Value="1"/><name Value="Hidden Layer"/><doOutput Value="0"/></CutSetting>',
    '<Shape Type="Rect" CutIndex="0" W="10" H="20"><XForm>1 0 0 1 0 0</XForm></Shape>',
    '<Shape Type="Ellipse" CutIndex="1" Rx="4" Ry="2"><XForm>1 0 0 1 0 0</XForm></Shape>',
  ].join(""),
);

const THUMBNAIL_XML = project(`<Thumbnail Source="${PNG_BASE64}"/>`);

const EMPTY_XML = project("");

const MB = 1024 * 1024;

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

function mockFile(
  xml: string,
  contentLength?: number | null,
  bodyBytes?: Uint8Array,
): ReturnType<typeof vi.fn> {
  const bytes = bodyBytes ?? new TextEncoder().encode(xml);
  const header = contentLength === undefined ? String(bytes.byteLength) : contentLength;
  const arrayBuffer = vi.fn(async () => toArrayBuffer(bytes));
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-length" && header !== null ? String(header) : null,
    },
    arrayBuffer,
  });
  return arrayBuffer;
}

type LightBurnPreviewProps = Parameters<typeof LightBurnPreview>[0];

function renderCard(overrides: Partial<LightBurnPreviewProps> = {}) {
  return render(
    <LightBurnPreview
      url="/api/assets/lb/file"
      assetId="lb"
      filename="preview.lbrn2"
      imgClass="w-full h-full object-cover"
      {...overrides}
    />,
  );
}

beforeEach(() => {
  observerCallback = null;
  observedTargets.length = 0;
  objectUrlCount = 0;
  clearLightBurnModelCacheForTests();
  vi.stubGlobal("Worker", undefined);

  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);

  URL.createObjectURL = vi.fn(
    () => `blob:mock-${(objectUrlCount += 1)}`,
  ) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  lightBurnUrlCache.dispose();

  mockFile(VECTOR_XML);
});

afterEach(() => {
  cleanup();
  lightBurnUrlCache.dispose();
  clearLightBurnModelCacheForTests();
  vi.unstubAllGlobals();
  URL.createObjectURL = originalCreateObjectURL;
  URL.revokeObjectURL = originalRevokeObjectURL;
});

describe("LightBurnPreview lazy loading", () => {
  it("does not fetch until the card is near the viewport", async () => {
    const { container } = renderCard({ url: "/api/assets/lb-lazy/file", assetId: "lb-lazy" });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText("Waiting to generate preview...")).toBeTruthy();
    expect(observedTargets.length).toBe(1);

    fireIntersect();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(container.querySelector("svg")).not.toBeNull());
  });

  it("loads immediately when IntersectionObserver is unavailable", async () => {
    vi.stubGlobal("IntersectionObserver", undefined);

    const { container } = renderCard({ url: "/api/assets/lb-no-io/file", assetId: "lb-no-io" });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(container.querySelector("svg")).not.toBeNull());
  });
});

describe("LightBurnPreview vector rendering", () => {
  it("renders a path per visible layer and hides the file's hidden layers", async () => {
    const { container } = renderCard({ url: "/api/assets/lb-vector/file", assetId: "lb-vector" });

    fireIntersect();

    const path = await waitFor(() => {
      const found = container.querySelector('path[data-layer="0"]');
      expect(found).not.toBeNull();
      return found;
    });
    expect(path?.getAttribute("stroke")).toBe("#000000");
    expect(container.querySelector('path[data-layer="1"]')).toBeNull();
  });

  it("toggles layers from the modal panel", async () => {
    const { container } = renderCard({
      url: "/api/assets/lb-modal/file",
      assetId: "lb-modal",
      variant: "modal",
    });

    const normalToggle = await screen.findByRole("checkbox", { name: "Outer Cut" });
    const hiddenToggle = await screen.findByRole("checkbox", { name: "Hidden Layer" });
    // The file's hidden flags seed the toggles in a follow-up effect.
    await waitFor(() => expect((hiddenToggle as HTMLInputElement).checked).toBe(false));
    expect((normalToggle as HTMLInputElement).checked).toBe(true);

    const svg = screen.getByRole("img", { name: "preview.lbrn2" });
    expect(svg.tagName.toLowerCase()).toBe("svg");
    expect(container.querySelector('path[data-layer="0"]')).not.toBeNull();
    expect(container.querySelector('path[data-layer="1"]')).toBeNull();

    fireEvent.click(normalToggle);
    expect(container.querySelector('path[data-layer="0"]')).toBeNull();

    fireEvent.click(hiddenToggle);
    expect(container.querySelector('path[data-layer="1"]')).not.toBeNull();
  });
});

describe("LightBurnPreview thumbnail fallback", () => {
  it("renders the embedded thumbnail with async decoding", async () => {
    mockFile(THUMBNAIL_XML);
    renderCard({ url: "/api/assets/lb-thumb/file", assetId: "lb-thumb" });

    fireIntersect();

    const img = await screen.findByAltText("preview.lbrn2");
    expect(img.getAttribute("decoding")).toBe("async");
    expect(img.getAttribute("src")).toMatch(/^blob:mock-/);
  });
});

describe("LightBurnPreview guards", () => {
  it("blocks files above the hard size limit without fetching", () => {
    renderCard({
      url: "/api/assets/lb-huge/file",
      assetId: "lb-huge",
      size: 33 * MB,
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(observerCallback).toBeNull();
    expect(screen.getByText(/too large to preview/i)).toBeTruthy();
    expect(screen.getByText(/Download it instead/i)).toBeTruthy();
  });

  it("blocks at fetch time when Content-Length exceeds the limit without reading the body", async () => {
    const arrayBuffer = mockFile(VECTOR_XML, 33 * MB);
    const { container } = renderCard({
      url: "/api/assets/lb-declared-huge/file",
      assetId: "lb-declared-huge",
    });

    fireIntersect();

    await screen.findByText(/too large to preview/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(arrayBuffer).not.toHaveBeenCalled();
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.queryByText("Preview unavailable")).toBeNull();
  });

  it("blocks when the served body exceeds the limit without a Content-Length", async () => {
    const arrayBuffer = mockFile(VECTOR_XML, null, new Uint8Array(33 * MB));
    const { container } = renderCard({
      url: "/api/assets/lb-undeclared-huge/file",
      assetId: "lb-undeclared-huge",
    });

    fireIntersect();

    await screen.findByText(/too large to preview/i);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(arrayBuffer).toHaveBeenCalledTimes(1);
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.queryByText("Preview unavailable")).toBeNull();
  });

  it("parses large-but-allowed files with a visible warning", async () => {
    const { container } = renderCard({
      url: "/api/assets/lb-large/file",
      assetId: "lb-large",
      size: 10 * MB,
    });

    fireIntersect();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(container.querySelector("svg")).not.toBeNull());
    expect(screen.getByText(/Large file/)).toBeTruthy();
    expect(screen.getByText(/simplified/i)).toBeTruthy();
  });

  it("does not fetch when previews are disabled on a card", () => {
    renderCard({
      url: "/api/assets/lb-disabled/file",
      assetId: "lb-disabled",
      mode: "disabled",
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(observerCallback).toBeNull();
    expect(screen.getByText("Preview generation disabled")).toBeTruthy();
  });

  it("waits for the Generate preview click in on-demand mode", async () => {
    const { container } = renderCard({
      url: "/api/assets/lb-demand/file",
      assetId: "lb-demand",
      mode: "on-demand",
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(observerCallback).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Generate preview" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(container.querySelector("svg")).not.toBeNull());
  });
});

describe("LightBurnPreview empty previews", () => {
  it("shows Preview unavailable when there is no geometry or thumbnail", async () => {
    mockFile(EMPTY_XML);
    const { container } = renderCard({ url: "/api/assets/lb-empty/file", assetId: "lb-empty" });

    fireIntersect();

    await screen.findByText("Preview unavailable");
    expect(container.querySelector("svg")).toBeNull();
  });
});
