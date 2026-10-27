// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { strToU8, zipSync } from "fflate";

// Only the network layer is mocked: `uploadEntriesToFolder` and `readZipEntries`
// are the real implementations, so the `failedEntries` plumbing and the real
// zip modal are exercised end to end.
vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {
    constructor(message = "Unauthorized") {
      super(message);
      this.name = "UnauthorizedError";
    }
  },
  createFolder: vi.fn(),
  uploadAsset: vi.fn(),
}));

import { createFolder, uploadAsset } from "../lib/api";
import { resetToasts } from "../lib/toast";
import type { UploadEntry } from "../lib/uploadTree";
import Toaster from "./Toaster";
import { useUpload, type UploadOutcome, type UploadRequestOptions } from "./useUpload";

const createFolderMock = vi.mocked(createFolder);
const uploadAssetMock = vi.mocked(uploadAsset);

type HookOptions = Parameters<typeof useUpload>[0];

type HarnessProps = {
  options: HookOptions;
  entries: UploadEntry[];
  requestOptions?: UploadRequestOptions;
  onResult: (outcome: UploadOutcome) => void;
};

function Harness({ options, entries, requestOptions, onResult }: HarnessProps) {
  const hook = useUpload(options);
  return (
    <>
      <Toaster />
      <button
        type="button"
        onClick={() => {
          void hook.upload(entries, requestOptions).then(onResult);
        }}
      >
        start
      </button>
      <span data-testid="busy">{hook.busy ? "busy" : "idle"}</span>
      {hook.modal}
    </>
  );
}

function file(name: string, content = "content"): File {
  return new File([content], name, { type: "application/octet-stream" });
}

function entry(name: string, relativePath = name): UploadEntry {
  return { file: file(name), relativePath };
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

function start(options: HookOptions, entries: UploadEntry[], requestOptions?: UploadRequestOptions) {
  const results: UploadOutcome[] = [];
  render(
    <Harness
      options={options}
      entries={entries}
      requestOptions={requestOptions}
      onResult={outcome => results.push(outcome)}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "start" }));
  return results;
}

function toaster() {
  return within(screen.getByTestId("toaster"));
}

describe("useUpload", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    resetToasts();
    vi.clearAllMocks();
    createFolderMock.mockImplementation(async (name: string) => ({ id: `folder-${name}` }));
    uploadAssetMock.mockImplementation(async () => ({ id: "asset" }));
    // uploadTree logs every failure with console.error; keep test output clean.
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    consoleError.mockRestore();
  });

  it("uploads non-zip entries to the requested folder and reports the outcome", async () => {
    const onUploaded = vi.fn();
    const results = start({ folderId: "folder-1", onUploaded }, [entry("a.stl")]);

    await waitFor(() => expect(results).toHaveLength(1));

    expect(uploadAssetMock).toHaveBeenCalledTimes(1);
    expect(uploadAssetMock.mock.calls[0][1]).toEqual({ folder_id: "folder-1" });
    expect(results[0].uploaded).toBe(1);
    expect(results[0].failed).toEqual([]);
    expect(results[0].failedEntries).toEqual([]);
    expect(onUploaded).toHaveBeenCalledTimes(1);
    expect(onUploaded).toHaveBeenCalledWith({ uploaded: 1 });
  });

  it("does not call onUploaded when nothing was uploaded", async () => {
    uploadAssetMock.mockRejectedValue(new Error("disk full"));
    const onUploaded = vi.fn();
    const results = start({ onUploaded }, [entry("a.stl")]);

    await waitFor(() => expect(results).toHaveLength(1));

    expect(results[0].uploaded).toBe(0);
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it("prompts once per zip, strictly in order", async () => {
    const onUploaded = vi.fn();
    start({ onUploaded }, [zipEntry("one.zip", { "one.stl": "1" }), zipEntry("two.zip", { "two.stl": "2" })]);

    await screen.findByText("one.zip");
    expect(screen.queryByText("two.zip")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Import as zip" }));

    await screen.findByText("two.zip");
    expect(uploadAssetMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Import as zip" }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(1));
    expect(uploadAssetMock).toHaveBeenCalledTimes(2);
    expect(onUploaded).toHaveBeenCalledWith({ uploaded: 2 });
  });

  it("uploads the zip itself when 'Import as zip' is chosen", async () => {
    const results = start({ folderId: "folder-1" }, [zipEntry("bundle.zip", { "model.stl": "1" })]);

    await screen.findByText("bundle.zip");
    fireEvent.click(screen.getByRole("button", { name: "Import as zip" }));

    await waitFor(() => expect(results).toHaveLength(1));
    const [uploadedFile, uploadOptions] = uploadAssetMock.mock.calls[0];
    expect((uploadedFile as File).name).toBe("bundle.zip");
    expect(uploadOptions).toEqual({ folder_id: "folder-1" });
    expect(results[0].uploaded).toBe(1);
  });

  it("unzips a selected subset under the zip's own folder", async () => {
    const results = start({ folderId: "folder-1" }, [
      zipEntry("nested/dir/bundle.zip", { "inner/model.stl": "m", "inner/other.stl": "o" }),
    ]);

    await screen.findByText("bundle.zip");
    fireEvent.click(screen.getByRole("button", { name: "Import and unzip" }));

    await screen.findByText("inner/model.stl");
    expect(screen.getByText("inner/other.stl")).toBeTruthy();

    const otherLabel = screen.getByText("inner/other.stl").closest("label");
    if (!otherLabel) throw new Error("missing entry label");
    fireEvent.click(within(otherLabel).getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Import selected" }));

    await waitFor(() => expect(results).toHaveLength(1));

    expect(createFolderMock.mock.calls).toEqual([
      ["nested", [], "folder-1"],
      ["dir", [], "folder-nested"],
      ["inner", [], "folder-dir"],
    ]);
    expect(uploadAssetMock).toHaveBeenCalledTimes(1);
    const [uploadedFile, uploadOptions] = uploadAssetMock.mock.calls[0];
    expect((uploadedFile as File).name).toBe("model.stl");
    expect(uploadOptions).toEqual({ folder_id: "folder-inner" });
    expect(results[0].failed).toEqual([]);
  });

  it("raises exactly one error toast with details when a file fails", async () => {
    uploadAssetMock.mockImplementation(async (uploadedFile: File) => {
      if (uploadedFile.name === "b.stl") throw new Error("disk full");
      return { id: "asset" };
    });
    const onUploaded = vi.fn();
    const results = start({ onUploaded }, [entry("a.stl"), entry("b.stl")]);

    await screen.findByTestId("toaster");

    expect(toaster().getByText("Failed to upload 1 file")).toBeTruthy();
    expect(toaster().getByText("b.stl (disk full)")).toBeTruthy();
    expect(toaster().getByRole("button", { name: /retry/i })).toBeTruthy();
    expect(toaster().getAllByRole("alert")).toHaveLength(1);
    expect(onUploaded).toHaveBeenCalledTimes(1);
    expect(onUploaded).toHaveBeenCalledWith({ uploaded: 1 });
    expect(results[0].failedEntries.map(failed => failed.file.name)).toEqual(["b.stl"]);
  });

  it("re-uploads only the failures when Retry is clicked", async () => {
    uploadAssetMock.mockImplementation(async (uploadedFile: File) => {
      if (uploadedFile.name === "b.stl") throw new Error("disk full");
      return { id: "asset" };
    });
    start({ folderId: "folder-1" }, [entry("a.stl"), entry("b.stl")]);

    await screen.findByTestId("toaster");
    expect(uploadAssetMock).toHaveBeenCalledTimes(2);

    uploadAssetMock.mockImplementation(async () => ({ id: "asset" }));
    fireEvent.click(toaster().getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(uploadAssetMock).toHaveBeenCalledTimes(3));

    const names = uploadAssetMock.mock.calls.map(([uploadedFile]) => (uploadedFile as File).name);
    expect(names).toEqual(["a.stl", "b.stl", "b.stl"]);
    expect(names.filter(name => name === "a.stl")).toHaveLength(1);
    expect(screen.queryByTestId("toaster")).toBeNull();
  });

  it("keeps the per-call folder override through a failed retry", async () => {
    uploadAssetMock.mockRejectedValue(new Error("nope"));
    start({ folderId: "default-folder" }, [entry("a.stl")], { folderId: "drop-folder" });

    await screen.findByTestId("toaster");
    expect(uploadAssetMock.mock.calls[0][1]).toEqual({ folder_id: "drop-folder" });

    fireEvent.click(toaster().getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(uploadAssetMock).toHaveBeenCalledTimes(2));
    expect(uploadAssetMock.mock.calls[1][1]).toEqual({ folder_id: "drop-folder" });
    expect(
      uploadAssetMock.mock.calls.some(([, opts]) => opts?.folder_id === "default-folder"),
    ).toBe(false);
  });

  it("marks itself busy while the zip prompt is open", async () => {
    start({}, [zipEntry("one.zip", { "one.stl": "1" })]);

    await screen.findByText("one.zip");
    expect(screen.getByTestId("busy").textContent).toBe("busy");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
    });
    expect(screen.getByTestId("busy").textContent).toBe("idle");
  });
});
