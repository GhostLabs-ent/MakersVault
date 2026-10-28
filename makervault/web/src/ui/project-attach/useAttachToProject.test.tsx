// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { strToU8, zipSync } from "fflate";

// Only the network layer is mocked: the real `uploadEntriesToProject`, the real
// queue, the real zip modal and the real toasts are exercised end to end.
vi.mock("../../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {
    constructor(message = "Unauthorized") {
      super(message);
      this.name = "UnauthorizedError";
    }
  },
  addProjectAssets: vi.fn(),
  listProjectAssets: vi.fn(),
  uploadAsset: vi.fn(),
}));

import { UnauthorizedError, addProjectAssets, listProjectAssets, uploadAsset, type Asset } from "../../lib/api";
import { getToasts, resetToasts } from "../../lib/toast";
import { clearFinishedUploads } from "../../lib/uploadQueue";
import type { UploadEntry } from "../../lib/uploadTree";
import Toaster from "../Toaster";
import { useAttachToProject, type AttachToProjectOptions } from "./useAttachToProject";

const addProjectAssetsMock = vi.mocked(addProjectAssets);
const listProjectAssetsMock = vi.mocked(listProjectAssets);
const uploadAssetMock = vi.mocked(uploadAsset);

function asset(overrides: Partial<Asset> = {}): Asset {
  return {
    id: "asset-1",
    name: "model",
    filename: "model.stl",
    mime: "application/octet-stream",
    size: 7,
    tags: [],
    url: "/api/asset/asset-1/file",
    supporting_file_count: 0,
    ...overrides,
  };
}

function file(name: string, content = "content"): File {
  return new File([content], name, { type: "application/octet-stream" });
}

function entry(name: string, relativePath = name, content = "content"): UploadEntry {
  return { file: file(name, content), relativePath };
}

function zipEntry(relativePath: string, contents: Record<string, string>): UploadEntry {
  const payload: Record<string, Uint8Array> = {};
  // `new Uint8Array(...)`: fflate's own `strToU8` output comes from the Node
  // realm, which `zipSync`'s `instanceof` check rejects under jsdom.
  for (const [path, body] of Object.entries(contents)) payload[path] = new Uint8Array(strToU8(body));
  const bytes = zipSync(payload);
  const name = relativePath.split("/").pop() || relativePath;
  const zipFile = new File([bytes], name);
  // jsdom's File has no `arrayBuffer()`, which `readZipEntries` needs.
  zipFile.arrayBuffer = async () =>
    bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  return { file: zipFile, relativePath };
}

type HarnessProps = {
  options: AttachToProjectOptions;
  entries: UploadEntry[];
  onDone: () => void;
};

function Harness({ options, entries, onDone }: HarnessProps) {
  const attacher = useAttachToProject(options);
  return (
    <>
      <Toaster />
      <button
        type="button"
        onClick={() => {
          void attacher.attach(entries).then(onDone);
        }}
      >
        attach
      </button>
      <span data-testid="busy">{attacher.busy ? "busy" : "idle"}</span>
      {attacher.modal}
    </>
  );
}

function start(
  entries: UploadEntry[],
  overrides: Partial<AttachToProjectOptions> = {},
): { onAttached: ReturnType<typeof vi.fn>; done: Promise<unknown> } {
  const onAttached = vi.fn();
  let resolveDone: (() => void) | null = null;
  const done = new Promise<void>(resolve => {
    resolveDone = resolve;
  });
  render(
    <Harness
      options={{ projectId: "p1", projectName: "Hydra", onAttached, ...overrides }}
      entries={entries}
      onDone={() => resolveDone?.()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "attach" }));
  return { onAttached, done };
}

function toaster() {
  return within(screen.getByTestId("toaster"));
}

function messages(): string[] {
  return getToasts().map(toast => toast.message);
}

function detailsOf(message: string): string[] | undefined {
  return getToasts().find(toast => toast.message === message)?.details;
}

function uploadedNames(): string[] {
  return uploadAssetMock.mock.calls.map(([uploadedFile]) => (uploadedFile as File).name);
}

describe("useAttachToProject", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    resetToasts();
    vi.clearAllMocks();
    clearFinishedUploads();
    listProjectAssetsMock.mockResolvedValue({ items: [], hasMore: false });
    uploadAssetMock.mockImplementation(async (uploadedFile: File) =>
      asset({
        id: `asset-${uploadedFile.name}`,
        name: uploadedFile.name.replace(/\.[^.]+$/, ""),
        filename: uploadedFile.name,
        size: uploadedFile.size,
      }),
    );
    addProjectAssetsMock.mockImplementation(async (_projectId, ids) => ({
      added: [...ids],
      skipped: [],
      failed: [],
    }));
    // Failed uploads are logged by design; keep the test output readable.
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    clearFinishedUploads();
    consoleError.mockRestore();
  });

  it("uploads a folder's files flat and adds every new id in ONE batch", async () => {
    const { onAttached, done } = start([
      entry("one.stl", "print/one.stl"),
      entry("two.stl", "print/two.stl"),
    ]);

    await done;

    expect(uploadedNames()).toEqual(["one.stl", "two.stl"]);
    // No `folder_id`: the project is the destination, storage stays normal.
    for (const call of uploadAssetMock.mock.calls) expect(call[1]).toEqual({});
    expect(addProjectAssetsMock).toHaveBeenCalledTimes(1);
    expect(addProjectAssetsMock).toHaveBeenCalledWith("p1", ["asset-one.stl", "asset-two.stl"]);
    expect(onAttached).toHaveBeenCalledTimes(1);
    expect(messages()).toEqual(['Attached 2 files to "Hydra"']);
    expect(detailsOf('Attached 2 files to "Hydra"')).toBeUndefined();
  });

  it("unzips only the selected entries of a zip", async () => {
    const { done } = start([zipEntry("pack.zip", { "good.stl": "good", "junk.txt": "junk" })]);

    await screen.findByText("pack.zip");
    fireEvent.click(screen.getByRole("button", { name: "Import and unzip" }));

    const junk = await screen.findByText("junk.txt");
    const junkLabel = junk.closest("label");
    if (!junkLabel) throw new Error("missing entry label");
    fireEvent.click(within(junkLabel).getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Import selected" }));

    await done;

    expect(uploadedNames()).toEqual(["good.stl"]);
    expect(addProjectAssetsMock).toHaveBeenCalledTimes(1);
    expect(addProjectAssetsMock).toHaveBeenCalledWith("p1", ["asset-good.stl"]);
  });

  it("adds a loose multi-select to the project in one request", async () => {
    const { done } = start([entry("a.stl"), entry("b.stl"), entry("c.stl")]);

    await done;

    expect(uploadedNames()).toEqual(["a.stl", "b.stl", "c.stl"]);
    expect(addProjectAssetsMock.mock.calls).toEqual([
      ["p1", ["asset-a.stl", "asset-b.stl", "asset-c.stl"]],
    ]);
    expect(messages()).toEqual(['Attached 3 files to "Hydra"']);
  });

  it("skips a file that is already a member and names it in the summary", async () => {
    listProjectAssetsMock.mockResolvedValue({
      items: [asset({ id: "existing", name: "Body", filename: "body.stl", size: 7 })],
      hasMore: false,
    });
    const { done } = start([entry("body.stl"), entry("part.stl")]);

    await done;

    expect(uploadedNames()).toEqual(["part.stl"]);
    expect(addProjectAssetsMock).toHaveBeenCalledWith("p1", ["asset-part.stl"]);
    expect(messages()).toEqual(['Attached 1 file to "Hydra"']);
    expect(detailsOf('Attached 1 file to "Hydra"')).toEqual(["body.stl — already in project"]);
  });

  it("reports an in-batch duplicate once and uploads the file once", async () => {
    const { done } = start([entry("dup.stl"), entry("dup.stl")]);

    await done;

    expect(uploadedNames()).toEqual(["dup.stl"]);
    expect(addProjectAssetsMock).toHaveBeenCalledWith("p1", ["asset-dup.stl"]);
    expect(detailsOf('Attached 1 file to "Hydra"')).toEqual(["dup.stl — duplicate in this batch"]);
  });

  it("reports a per-file upload failure and retries only that file", async () => {
    uploadAssetMock.mockImplementation(async (uploadedFile: File) => {
      if (uploadedFile.name === "part.stl") throw new Error("boom");
      return asset({ id: `asset-${uploadedFile.name}`, name: "Ok", filename: uploadedFile.name });
    });
    const { onAttached, done } = start([entry("part.stl"), entry("ok.stl")]);

    await done;

    expect(messages()).toContain("Failed to upload 1 file");
    expect(detailsOf("Failed to upload 1 file")).toEqual(["part.stl (boom)"]);
    expect(addProjectAssetsMock).toHaveBeenCalledTimes(1);
    expect(addProjectAssetsMock).toHaveBeenCalledWith("p1", ["asset-ok.stl"]);
    expect(onAttached).toHaveBeenCalledTimes(1);

    uploadAssetMock.mockImplementation(async (uploadedFile: File) =>
      asset({ id: `asset-${uploadedFile.name}`, name: "Part", filename: uploadedFile.name }),
    );
    fireEvent.click(toaster().getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(uploadedNames()).toEqual(["part.stl", "ok.stl", "part.stl"]));
    expect(addProjectAssetsMock).toHaveBeenLastCalledWith("p1", ["asset-part.stl"]);
    // A retried upload is a real attachment: the user is told and the list refreshes.
    await waitFor(() => expect(onAttached).toHaveBeenCalledTimes(2));
    expect(messages().filter(message => message === 'Attached 1 file to "Hydra"')).toHaveLength(2);
  });

  it("reports per-id membership failures and retries only the membership call", async () => {
    uploadAssetMock.mockResolvedValue(asset({ id: "asset-a1", name: "Body", filename: "body.stl" }));
    addProjectAssetsMock.mockResolvedValueOnce({
      added: [],
      skipped: [],
      failed: [{ id: "asset-a1", code: "conflict", status: 409, error: "nope" }],
    });
    const { onAttached, done } = start([entry("body.stl")]);

    await done;

    expect(messages()).toContain('Failed to add 1 file to "Hydra"');
    expect(detailsOf('Failed to add 1 file to "Hydra"')).toEqual(["Body (nope)"]);
    expect(onAttached).not.toHaveBeenCalled();

    fireEvent.click(toaster().getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(addProjectAssetsMock).toHaveBeenCalledTimes(2));
    expect(addProjectAssetsMock).toHaveBeenLastCalledWith("p1", ["asset-a1"]);
    expect(uploadAssetMock).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onAttached).toHaveBeenCalledTimes(1));
  });

  it("reports every uploaded file when the membership call throws, and never re-uploads", async () => {
    uploadAssetMock.mockImplementation(async (uploadedFile: File) =>
      asset({ id: `asset-${uploadedFile.name}`, name: "Body", filename: uploadedFile.name }),
    );
    addProjectAssetsMock.mockRejectedValueOnce(new Error("server down"));
    const { done } = start([entry("one.stl"), entry("two.stl")]);

    await done;

    expect(messages()).toContain('Failed to add 2 files to "Hydra"');
    expect(detailsOf('Failed to add 2 files to "Hydra"')).toEqual([
      "Body (server down)",
      "Body (server down)",
    ]);

    fireEvent.click(toaster().getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(addProjectAssetsMock).toHaveBeenCalledTimes(2));
    expect(addProjectAssetsMock).toHaveBeenLastCalledWith("p1", ["asset-one.stl", "asset-two.stl"]);
    expect(uploadAssetMock).toHaveBeenCalledTimes(2);
  });

  it("names a server-skipped asset as already in the project", async () => {
    addProjectAssetsMock.mockResolvedValue({
      added: [],
      skipped: ["asset-body.stl"],
      failed: [],
    });
    const { onAttached, done } = start([entry("body.stl")]);

    await done;

    expect(uploadAssetMock).toHaveBeenCalledTimes(1);
    expect(onAttached).not.toHaveBeenCalled();
    expect(messages()).toEqual(['No new files attached to "Hydra"']);
    expect(detailsOf('No new files attached to "Hydra"')).toEqual([
      "body.stl — already in project",
    ]);
  });

  it("aborts the gesture when the existing-files check fails", async () => {
    listProjectAssetsMock.mockRejectedValue(new Error("nope"));
    const { onAttached, done } = start([entry("a.stl")]);

    await done;

    expect(messages()).toEqual(["Failed to check the project's existing files."]);
    expect(uploadAssetMock).not.toHaveBeenCalled();
    expect(addProjectAssetsMock).not.toHaveBeenCalled();
    expect(onAttached).not.toHaveBeenCalled();
  });

  it("reports a 401 from the existing-files check without an error toast", async () => {
    listProjectAssetsMock.mockRejectedValue(new UnauthorizedError());
    const onUnauthorized = vi.fn();
    const { done } = start([entry("a.stl")], { onUnauthorized });

    await done;

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    expect(messages()).not.toContain("Failed to check the project's existing files.");
    expect(uploadAssetMock).not.toHaveBeenCalled();
  });

  it("pages the membership check and still attaches to an empty project", async () => {
    listProjectAssetsMock
      .mockResolvedValueOnce({ items: [], hasMore: true, nextOffset: 1000 })
      .mockResolvedValueOnce({ items: [], hasMore: false });
    const { done } = start([entry("only.stl")]);

    await done;

    expect(listProjectAssetsMock).toHaveBeenCalledTimes(2);
    expect(listProjectAssetsMock).toHaveBeenNthCalledWith(2, {
      projectId: "p1",
      limit: 1000,
      offset: 1000,
    });
    expect(addProjectAssetsMock).toHaveBeenCalledWith("p1", ["asset-only.stl"]);
  });

  it("does not call the membership endpoint when everything was a duplicate", async () => {
    listProjectAssetsMock.mockResolvedValue({
      items: [asset({ id: "existing", name: "Body", filename: "body.stl", size: 7 })],
      hasMore: false,
    });
    const { onAttached, done } = start([entry("body.stl")]);

    await done;

    expect(uploadAssetMock).not.toHaveBeenCalled();
    expect(addProjectAssetsMock).not.toHaveBeenCalled();
    expect(onAttached).not.toHaveBeenCalled();
    expect(messages()).toEqual(['No new files attached to "Hydra"']);
    expect(detailsOf('No new files attached to "Hydra"')).toEqual(["body.stl — already in project"]);
  });

  it("marks itself busy while the zip prompt is open", async () => {
    start([zipEntry("one.zip", { "one.stl": "1" })]);

    await screen.findByText("one.zip");
    expect(screen.getByTestId("busy").textContent).toBe("busy");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.getByTestId("busy").textContent).toBe("idle"));
  });
});
