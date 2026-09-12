import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { UploadProgressItem } from "./UploadProgress";
import type { UploadBatch } from "../lib/uploadProgress";

const batch: UploadBatch = { id: 1, totalFiles: 10, totalBytes: 100, transferredBytes: 100,
  savedFiles: 9, failedFiles: 0, currentPath: "folder/part.stl", phase: "finalizing", measurable: true };

describe("accessible upload status", () => {
  it("distinguishes transfer 100% from saved completion", () => {
    const html = renderToStaticMarkup(<UploadProgressItem batch={batch} />);
    expect(html).toContain('aria-label="Upload transfer"');
    expect(html).toContain('value="100"');
    expect(html).toContain('100% transferred');
    expect(html).toContain('9 / 10 files saved');
    expect(html).toContain('Finalizing on server');
    expect(html).not.toContain('Upload complete');
    expect(html).not.toContain('Dismiss');
  });

  it("uses native indeterminate progress and exposes partial failures", () => {
    const html = renderToStaticMarkup(<UploadProgressItem batch={{ ...batch, measurable: false, phase: "partial", failedFiles: 1 }} />);
    expect(html).not.toMatch(/<progress[^>]+value=/);
    expect(html).toContain('1 failed');
    expect(html).toContain('Upload finished with errors');
    expect(html).toContain('Dismiss upload result');
  });
});
