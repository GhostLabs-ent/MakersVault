import { sessionRequestHeaders } from "./auth";

export type UploadTransfer = { fraction: number | null; phase: "uploading" | "finalizing" };
export type UploadRequestOptions = {
  onProgress: (progress: UploadTransfer) => void;
  signal?: AbortSignal;
};

// XHR exposes upload progress; fetch does not expose this transport signal.
// Progress measures request transfer, not server persistence or preview completion.
export function uploadRequest(url: string, body: FormData, options: UploadRequestOptions): Promise<Response> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const aborted = () => new DOMException("Upload stopped", "AbortError");
    if (options.signal?.aborted) { reject(aborted()); return; }
    const abort = () => xhr.abort();
    const cleanup = () => options.signal?.removeEventListener("abort", abort);
    // Register before open/send for browser upload-event compatibility.
    xhr.upload.onprogress = event => {
      const fraction = event.lengthComputable && event.total > 0 && Number.isFinite(event.loaded)
        ? Math.max(0, Math.min(1, event.loaded / event.total)) : null;
      options.onProgress({ fraction, phase: "uploading" });
    };
    xhr.upload.onload = () => options.onProgress({ fraction: 1, phase: "finalizing" });
    xhr.onload = () => {
      cleanup();
      if (xhr.status === 0) { reject(new Error("Upload connection failed")); return; }
      resolve(new Response([204, 205, 304].includes(xhr.status) ? null : xhr.responseText, { status: xhr.status }));
    };
    xhr.onerror = () => { cleanup(); reject(new Error("Upload connection failed")); };
    xhr.onabort = () => { cleanup(); reject(aborted()); };
    xhr.ontimeout = () => { cleanup(); reject(new Error("Upload timed out")); };
    try {
      xhr.open("POST", url);
      xhr.withCredentials = true;
      sessionRequestHeaders("POST").forEach((value, name) => xhr.setRequestHeader(name, value));
      // Let the browser set the multipart boundary; no new timeout or file ceiling.
      options.signal?.addEventListener("abort", abort, { once: true });
      xhr.send(body);
    } catch (error) {
      cleanup();
      reject(error);
    }
  });
}
