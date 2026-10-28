// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

// Only the network layer is mocked: the real `useUpload`/`ZipImportModal` prompt
// and the real toast store are driven end to end, exactly as a user would.
vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {
    constructor(message = "Unauthorized") {
      super(message);
      this.name = "UnauthorizedError";
    }
  },
  createFolder: vi.fn(),
  importFromLink: vi.fn(),
  importToProject: vi.fn(),
  importZipFromLink: vi.fn(),
  inspectImportLink: vi.fn(),
  listImportZipEntries: vi.fn(),
  listProjects: vi.fn(),
  uploadAsset: vi.fn(),
}));

import type { Asset } from "../lib/api";
import { importFromLink, importZipFromLink, inspectImportLink, listImportZipEntries } from "../lib/api";
import { resetToasts } from "../lib/toast";
import Toaster from "./Toaster";
import UploadBar from "./UploadBar";

const importFromLinkMock = vi.mocked(importFromLink);
const importZipFromLinkMock = vi.mocked(importZipFromLink);
const inspectImportLinkMock = vi.mocked(inspectImportLink);
const listImportZipEntriesMock = vi.mocked(listImportZipEntries);

const LINK_URL = "https://www.printables.com/model/1-bundle";
const THINGIVERSE_URL = "https://www.thingiverse.com/thing:1";
const LINK_INPUT = "Paste model link (MakerWorld, Printables, Thingiverse...)";

function asset(name: string): Asset {
  return {
    id: `asset-${name}`,
    name,
    filename: name,
    mime: "model/stl",
    size: 1,
    tags: [],
    url: `/assets/${name}`,
    supporting_file_count: 0,
  };
}

/** The toaster, scoped so modal text can never satisfy a toast assertion. */
function toaster() {
  return within(screen.getByTestId("toaster"));
}

function renderUploadBar() {
  const onUploaded = vi.fn();
  render(
    <>
      <UploadBar onUploaded={onUploaded} />
      <Toaster />
    </>,
  );
  return { onUploaded };
}

function typeLink(url: string) {
  fireEvent.change(screen.getByPlaceholderText(LINK_INPUT), { target: { value: url } });
}

/** Type a link, inspect it as a zip, then choose "Import and unzip" + "Import selected". */
async function importSelectedFromZip() {
  typeLink(LINK_URL);
  fireEvent.click(screen.getByRole("button", { name: "Import link" }));
  fireEvent.click(await screen.findByRole("button", { name: "Import and unzip" }));
  fireEvent.click(await screen.findByRole("button", { name: "Import selected" }));
}

/** The zip prompt only renders once `inspectImportLink` resolved. */
function mockZipLink() {
  inspectImportLinkMock.mockResolvedValue({
    filename: "bundle.zip",
    mime: "application/zip",
    is_zip: true,
  });
  listImportZipEntriesMock.mockResolvedValue({
    filename: "bundle.zip",
    entries: [
      { path: "ok.stl", size: 1 },
      { path: "x.stl", size: 1 },
    ],
  });
}

describe("UploadBar link import", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    resetToasts();
    // `vi.resetAllMocks` (not `clearAllMocks`): a leftover `mockResolvedValueOnce`
    // queue from an earlier test would otherwise shift the next test's call order.
    vi.resetAllMocks();
    // `importFromUrl` reports failures with console.error; keep test output clean.
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    consoleError.mockRestore();
  });

  it("reports a partial zip import with its failed entries and a retry action", async () => {
    mockZipLink();
    importZipFromLinkMock.mockResolvedValue({ assets: [asset("ok.stl")], failed: ["x.stl"] });
    renderUploadBar();

    await importSelectedFromZip();

    await waitFor(() => expect(toaster().getAllByRole("alert")).toHaveLength(1));
    const alert = toaster().getByRole("alert");

    expect(alert.textContent).toContain("Failed to import 1 file");
    expect(within(alert).getByText("x.stl")).toBeTruthy();
    expect(within(alert).getByRole("button", { name: /retry/i })).toBeTruthy();
  });

  it("retries only the entries that failed, never re-importing the ones that made it", async () => {
    mockZipLink();
    importZipFromLinkMock
      .mockResolvedValueOnce({ assets: [asset("ok.stl")], failed: ["x.stl"] })
      .mockResolvedValueOnce({ assets: [asset("x.stl")], failed: [] });
    renderUploadBar();

    await importSelectedFromZip();
    await waitFor(() => expect(toaster().getAllByRole("alert")).toHaveLength(1));

    expect(importZipFromLinkMock.mock.calls[0][0].entries).toEqual(["ok.stl", "x.stl"]);

    fireEvent.click(toaster().getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(importZipFromLinkMock).toHaveBeenCalledTimes(2));
    expect(importZipFromLinkMock.mock.calls[1][0].entries).toEqual(["x.stl"]);
    expect(importZipFromLinkMock.mock.calls[1][0].entries).not.toContain("ok.stl");
    expect(importZipFromLinkMock.mock.calls[1][0].url).toBe(LINK_URL);

    await waitFor(() => expect(screen.queryByTestId("toaster")).toBeNull());
  });

  it("labels a thrown import error with the failing url and retries that url, not the live input", async () => {
    inspectImportLinkMock.mockRejectedValue(new Error("boom"));
    renderUploadBar();

    typeLink(THINGIVERSE_URL);
    fireEvent.click(screen.getByRole("button", { name: "Import link" }));

    await waitFor(() => expect(toaster().getAllByRole("alert")).toHaveLength(1));
    const alert = toaster().getByRole("alert");
    expect(alert.textContent).toContain("boom");
    expect(within(alert).getByText(THINGIVERSE_URL)).toBeTruthy();

    // The user moves on to a different link before hitting retry.
    typeLink("https://www.printables.com/model/2-other");
    fireEvent.click(within(alert).getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(inspectImportLinkMock).toHaveBeenCalledTimes(2));
    expect(inspectImportLinkMock.mock.calls[1][0].url).toBe(THINGIVERSE_URL);
  });

  it("imports a plain link without raising a toast", async () => {
    inspectImportLinkMock.mockResolvedValue({
      filename: "model.stl",
      mime: "model/stl",
      is_zip: false,
    });
    importFromLinkMock.mockResolvedValue({ id: "asset-model" });
    const { onUploaded } = renderUploadBar();

    typeLink(LINK_URL);
    fireEvent.click(screen.getByRole("button", { name: "Import link" }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
    expect(importFromLinkMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("toaster")).toBeNull();
  });
});
