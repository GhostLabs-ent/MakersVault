import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setSessionCsrfToken } from "./auth";
import { uploadRequest } from "./uploadRequest";

class FakeXHR {
  static latest: FakeXHR;
  upload = { onprogress: null as null | ((event: Partial<ProgressEvent>) => void), onload: null as null | (() => void) };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  status = 200;
  responseText = '{"id":"stored"}';
  withCredentials = false;
  headers = new Headers();
  open = vi.fn();
  send = vi.fn();
  abort = vi.fn(() => this.onabort?.());
  setRequestHeader(name: string, value: string) { this.headers.set(name, value); }
  constructor() { FakeXHR.latest = this; }
}

beforeEach(() => {
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  vi.stubGlobal("document", { cookie: "__Host-makersvault_csrf=cookie-csrf" });
  setSessionCsrfToken(null);
});
afterEach(() => { vi.unstubAllGlobals(); setSessionCsrfToken(null); });

describe("cookie-authenticated progress transport", () => {
  it("keeps credentials/CSRF and the browser multipart boundary; awaits the response", async () => {
    const onProgress = vi.fn();
    const body = new FormData();
    const finished = vi.fn();
    const promise = uploadRequest("https://vault.example/api/upload", body, { onProgress }).then(response => { finished(); return response; });
    const xhr = FakeXHR.latest;
    expect(xhr.open).toHaveBeenCalledWith("POST", "https://vault.example/api/upload");
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.headers.get("X-CSRF-Token")).toBe("cookie-csrf");
    expect(xhr.headers.has("Authorization")).toBe(false);
    expect(xhr.headers.has("Content-Type")).toBe(false);
    expect(xhr.send).toHaveBeenCalledWith(body);
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 25, total: 100 });
    expect(onProgress).toHaveBeenLastCalledWith({ fraction: 0.25, phase: "uploading" });
    xhr.upload.onload?.();
    await Promise.resolve();
    expect(finished).not.toHaveBeenCalled();
    expect(onProgress).toHaveBeenLastCalledWith({ fraction: 1, phase: "finalizing" });
    xhr.onload?.();
    expect(await (await promise).json()).toEqual({ id: "stored" });
  });

  it("uses memory CSRF for a separately hosted API", async () => {
    setSessionCsrfToken("cross-host-csrf");
    const promise = uploadRequest("https://api.vault.example/upload", new FormData(), { onProgress: vi.fn() });
    expect(FakeXHR.latest.headers.get("X-CSRF-Token")).toBe("cross-host-csrf");
    FakeXHR.latest.onload?.(); await promise;
  });

  it("preserves unknown-length events instead of inventing a percentage", async () => {
    const onProgress = vi.fn();
    const promise = uploadRequest("/api/upload", new FormData(), { onProgress });
    FakeXHR.latest.upload.onprogress?.({ lengthComputable: false, loaded: 20, total: 0 });
    expect(onProgress).toHaveBeenCalledWith({ fraction: null, phase: "uploading" });
    FakeXHR.latest.onload?.(); await promise;
  });

  it.each([401, 403, 413, 500])("returns status %i and its error body to the existing API handler", async status => {
    const promise = uploadRequest("/api/upload", new FormData(), { onProgress: vi.fn() });
    FakeXHR.latest.status = status;
    FakeXHR.latest.responseText = '{"detail":"specific error"}';
    FakeXHR.latest.onload?.();
    const response = await promise;
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({ detail: "specific error" });
  });

  it("rejects network failures without reporting a saved file", async () => {
    const promise = uploadRequest("/api/upload", new FormData(), { onProgress: vi.fn() });
    FakeXHR.latest.onerror?.();
    await expect(promise).rejects.toThrow("Upload connection failed");
  });

  it("aborts a pending upload and does not send one already cancelled", async () => {
    const controller = new AbortController();
    const promise = uploadRequest("/api/upload", new FormData(), { onProgress: vi.fn(), signal: controller.signal });
    controller.abort();
    await expect(promise).rejects.toMatchObject({ name: "AbortError" });
    expect(FakeXHR.latest.abort).toHaveBeenCalledTimes(1);
    const cancelled = uploadRequest("/api/upload", new FormData(), { onProgress: vi.fn(), signal: controller.signal });
    await expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
    expect(FakeXHR.latest.send).not.toHaveBeenCalled();
  });
});
