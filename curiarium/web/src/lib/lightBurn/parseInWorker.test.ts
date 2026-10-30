import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PreviewQueue } from "../previewQueue";
import {
  DEFAULT_LIGHTBURN_LIMITS,
  LIGHTBURN_INLINE_FALLBACK_BYTES,
  LightBurnParseError,
  type LightBurnModel,
} from "./parse";
import {
  LightBurnAbortError,
  LightBurnTimeoutError,
  parseLightBurnInWorker,
  resetLightBurnWorkerForTests,
} from "./parseInWorker";

type SentMessage = { message: { id: number }; transfer?: Transferable[] };

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
    this.messages.push({ message: message as { id: number }, transfer });
  }

  respond(response: unknown): void {
    this.onmessage?.({ data: response } as MessageEvent<unknown>);
  }
}

function emptyModel(): LightBurnModel {
  return {
    layers: [],
    paths: [],
    bounds: null,
    thumbnail: null,
    truncated: false,
    stats: { shapes: 0, skippedShapes: 0, segments: 0 },
  };
}

function smallProject(): Uint8Array {
  return new TextEncoder().encode("<LightBurnProject AppVersion=\"1.7\" FormatVersion=\"1\"></LightBurnProject>");
}

beforeEach(() => {
  vi.spyOn(console, "info").mockImplementation(() => undefined);
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
  resetLightBurnWorkerForTests();
  FakeWorker.instances = [];
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  FakeWorker.instances = [];
});

describe("parseLightBurnInWorker", () => {
  it("falls back to synchronous parsing without a Worker", async () => {
    vi.stubGlobal("Worker", undefined);

    const model = await parseLightBurnInWorker(smallProject(), DEFAULT_LIGHTBURN_LIMITS);
    expect(model.layers).toEqual([]);
    expect(model.bounds).toBeNull();
  });

  it("rejects large files when no Worker is available", async () => {
    vi.stubGlobal("Worker", undefined);
    const bytes = new Uint8Array(LIGHTBURN_INLINE_FALLBACK_BYTES + 1);

    await expect(parseLightBurnInWorker(bytes, DEFAULT_LIGHTBURN_LIMITS)).rejects.toBeInstanceOf(
      LightBurnParseError,
    );
  });

  it("parses through a worker and transfers the bytes", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    const model = emptyModel();

    const promise = parseLightBurnInWorker(smallProject(), DEFAULT_LIGHTBURN_LIMITS);
    expect(FakeWorker.instances).toHaveLength(1);
    const instance = FakeWorker.instances[0];
    expect(instance.messages).toHaveLength(1);
    const sent = instance.messages[0];
    expect(sent.transfer?.length).toBeGreaterThan(0);

    instance.respond({ id: sent.message.id, ok: true, model });
    await expect(promise).resolves.toBe(model);
  });

  it("times out, terminates the worker, and recovers with a fresh worker", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("Worker", FakeWorker);
    const model = emptyModel();

    const promise = parseLightBurnInWorker(smallProject(), DEFAULT_LIGHTBURN_LIMITS, {
      timeoutMs: 5000,
    });
    const first = FakeWorker.instances[0];
    expect(first).toBeDefined();

    const rejection = expect(promise).rejects.toBeInstanceOf(LightBurnTimeoutError);
    await vi.advanceTimersByTimeAsync(5001);
    await rejection;
    expect(first.terminate).toHaveBeenCalledTimes(1);

    const secondPromise = parseLightBurnInWorker(smallProject(), DEFAULT_LIGHTBURN_LIMITS, {
      timeoutMs: 5000,
    });
    expect(FakeWorker.instances).toHaveLength(2);
    const second = FakeWorker.instances[1];
    const sent = second.messages[0];
    second.respond({ id: sent.message.id, ok: true, model });

    await expect(secondPromise).resolves.toBe(model);
  });

  it("rejects with an abort error when the queue yields no result", async () => {
    vi.stubGlobal("Worker", FakeWorker);
    const queue = { enqueue: vi.fn().mockResolvedValue(null) } as unknown as PreviewQueue;

    await expect(
      parseLightBurnInWorker(smallProject(), DEFAULT_LIGHTBURN_LIMITS, { queue }),
    ).rejects.toBeInstanceOf(LightBurnAbortError);
  });
});
