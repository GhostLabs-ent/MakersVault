import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./readStep", () => ({
  readStepMeshes: vi.fn(),
}));

import { formatBytes } from "../format";
import {
  parseStepInWorker,
  resetStepWorkerForTests,
  StepAbortError,
  StepTimeoutError,
  stepSizeNotice,
} from "./parseStepInWorker";
import {
  STEP_INLINE_FALLBACK_BYTES,
  STEP_MAX_BYTES,
  STEP_SIZE_WARN_BYTES,
  StepParseError,
  type StepGeometryPayload,
} from "./protocol";
import { readStepMeshes } from "./readStep";

const readStepMeshesMock = vi.mocked(readStepMeshes);

type SentMessage = { message: { id: number; bytes?: ArrayBuffer }; transfer?: Transferable[] };

class FakeWorker {
  static instances: FakeWorker[] = [];

  onmessage: ((event: MessageEvent<unknown>) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessageerror: ((event: unknown) => void) | null = null;
  readonly messages: SentMessage[] = [];
  readonly terminate = vi.fn();

  constructor() {
    FakeWorker.instances.push(this);
  }

  postMessage(message: unknown, transfer?: Transferable[]): void {
    this.messages.push({ message: message as { id: number; bytes?: ArrayBuffer }, transfer });
  }

  respond(response: unknown): void {
    this.onmessage?.({ data: response } as MessageEvent<unknown>);
  }

  crash(error: unknown = new Error("worker crashed")): void {
    this.onerror?.(error);
  }
}

function sampleGeometry(): StepGeometryPayload {
  return {
    meshes: [
      {
        positions: new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]),
        normals: null,
        indices: null,
        color: null,
      },
    ],
  };
}

function smallStepFile(): Uint8Array {
  return new Uint8Array([73, 83, 79, 45, 49, 48, 51, 48, 51]);
}

beforeEach(() => {
  vi.spyOn(console, "info").mockImplementation(() => undefined);
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  readStepMeshesMock.mockReset();
  resetStepWorkerForTests();
  FakeWorker.instances = [];
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  FakeWorker.instances = [];
});

describe("parseStepInWorker", () => {
  it("parses through the worker and transfers a private copy of the bytes", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    const geometry = sampleGeometry();
    const bytes = smallStepFile();

    const promise = parseStepInWorker(bytes);

    expect(FakeWorker.instances).toHaveLength(1);
    const instance = FakeWorker.instances[0];
    expect(instance.messages).toHaveLength(1);

    const sent = instance.messages[0];
    expect(sent.transfer).toHaveLength(1);
    expect(sent.message.bytes).toBeInstanceOf(ArrayBuffer);
    expect(sent.message.bytes).toBe(sent.transfer?.[0]);
    expect(sent.message.bytes).not.toBe(bytes.buffer);
    expect(Array.from(bytes)).toEqual([73, 83, 79, 45, 49, 48, 51, 48, 51]);
    expect(readStepMeshesMock).not.toHaveBeenCalled();

    instance.respond({ id: sent.message.id, ok: true, geometry });
    await expect(promise).resolves.toBe(geometry);
    expect(readStepMeshesMock).not.toHaveBeenCalled();
  });

  it("rejects with a StepParseError when the worker reports a failure", async () => {
    vi.stubGlobal("Worker", FakeWorker);

    const promise = parseStepInWorker(smallStepFile());
    const instance = FakeWorker.instances[0];
    const sent = instance.messages[0];

    const rejection = expect(promise).rejects.toBeInstanceOf(StepParseError);
    instance.respond({ id: sent.message.id, ok: false, error: "STEP preview produced no meshes" });

    await rejection;
    expect(FakeWorker.instances).toHaveLength(1);
  });

  it("terminates the worker on abort and cold-starts exactly one replacement", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    const controller = new AbortController();
    const geometry = sampleGeometry();

    const promise = parseStepInWorker(smallStepFile(), { signal: controller.signal });
    const first = FakeWorker.instances[0];
    expect(first.messages).toHaveLength(1);
    expect(readStepMeshesMock).not.toHaveBeenCalled();

    const rejection = expect(promise).rejects.toBeInstanceOf(StepAbortError);
    controller.abort();
    await rejection;

    expect(first.terminate).toHaveBeenCalledTimes(1);

    const next = parseStepInWorker(smallStepFile());
    await vi.waitFor(() => {
      expect(FakeWorker.instances).toHaveLength(2);
    });
    const second = FakeWorker.instances[1];
    const sent = second.messages[0];
    second.respond({ id: sent.message.id, ok: true, geometry });

    await expect(next).resolves.toBe(geometry);
    expect(FakeWorker.instances).toHaveLength(2);
  });

  it("does not terminate the worker when a queued job is aborted", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    const geometry = sampleGeometry();

    const firstPromise = parseStepInWorker(smallStepFile());
    const first = FakeWorker.instances[0];
    expect(first.messages).toHaveLength(1);

    const controller = new AbortController();
    const queuedPromise = parseStepInWorker(smallStepFile(), { signal: controller.signal });
    const rejection = expect(queuedPromise).rejects.toBeInstanceOf(StepAbortError);

    controller.abort();
    await rejection;

    expect(first.terminate).not.toHaveBeenCalled();
    expect(FakeWorker.instances).toHaveLength(1);
    expect(first.messages).toHaveLength(1);

    const sent = first.messages[0];
    first.respond({ id: sent.message.id, ok: true, geometry });
    await expect(firstPromise).resolves.toBe(geometry);
  });

  it("parses inline when no Worker exists and the file is small", async () => {
    vi.stubGlobal("Worker", undefined);
    const geometry = sampleGeometry();
    readStepMeshesMock.mockResolvedValue(geometry);

    await expect(parseStepInWorker(smallStepFile())).resolves.toBe(geometry);
    expect(readStepMeshesMock).toHaveBeenCalledTimes(1);
  });

  it("rejects a file over the inline limit when no Worker exists", async () => {
    vi.stubGlobal("Worker", undefined);

    await expect(
      parseStepInWorker(new Uint8Array(STEP_INLINE_FALLBACK_BYTES + 1)),
    ).rejects.toBeInstanceOf(StepParseError);
    expect(readStepMeshesMock).not.toHaveBeenCalled();
  });

  it("rejects a file over the hard limit before touching the worker", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    // Only `length` is read before the limit throws; a real 150 MB buffer would
    // just make the test slow.
    const oversized = { length: STEP_MAX_BYTES + 1 } as unknown as Uint8Array;

    await expect(parseStepInWorker(oversized)).rejects.toThrow(/150 MB/);
    expect(FakeWorker.instances).toHaveLength(0);
    expect(readStepMeshesMock).not.toHaveBeenCalled();
  });

  it("stops spawning workers for the session after a worker crash", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    const geometry = sampleGeometry();

    const promise = parseStepInWorker(smallStepFile());
    const first = FakeWorker.instances[0];

    const rejection = expect(promise).rejects.toBeInstanceOf(StepParseError);
    first.crash(new Error("wasm trap"));
    await rejection;
    expect(first.terminate).toHaveBeenCalledTimes(1);

    readStepMeshesMock.mockResolvedValue(geometry);
    await expect(parseStepInWorker(smallStepFile())).resolves.toBe(geometry);
    expect(readStepMeshesMock).toHaveBeenCalledTimes(1);

    await expect(
      parseStepInWorker(new Uint8Array(STEP_INLINE_FALLBACK_BYTES + 1)),
    ).rejects.toBeInstanceOf(StepParseError);
    await expect(
      parseStepInWorker(new Uint8Array(STEP_INLINE_FALLBACK_BYTES + 1)),
    ).rejects.toThrow(/wasm trap/);

    expect(FakeWorker.instances).toHaveLength(1);
  });

  it("times out with a StepTimeoutError when the job budget expires", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("Worker", FakeWorker);

    const promise = parseStepInWorker(smallStepFile());
    const instance = FakeWorker.instances[0];
    expect(instance.messages).toHaveLength(1);

    const rejection = expect(promise).rejects.toBeInstanceOf(StepTimeoutError);
    await vi.advanceTimersByTimeAsync(120_001);
    await rejection;

    expect(instance.terminate).toHaveBeenCalledTimes(1);
  });
});

describe("stepSizeNotice", () => {
  it("stays quiet up to the warning threshold", () => {
    expect(stepSizeNotice(STEP_SIZE_WARN_BYTES - 1)).toBeNull();
    expect(stepSizeNotice(STEP_SIZE_WARN_BYTES)).toBeNull();
  });

  it("warns above the threshold and names the size", () => {
    const notice = stepSizeNotice(21 * 1024 * 1024);

    expect(notice).toContain("Large STEP file");
    expect(notice).toContain(formatBytes(21 * 1024 * 1024));
    expect(notice).toBe("Large STEP file (21.0 MB) - parsing may take a moment");
    expect(stepSizeNotice(STEP_SIZE_WARN_BYTES + 1)).toContain("Large STEP file");
  });

  it("honours a custom threshold", () => {
    expect(stepSizeNotice(2048, 4096)).toBeNull();
    expect(stepSizeNotice(4097, 4096)).toContain("Large STEP file");
  });
});
