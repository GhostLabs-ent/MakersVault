// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { UnauthorizedError, UploadRequestError, uploadAsset } from "./api";

type Listener = (event: unknown) => void;

/** The one bit of `XMLHttpRequestUpload` the implementation subscribes to. */
class FakeUploadTarget {
  readonly listeners = new Map<string, Listener[]>();

  addEventListener(type: string, listener: Listener): void {
    const existing = this.listeners.get(type) ?? [];
    existing.push(listener);
    this.listeners.set(type, existing);
  }

  emit(type: string, event: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

class FakeXMLHttpRequest {
  static instances: FakeXMLHttpRequest[] = [];

  readonly upload = new FakeUploadTarget();
  readonly headers: Array<{ key: string; value: string }> = [];
  method = "";
  url = "";
  body: FormData | null = null;
  timeout = 0;
  withCredentials = true;
  status = 0;
  responseText = "";
  sent = false;
  aborted = false;

  private readonly listeners = new Map<string, Listener[]>();

  constructor() {
    FakeXMLHttpRequest.instances.push(this);
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(key: string, value: string): void {
    this.headers.push({ key, value });
  }

  send(body: unknown): void {
    this.body = body as FormData;
    this.sent = true;
  }

  abort(): void {
    this.aborted = true;
    this.emit("abort");
  }

  addEventListener(type: string, listener: Listener): void {
    const existing = this.listeners.get(type) ?? [];
    existing.push(listener);
    this.listeners.set(type, existing);
  }

  emit(type: string): void {
    for (const listener of this.listeners.get(type) ?? []) listener(undefined);
  }

  progress(loaded: number, total: number): void {
    this.upload.emit("progress", { loaded, total });
  }

  respond(status: number, responseText = ""): void {
    this.status = status;
    this.responseText = responseText;
    this.emit("load");
  }
}

function installMemoryStorage(): void {
  const store = new Map<string, string>();
  const storage: Storage = {
    get length(): number {
      return store.size;
    },
    clear(): void {
      store.clear();
    },
    getItem(key: string): string | null {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number): string | null {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string): void {
      store.delete(key);
    },
    setItem(key: string, value: string): void {
      store.set(key, value);
    },
  };
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
}

const originalXhr = globalThis.XMLHttpRequest;

function latestRequest(): FakeXMLHttpRequest {
  const request = FakeXMLHttpRequest.instances[FakeXMLHttpRequest.instances.length - 1];
  if (!request) throw new Error("no XMLHttpRequest was created");
  return request;
}

function makeFile(name = "part.stl", content = "solid"): File {
  return new File([content], name, { type: "model/stl" });
}

/** Captures the settled outcome so assertions never depend on unhandled rejections. */
async function settle(promise: Promise<unknown>): Promise<{ error?: unknown }> {
  try {
    await promise;
    return {};
  } catch (error) {
    return { error };
  }
}

beforeEach(() => {
  FakeXMLHttpRequest.instances = [];
  globalThis.XMLHttpRequest = FakeXMLHttpRequest as unknown as typeof XMLHttpRequest;
  installMemoryStorage();
  window.localStorage.clear();
});

afterEach(() => {
  globalThis.XMLHttpRequest = originalXhr;
});

describe("uploadAsset (XHR transport)", () => {
  it("posts multipart FormData to /upload and resolves with the parsed JSON", async () => {
    const promise = uploadAsset(makeFile("part.stl"), {
      title: "Gear",
      tags: ["a", "b"],
      folder_id: "folder-1",
    });

    const request = latestRequest();
    expect(request.method).toBe("POST");
    expect(request.url.endsWith("/upload")).toBe(true);
    expect(request.body?.get("title")).toBe("Gear");
    expect(request.body?.get("folder_id")).toBe("folder-1");
    expect(request.body?.get("tags")).toBe("a,b");
    expect((request.body?.get("file") as File).name).toBe("part.stl");

    request.respond(200, JSON.stringify({ id: "asset-1" }));
    await expect(promise).resolves.toEqual({ id: "asset-1" });
  });

  it("forwards progress events and falls back to the file size when total is 0", async () => {
    const seen: Array<{ loaded: number; total: number }> = [];
    const file = makeFile("part.stl", "0123456789");

    uploadAsset(file, {}, { onProgress: (loaded, total) => seen.push({ loaded, total }) });

    const request = latestRequest();
    request.progress(4, 10);
    request.progress(7, 0);
    request.respond(200, "{}");

    expect(seen).toEqual([
      { loaded: 4, total: 10 },
      { loaded: 7, total: file.size },
    ]);
  });

  it("rejects with UnauthorizedError on 401", async () => {
    const promise = uploadAsset(makeFile());
    latestRequest().respond(401, "");
    const { error } = await settle(promise);

    expect(error).toBeInstanceOf(UnauthorizedError);
    expect((error as Error).name).toBe("UnauthorizedError");
  });

  it("rejects a 500 with a retryable UploadRequestError carrying the JSON detail", async () => {
    const promise = uploadAsset(makeFile());
    latestRequest().respond(500, JSON.stringify({ detail: "disk on fire" }));
    const { error } = await settle(promise);

    expect(error).toBeInstanceOf(UploadRequestError);
    const uploadError = error as UploadRequestError;
    expect(uploadError.status).toBe(500);
    expect(uploadError.retryable).toBe(true);
    expect(uploadError.message).toBe("disk on fire");
  });

  it.each([400, 409, 413])("treats a seen %i as non-retryable", async status => {
    const promise = uploadAsset(makeFile());
    latestRequest().respond(status, JSON.stringify({ detail: "nope" }));
    const { error } = await settle(promise);

    expect(error).toBeInstanceOf(UploadRequestError);
    expect((error as UploadRequestError).retryable).toBe(false);
    expect((error as UploadRequestError).status).toBe(status);
  });

  it("surfaces a raw HTML body (nginx 413 page) as the message", async () => {
    const promise = uploadAsset(makeFile());
    latestRequest().respond(413, "  <html>\n<body>413 Request Entity Too Large</body>\n</html>\n  ");
    const { error } = await settle(promise);

    expect((error as UploadRequestError).message).toBe(
      "<html>\n<body>413 Request Entity Too Large</body>\n</html>",
    );
  });

  it("treats a transport error as retryable with no status", async () => {
    const promise = uploadAsset(makeFile());
    latestRequest().emit("error");
    const { error } = await settle(promise);

    expect(error).toBeInstanceOf(UploadRequestError);
    expect((error as UploadRequestError).retryable).toBe(true);
    expect((error as UploadRequestError).status).toBeUndefined();
  });

  it("aborts on an AbortSignal and reports a non-retryable AbortError", async () => {
    const controller = new AbortController();
    const promise = uploadAsset(makeFile(), {}, { signal: controller.signal });
    const request = latestRequest();

    controller.abort();
    const { error } = await settle(promise);

    expect(request.aborted).toBe(true);
    expect((error as Error).name).toBe("AbortError");
    expect((error as UploadRequestError).retryable).toBe(false);
  });

  it("rejects without sending when the signal is already aborted", async () => {
    const controller = new AbortController();
    controller.abort();

    const { error } = await settle(uploadAsset(makeFile(), {}, { signal: controller.signal }));

    expect((error as Error).name).toBe("AbortError");
    expect(FakeXMLHttpRequest.instances).toHaveLength(0);
  });

  it("sends the bearer token and lets the browser choose Content-Type", async () => {
    window.localStorage.setItem("makersvault_auth_token", "tok-123");

    const promise = uploadAsset(makeFile());
    const request = latestRequest();
    request.respond(200, "{}");
    await promise;

    // `Headers` iteration lowercases names; XHR header names are case-insensitive.
    expect(request.headers).toContainEqual({ key: "authorization", value: "Bearer tok-123" });
    expect(request.headers.some(header => header.key.toLowerCase() === "content-type")).toBe(false);
    expect(request.withCredentials).toBe(false);
  });
});
