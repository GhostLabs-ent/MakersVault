// @vitest-environment jsdom
//
// Acceptance test for `Mf-1vxh`: every deferred interaction re-mints its file
// grants. The grant machinery is the real thing — `mintFileGrants` from
// `../lib/api/grants` installs itself as the minter on import, exactly as it
// does in the app — and only the transport (`fetch`) is stubbed. Nothing here
// mocks `../lib/api` or `../lib/fileGrants`, so the production path
// (`useFileGrants` -> `primeGrants` -> `POST /file-grants` -> `fileUrl`) runs
// end to end.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Asset, AssetFile, AssetFileLimits } from "../lib/api";
import { mintFileGrants } from "../lib/api/grants";
import {
  configureGrantMinter,
  grantedFileUrl,
  resetFileGrants,
} from "../lib/fileGrants";

import AssetCard from "./asset-grid/AssetCard";
import type { AssetCardProps } from "./asset-grid/assetCardProps";
import AssetFilePreview from "./asset-grid/AssetFilePreview";
import { AssetPreviewModal } from "./asset-grid/preview";
import { useAssetActions } from "./asset-grid/useAssetActions";

/** The server's `FILE_GRANT_TTL_SECONDS`; a grant is dead after this long. */
const GRANT_TTL_SECONDS = 60;

/** Everything `POST /file-grants` was asked for, one entry per request. */
let mintRequests: string[][] = [];

/** Every minted URL gets a fresh `sig`, so a re-mint is distinguishable. */
let sigCounter = 0;

/** The `sig` query value of a rendered URL, or null when it carries none. */
function sigOf(url: string | null | undefined): string | null {
  if (!url) return null;
  const match = /[?&]sig=([^&]+)/.exec(url);
  return match ? match[1] : null;
}

/** A `Response`-shaped object: a real one is awkward to build under fake timers. */
function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (typeof body === "string" ? body : JSON.stringify(body)),
  };
}

const SUPPORTING_FILE: AssetFile = {
  id: "sf1",
  filename: "assembly.pdf",
  mime: "application/pdf",
  size: 2048,
  position: 0,
  url: "/asset/a1/files/sf1",
};

const FILE_LIMITS: AssetFileLimits = {
  count: 1,
  total_bytes: 2048,
  max_count: 10,
  max_file_bytes: 10_485_760,
  max_total_bytes: 104_857_600,
};

/**
 * The stub answers only the four endpoints these surfaces touch; `mintRequests`
 * is the record the tests assert on.
 */
function installFetchStub(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: unknown, init?: RequestInit) => {
      const url = String(input);
      const path = url.split("?")[0];
      const method = (init?.method ?? "GET").toUpperCase();

      if (method === "POST" && path.endsWith("/file-grants")) {
        const body = JSON.parse(String(init?.body ?? "{}")) as { paths?: string[] };
        const paths = Array.isArray(body.paths) ? body.paths : [];
        mintRequests.push([...paths]);
        return jsonResponse({
          grants: paths.map(path => ({
            path,
            url: `${path}${path.includes("?") ? "&" : "?"}sig=${sigCounter++}`,
            expires_at: Math.floor(Date.now() / 1000) + GRANT_TTL_SECONDS,
          })),
        });
      }
      if (/\/asset\/[^/]+\/files\/limits$/.test(path)) {
        return jsonResponse(FILE_LIMITS);
      }
      if (/\/asset\/[^/]+\/files$/.test(path)) {
        return jsonResponse([SUPPORTING_FILE]);
      }
      return jsonResponse({});
    }),
  );
}

/**
 * Drains the mint -> cache -> repaint chain. RTL's `waitFor`/`findBy*` poll on
 * timers and would hang under fake timers, so the tests flush microtasks
 * explicitly instead.
 */
async function flush(): Promise<void> {
  await act(async () => {
    for (let round = 0; round < 12; round += 1) {
      await Promise.resolve();
    }
  });
}

/** Advances the fake clock past the grant TTL, letting every armed timer fire. */
async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  await flush();
}

const PNG_ASSET: Asset = {
  id: "a1",
  name: "Cube",
  filename: "cube.png",
  mime: "image/png",
  size: 1024,
  tags: [],
  url: "/file/a1/cube.png",
  thumb_url: "/thumb/a1.jpg",
  supporting_file_count: 0,
};

const STL_ASSET: Asset = {
  id: "a2",
  name: "Cube",
  filename: "cube.stl",
  mime: "model/stl",
  size: 4096,
  tags: [],
  url: "/file/a2/cube.stl",
  thumb_url: "/thumb/a2.jpg",
  supporting_file_count: 0,
};

function cardProps(overrides: Partial<AssetCardProps> = {}): AssetCardProps {
  return {
    item: PNG_ASSET,
    canWrite: false,
    onSaveTags: vi.fn(),
    onSaveDetails: vi.fn(),
    onRename: vi.fn(),
    onPreview: vi.fn(),
    onDownloadSingle: vi.fn(),
    onDownloadByTag: vi.fn(),
    onDownloadSelected: vi.fn(),
    downloading: false,
    onDelete: vi.fn(),
    onAddToProject: vi.fn(),
    onMoveFolder: vi.fn(),
    folderOptions: [],
    moving: false,
    selected: false,
    onToggleSelected: vi.fn(),
    hasSelection: false,
    bulkDownloading: false,
    slicerEnabled: false,
    slicerLabel: "Orca",
    onOpenInSlicer: vi.fn(),
    engravingEnabled: false,
    engraverLabel: "LightBurn",
    onOpenInEngraving: vi.fn(),
    theme: "dark",
    previewMode: "automatic",
    onAssetChanged: vi.fn(),
    onForgetMissing: vi.fn(),
    onRescanMissing: vi.fn(),
    rescanning: false,
    onRequestConfirm: vi.fn(),
    ...overrides,
  } satisfies AssetCardProps;
}

function imgSrc(container: HTMLElement): string {
  const img = container.querySelector("img");
  if (!img) throw new Error("expected an <img>");
  return img.getAttribute("src") ?? "";
}

function downloadLink(): HTMLAnchorElement {
  return screen.getByRole("link", { name: "Download" }) as HTMLAnchorElement;
}

beforeEach(() => {
  vi.useFakeTimers();
  mintRequests = [];
  sigCounter = 0;
  resetFileGrants();
  configureGrantMinter(mintFileGrants);
  installFetchStub();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

afterAll(() => {
  configureGrantMinter(null);
  resetFileGrants();
});

describe("deferred file grants", () => {
  it("a virtualized-grid row remount mints for itself and ends up signed", async () => {
    // `AssetGridBody` keys rows by index, so a row that scrolls out unmounts its
    // cards and a row that scrolls back mounts them fresh — a remount, not a
    // re-render. That new mount has to mint for itself. The remount's first
    // paint is genuinely unsigned (the cache is empty and `fileUrl` is a
    // synchronous miss) and the browser does fire that request; this asserts the
    // end state, which is the contract. Only the two dialogs gate their body on
    // the first mint (ADR 0005, decision 10).
    const first = render(<AssetCard {...cardProps()} />);
    await flush();

    const firstSrc = imgSrc(first.container);
    expect(firstSrc.startsWith("http://localhost:8000/thumb/a1.jpg")).toBe(true);
    expect(sigOf(firstSrc)).not.toBeNull();
    expect(mintRequests).toHaveLength(1);
    expect([...mintRequests[0]].sort()).toEqual(["/file/a1/cube.png", "/thumb/a1.jpg"]);

    // Unmounting drops the card's refresh timer; 61 s later the cache is cold.
    first.unmount();
    await flush();
    await advance(61_000);
    expect(grantedFileUrl("/thumb/a1.jpg")).toBeNull();

    const second = render(<AssetCard {...cardProps()} />);
    await flush();

    expect(mintRequests).toHaveLength(2);
    expect(mintRequests[1]).toContain("/thumb/a1.jpg");
    expect(mintRequests[1]).toContain("/file/a1/cube.png");

    const secondSrc = imgSrc(second.container);
    expect(sigOf(secondSrc)).not.toBeNull();
    expect(sigOf(secondSrc)).not.toBe(sigOf(firstSrc));
  });

  it("a card that re-renders while mounted after the minute keeps a signed thumbnail", async () => {
    const view = render(<AssetCard {...cardProps()} />);
    await flush();

    const firstSrc = imgSrc(view.container);
    expect(sigOf(firstSrc)).not.toBeNull();

    // The mounted card's silent refresh re-mints without repainting the <img>.
    await advance(61_000);
    expect(imgSrc(view.container)).toBe(firstSrc);
    expect(grantedFileUrl("/thumb/a1.jpg")).not.toBeNull();

    // A selection toggle is the regression: the card re-reads the cache on every
    // render, so a warm cache is what keeps `src` signed.
    view.rerender(<AssetCard {...cardProps({ selected: true })} />);
    await flush();

    const rerenderedSrc = imgSrc(view.container);
    expect(sigOf(rerenderedSrc)).not.toBeNull();
    expect(sigOf(rerenderedSrc)).not.toBe(sigOf(firstSrc));
  });

  it("a preview dialog opened after the grant expired gates its body on the first mint", async () => {
    // Nothing is mounted, so the clock passes any earlier expiry unchecked.
    await advance(61_000);

    const view = render(<AssetPreviewModal asset={PNG_ASSET} theme="dark" onClose={() => {}} />);
    expect(screen.getByText("Preparing preview...")).toBeTruthy();
    expect(view.container.querySelector("img")).toBeNull();

    await flush();
    const img = view.container.querySelector("img");
    expect(sigOf(img?.getAttribute("src"))).not.toBeNull();

    const link = downloadLink();
    const firstHref = link.href;
    expect(sigOf(firstHref)).not.toBeNull();
    expect(link.getAttribute("download")).toBe(PNG_ASSET.filename);

    // The body is rendered by the silent variant, so its src is captured now.
    const bodySrc = imgSrc(view.container);

    // Held open past the TTL: the live anchor re-mints, the modal body does not repaint.
    await advance(61_000);
    const refreshed = downloadLink();
    expect(sigOf(refreshed.href)).not.toBeNull();
    expect(sigOf(refreshed.href)).not.toBe(sigOf(firstHref));
    // A mounted model/image keeps the src it painted with: re-rendering it would
    // re-download bytes the browser already holds for a merely re-signed URL.
    expect(imgSrc(view.container)).toBe(bodySrc);
  });

  it("the supporting-file dialog's Download anchor re-mints rather than extending", async () => {
    render(<AssetFilePreview assetId="a1" file={SUPPORTING_FILE} onClose={() => {}} />);
    await flush();

    const link = downloadLink();
    expect(link.getAttribute("href")).toContain("sig=");
    expect(link.getAttribute("download")).toBe(SUPPORTING_FILE.filename);
    const firstSig = sigOf(link.href);

    await advance(61_000);

    const refreshed = downloadLink();
    expect(sigOf(refreshed.href)).not.toBeNull();
    expect(sigOf(refreshed.href)).not.toBe(firstSig);
  });

  it("the card's supporting-file row Download anchor re-mints", async () => {
    render(<AssetCard {...cardProps({ item: { ...PNG_ASSET, supporting_file_count: 1 } })} />);
    await flush();

    fireEvent.click(screen.getByRole("button", { name: /supporting files/i }));
    await flush();
    screen.getByRole("button", { name: `Preview ${SUPPORTING_FILE.filename}` });

    const link = downloadLink();
    expect(link.getAttribute("href")).toContain("sig=");
    expect(link.getAttribute("download")).toBe(SUPPORTING_FILE.filename);
    const firstSig = sigOf(link.href);

    await advance(61_000);

    const refreshed = downloadLink();
    expect(sigOf(refreshed.href)).not.toBeNull();
    expect(sigOf(refreshed.href)).not.toBe(firstSig);
  });

  it("the slicer handoff re-mints at click time, not at fetch time", async () => {
    function SlicerHarness({ asset }: { asset: Asset }) {
      const actions = useAssetActions({
        items: [asset],
        setItems: () => {},
        setPreviewItem: () => {},
        refresh: async () => {},
        handleApiError: () => false,
        slicerSettings: { enabled: true, selected: "orca" },
        engravingSettings: { enabled: false, selected: "lightburn" },
        selectedIds: new Set<string>(),
        bulkSetTags: async () => {},
        onRequestDelete: () => {},
        onAddToProject: () => {},
      });
      return (
        <button type="button" onClick={() => void actions.openInSlicer(asset)}>
          Open in slicer
        </button>
      );
    }

    // The cache is cold and the clock is past any earlier expiry.
    await advance(61_000);

    render(<SlicerHarness asset={STL_ASSET} />);
    await flush();
    const mintsBeforeClick = mintRequests.length;

    // jsdom prints "Not implemented: navigation" when the handler assigns
    // `window.location.href`; that noise is expected and is not asserted on.
    fireEvent.click(screen.getByRole("button", { name: "Open in slicer" }));
    await flush();

    expect(mintRequests.length).toBeGreaterThan(mintsBeforeClick);
    expect(mintRequests[mintRequests.length - 1]).toContain(STL_ASSET.url);
    expect(grantedFileUrl(STL_ASSET.url)).not.toBeNull();
  });
});
