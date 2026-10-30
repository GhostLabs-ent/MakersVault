// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import MfaQrCode from "./MfaQrCode";

/** A fixed URI, so the module matrix below is a fact about this input. */
const OTPAUTH_URI =
  "otpauth://totp/Curiarium:admin?secret=JBSWY3DPEHPK3PXP&issuer=Curiarium&algorithm=SHA1&digits=6&period=30";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("MfaQrCode", () => {
  it("draws the URI as an accessible svg in this document", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<MfaQrCode value={OTPAUTH_URI} label="Authenticator setup QR code" />);

    const svg = screen.getByRole("img", { name: "Authenticator setup QR code" });
    expect(svg.tagName.toLowerCase()).toBe("svg");
    // Drawing is local by construction: the seed must never leave the page.
    expect(fetchMock).not.toHaveBeenCalled();
    const html = document.body.innerHTML;
    expect(html).not.toContain("secret=");
  });

  it("emits at least one dark module from the fixed URI", () => {
    const { container } = render(<MfaQrCode value={OTPAUTH_URI} />);

    const path = container.querySelector("path");
    if (!path) throw new Error("the QR code rendered no modules");
    const d = path.getAttribute("d") ?? "";
    // Every dark module is one `M x y h1 v1 h-1 z` subpath. A QR code's
    // top-left finder pattern starts dark at (0, 0), which is also a fact about
    // the symbol rather than about this implementation.
    expect(d.startsWith("M0 0h1v1h-1z")).toBe(true);
    expect((d.match(/M/g) ?? []).length).toBeGreaterThan(100);
    expect(path.getAttribute("fill")).toBe("#000000");
  });

  it("sizes the drawing from the size prop and keeps the quiet zone", () => {
    const { container } = render(<MfaQrCode value={OTPAUTH_URI} size={128} />);

    const svg = container.querySelector("svg");
    if (!svg) throw new Error("the QR code rendered no svg");
    expect(svg.getAttribute("width")).toBe("128");
    expect(svg.getAttribute("height")).toBe("128");
    // 4 modules of margin on each side of a module-exact viewBox.
    const viewBox = (svg.getAttribute("viewBox") ?? "").split(" ").map(Number);
    const [minX, minY, width, height] = viewBox;
    expect(minX).toBe(-4);
    expect(minY).toBe(-4);
    expect(width).toBe(height);
    expect(width).toBeGreaterThan(33);
  });

  it("renders a placeholder instead of throwing on an empty value", () => {
    render(<MfaQrCode value="   " />);

    expect(screen.getByTestId("mfa-qr-placeholder")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });
});
