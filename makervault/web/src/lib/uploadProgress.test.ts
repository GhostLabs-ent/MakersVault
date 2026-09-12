import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearUploads, dismissUpload, getUploadBatches, startUploadBatch, subscribeUploads, uploadPercent } from "./uploadProgress";

beforeEach(clearUploads);
const latest = () => getUploadBatches()[getUploadBatches().length - 1]!;

describe("upload progress accounting", () => {
  it("weights transfer by bytes and does not call transmitted data saved", () => {
    const batch = startUploadBatch([{ size: 10 }, { size: 90 }]);
    batch.beginFile("small.stl", 10);
    batch.transfer({ fraction: 1, phase: "finalizing" });
    expect(uploadPercent(latest())).toBe(10);
    expect(latest().savedFiles).toBe(0);
    expect(latest().phase).toBe("finalizing");
    batch.saved();
    batch.beginFile("large.stl", 90);
    batch.transfer({ fraction: 0.5, phase: "uploading" });
    expect(uploadPercent(latest())).toBe(55);
    batch.transfer({ fraction: 1, phase: "finalizing" });
    expect(uploadPercent(latest())).toBe(100);
    expect(latest().savedFiles).toBe(1);
    expect(latest().phase).not.toBe("complete");
    batch.saved(); batch.finish();
    expect(latest()).toMatchObject({ phase: "complete", savedFiles: 2 });
  });

  it("does not label a fully transferred but rejected upload successful", () => {
    const batch = startUploadBatch([{ size: 100 }]);
    batch.beginFile("denied.stl", 100);
    batch.transfer({ fraction: 1, phase: "finalizing" });
    batch.failed(); batch.finish();
    expect(latest()).toMatchObject({ phase: "partial", savedFiles: 0, failedFiles: 1 });
    expect(uploadPercent(latest())).toBe(100); // Transfer is not persistence.
  });

  it("does not fill in bytes for a failed file or folder", () => {
    const batch = startUploadBatch([{ size: 20 }, { size: 80 }]);
    batch.beginFile("folder/failed.stl", 20); batch.failed();
    batch.beginFile("ok.stl", 80); batch.saved(); batch.finish();
    expect(uploadPercent(latest())).toBe(80);
    expect(latest()).toMatchObject({ savedFiles: 1, failedFiles: 1, phase: "partial" });
  });

  it("shows unknown-length and zero-byte transfers as indeterminate until confirmed", () => {
    const batch = startUploadBatch([{ size: 0 }]);
    batch.beginFile("empty.txt", 0);
    batch.transfer({ fraction: null, phase: "uploading" });
    expect(uploadPercent(latest())).toBeNull();
    batch.transfer({ fraction: 1, phase: "finalizing" });
    expect(uploadPercent(latest())).toBeNull();
    batch.saved(); batch.finish();
    expect(uploadPercent(latest())).toBe(100);
  });

  it("keeps monotonic bounded progress and coalesces sub-percentage events", () => {
    const batch = startUploadBatch([{ size: 1000 }]);
    batch.beginFile("part.stl", 1000);
    const listener = vi.fn();
    const unsubscribe = subscribeUploads(listener);
    batch.transfer({ fraction: 0.501, phase: "uploading" });
    batch.transfer({ fraction: 0.505, phase: "uploading" });
    batch.transfer({ fraction: 0.1, phase: "uploading" });
    expect(listener).toHaveBeenCalledTimes(1);
    expect(uploadPercent(latest())).toBe(50);
    batch.transfer({ fraction: 2, phase: "finalizing" });
    expect(uploadPercent(latest())).toBe(100);
    unsubscribe();
  });

  it("keeps simultaneous batches separate and cannot dismiss an active one", () => {
    const first = startUploadBatch([{ size: 10 }]);
    first.beginFile("first.stl", 10);
    const firstId = latest().id;
    const second = startUploadBatch([{ size: 20 }]);
    second.beginFile("second.stl", 20); second.saved(); second.finish();
    dismissUpload(firstId);
    expect(getUploadBatches()).toHaveLength(2);
    dismissUpload(latest().id);
    expect(getUploadBatches()).toHaveLength(1);
    expect(latest().currentPath).toBe("first.stl");
  });

  it("retains only three completed summaries, without an upload-count ceiling", () => {
    for (let index = 0; index < 10; index++) {
      const batch = startUploadBatch([{ size: 1 }]);
      batch.beginFile("part.stl", 1); batch.saved(); batch.finish();
    }
    expect(getUploadBatches()).toHaveLength(3);
  });

  it("aborts old-account work and prevents stale progress from resurfacing", () => {
    const batch = startUploadBatch([{ size: 100 }]);
    batch.beginFile("private.stl", 100);
    clearUploads();
    expect(batch.signal.aborted).toBe(true);
    batch.transfer({ fraction: 1, phase: "finalizing" }); batch.saved(); batch.finish();
    expect(getUploadBatches()).toEqual([]);
  });
});
