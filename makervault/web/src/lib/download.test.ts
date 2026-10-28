// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { filenameFromDisposition, saveResponseToDisk } from "./download";

/** A Response carrying only the headers this helper reads. */
function responseWith(disposition?: string, body = "payload"): Response {
  const headers = new Headers();
  if (disposition !== undefined) headers.set("content-disposition", disposition);
  return new Response(body, { headers });
}

type ClickedAnchor = { download: string | null; href: string | null; attached: boolean };

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:makersvault-download") as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
});

afterEach(() => {
  vi.restoreAllMocks();
  if (originalCreateObjectURL) URL.createObjectURL = originalCreateObjectURL;
  else Reflect.deleteProperty(URL, "createObjectURL");
  if (originalRevokeObjectURL) URL.revokeObjectURL = originalRevokeObjectURL;
  else Reflect.deleteProperty(URL, "revokeObjectURL");
});

describe("filenameFromDisposition", () => {
  it("reads a quoted filename", () => {
    const res = responseWith('attachment; filename="model.stl"');
    expect(filenameFromDisposition(res, "fallback.stl")).toBe("model.stl");
  });

  it("reads an unquoted filename", () => {
    const res = responseWith("attachment; filename=model.stl");
    expect(filenameFromDisposition(res, "fallback.stl")).toBe("model.stl");
  });

  it("prefers and decodes an RFC 5987 filename*", () => {
    const res = responseWith("attachment; filename*=UTF-8''caf%C3%A9%20model.zip");
    expect(filenameFromDisposition(res, "fallback.zip")).toBe("café model.zip");
  });

  it("prefers filename* over the plain filename parameter", () => {
    const res = responseWith(`attachment; filename="plain.zip"; filename*=UTF-8''real.zip`);
    expect(filenameFromDisposition(res, "fallback.zip")).toBe("real.zip");
  });

  it("uses the fallback when the header is missing", () => {
    expect(filenameFromDisposition(responseWith(), "makersvault-selected.zip")).toBe(
      "makersvault-selected.zip",
    );
  });

  it("falls back to \"download\" when neither header nor fallback exist", () => {
    expect(filenameFromDisposition(responseWith(), "")).toBe("download");
  });
});

describe("saveResponseToDisk", () => {
  const clicked: ClickedAnchor[] = [];

  beforeEach(() => {
    clicked.length = 0;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({
        download: this.getAttribute("download"),
        href: this.getAttribute("href"),
        attached: this.parentElement === document.body,
      });
    });
  });

  it("downloads the body under the server-provided filename and revokes the URL", async () => {
    await saveResponseToDisk(responseWith('attachment; filename="café model.zip"'), "fallback.zip");

    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    const blob = vi.mocked(URL.createObjectURL).mock.calls[0][0] as Blob;
    expect(blob.size).toBeGreaterThan(0);
    expect(clicked).toEqual([
      { download: "café model.zip", href: "blob:makersvault-download", attached: true },
    ]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:makersvault-download");
    // The synthetic link must not be left behind in the document.
    expect(document.querySelectorAll("a")).toHaveLength(0);
  });

  it("uses the fallback filename when the response has no disposition", async () => {
    await saveResponseToDisk(responseWith(), "folder.zip");

    expect(clicked).toEqual([{ download: "folder.zip", href: "blob:makersvault-download", attached: true }]);
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });
});
