// Byte-streaming uploads. Split by TRANSPORT, not by URL domain: everything that
// puts file bytes on the wire (`XMLHttpRequest`, progress, abort, retryability)
// lives here, whatever route it targets.

import { authHeaders } from "../auth";
import type { Asset } from "./assets";
import { apiBase } from "./baseUrl";
import { UnauthorizedError, errorMessageFromBody, readErrorMessage } from "./http";

/**
 * A non-2xx (or transport-level) failure from an XHR upload. `retryable` marks
 * failures the queue may safely re-attempt; a *seen* 4xx is never retryable.
 */
export class UploadRequestError extends Error {
  status?: number;
  retryable: boolean;
  constructor(message: string, status?: number, retryable = false) {
    super(message);
    this.name = "UploadRequestError";
    this.status = status;
    this.retryable = retryable;
  }
}

/** Generous ceiling so a stalled connection cannot hold a queue slot forever. */
const UPLOAD_TIMEOUT_MS = 15 * 60 * 1000;

function uploadAbortError(): UploadRequestError {
  const error = new UploadRequestError("Upload cancelled", undefined, false);
  // The queue keys off `name` to treat this as cancellation rather than failure.
  error.name = "AbortError";
  return error;
}

function parseUploadResponse(body: string): unknown {
  if (!body.trim()) return null;
  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

export type UploadTransportOptions = {
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
};

export function uploadAsset(
  file: File,
  opts: { title?: string; notes?: string; tags?: string[]; folder_id?: string } = {},
  transport: UploadTransportOptions = {},
): Promise<unknown> {
  return new Promise<unknown>((resolve, reject) => {
    const fd = new FormData();
    fd.set("file", file);
    if (opts.title) fd.set("title", opts.title);
    if (opts.notes) fd.set("notes", opts.notes);
    if (opts.tags && opts.tags.length) fd.set("tags", opts.tags.join(","));
    if (opts.folder_id) fd.set("folder_id", opts.folder_id);

    const signal = transport.signal;
    if (signal?.aborted) {
      reject(uploadAbortError());
      return;
    }

    const xhr = new XMLHttpRequest();
    // The API authenticates with bearer tokens, never cookies.
    xhr.withCredentials = false;
    xhr.timeout = UPLOAD_TIMEOUT_MS;
    xhr.open("POST", `${apiBase()}/upload`);
    // Content-Type is intentionally omitted: the browser adds the multipart boundary.
    authHeaders().forEach((value, key) => xhr.setRequestHeader(key, value));

    xhr.upload.addEventListener("progress", event => {
      transport.onProgress?.(event.loaded, event.total || file.size);
    });

    const onSignalAbort = () => xhr.abort();
    const detachSignal = () => signal?.removeEventListener("abort", onSignalAbort);
    signal?.addEventListener("abort", onSignalAbort, { once: true });

    xhr.addEventListener("load", () => {
      detachSignal();
      const status = xhr.status;
      if (status === 401) {
        reject(new UnauthorizedError());
        return;
      }
      if (status >= 200 && status < 300) {
        resolve(parseUploadResponse(xhr.responseText));
        return;
      }
      // Retry safety: each POST creates a fresh asset row and the server removes the
      // row and its partial file on any failure, so a retried attempt cannot leave a
      // half-written asset; a response lost after a full commit surfaces as a
      // non-retryable 409 (unique filename index) rather than a duplicate row.
      const retryable = status >= 500 || status === 429 || status === 408;
      reject(
        new UploadRequestError(
          errorMessageFromBody(xhr.responseText || "", "Upload failed"),
          status,
          retryable,
        ),
      );
    });
    xhr.addEventListener("error", () => {
      detachSignal();
      // Status 0 or a mid-body server abort (e.g. MAX_UPLOAD_MB rejected before headers).
      reject(new UploadRequestError("Network error", undefined, true));
    });
    xhr.addEventListener("timeout", () => {
      detachSignal();
      reject(new UploadRequestError("Upload timed out", undefined, true));
    });
    xhr.addEventListener("abort", () => {
      detachSignal();
      reject(uploadAbortError());
    });

    xhr.send(fd);
  });
}

export async function uploadGeneratedThumbnail(id: string, image: Blob): Promise<Asset> {
  const body = new FormData();
  body.set("file", image, "thumbnail.png");
  const res = await fetch(`${apiBase()}/asset/${id}/thumbnail-generated`, {
    method: "POST",
    headers: authHeaders(),
    body,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to save generated thumbnail"));
  }
  return res.json();
}

export async function uploadAssetFile(id: string, file: File): Promise<Asset> {
  const body = new FormData();
  body.set("file", file, file.name);
  const res = await fetch(`${apiBase()}/asset/${id}/files`, {
    method: "POST",
    headers: authHeaders(),
    body,
  });
  if (res.status === 401) throw new UnauthorizedError();
  if (!res.ok) {
    throw new Error(await readErrorMessage(res, "Failed to add file"));
  }
  return res.json();
}
