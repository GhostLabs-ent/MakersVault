// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { formatBytes } from "../lib/format";
import { stepSizeNotice } from "../lib/step/parseStepInWorker";
import { STEP_SIZE_WARN_BYTES } from "../lib/step/protocol";
import ModelViewer, { ModelSnapshot, PreviewCancelledError, StepSizeNotice } from "./ModelViewer";
// Vite's raw import rather than `node:fs`: the app deliberately ships without
// `@types/node`, and this is the only place that wants the module's own text.
import modelViewerSource from "./ModelViewer.tsx?raw";

// jsdom has no WebGL, so nothing here mounts the viewer itself.

afterEach(cleanup);

describe("StepSizeNotice", () => {
  it("renders nothing when there is no notice", () => {
    const { container } = render(<StepSizeNotice notice={null} />);
    expect(container.textContent).toBe("");
  });

  it("renders the warning for a file above the threshold", () => {
    const bytes = 50 * 1024 * 1024;
    const notice = stepSizeNotice(bytes);
    expect(notice).not.toBeNull();

    render(<StepSizeNotice notice={notice} />);

    const text = screen.getByText(/Large STEP file/);
    expect(text.textContent).toMatch(/Large STEP file/);
    expect(text.textContent).toContain(formatBytes(bytes));
    expect(text.textContent).toContain("50.0 MB");
  });

  it("stays silent at and below the warning threshold", () => {
    const below = STEP_SIZE_WARN_BYTES - 1;
    const at = STEP_SIZE_WARN_BYTES;
    const above = STEP_SIZE_WARN_BYTES + 1;

    expect(stepSizeNotice(below)).toBeNull();
    expect(stepSizeNotice(at)).toBeNull();
    expect(stepSizeNotice(above)).not.toBeNull();

    for (const bytes of [below, at]) {
      const { container, unmount } = render(<StepSizeNotice notice={stepSizeNotice(bytes)} />);
      expect(container.textContent).toBe("");
      unmount();
    }

    const { container } = render(<StepSizeNotice notice={stepSizeNotice(above)} />);
    expect(container.textContent).toMatch(/Large STEP file/);
  });
});

describe("ModelViewer STEP wiring", () => {
  // Cheap regression guard for "occt must never be imported on the main thread";
  // the behavioural proof lives in src/lib/step/parseStepInWorker.test.ts.
  it("reaches STEP parsing only through the worker module", () => {
    expect(modelViewerSource).not.toContain("occt-import-js");
    expect(modelViewerSource).not.toContain('from "./occt"');
    expect(modelViewerSource).not.toContain("lib/step/occt");
    expect(modelViewerSource).not.toContain("readStepMeshes");
    expect(modelViewerSource).toContain("parseStepInWorker");
  });

  it("keeps the module surface asset-grid/preview.tsx relies on", () => {
    expect(typeof ModelViewer).toBe("function");
    expect(typeof ModelSnapshot).toBe("function");
    expect(typeof StepSizeNotice).toBe("function");
    expect(PreviewCancelledError.prototype instanceof Error).toBe(true);

    const error = new PreviewCancelledError();
    expect(typeof PreviewCancelledError).toBe("function");
    expect(error.name).toBe("PreviewCancelledError");
  });
});
