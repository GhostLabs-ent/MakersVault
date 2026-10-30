import React from "react";
import qrcode from "qrcode-generator";

type Props = {
  /** The `otpauth://` URI. Never sent anywhere: it is drawn here and only here. */
  value: string;
  /** Rendered edge length in CSS pixels; the viewBox stays module-exact. */
  size?: number;
  label?: string;
};

/** Modules of blank margin around the symbol: scanners need the quiet zone. */
const QUIET_ZONE = 4;
const DEFAULT_SIZE = 192;
const DEFAULT_LABEL = "Two-factor authentication setup QR code";

/**
 * The QR module matrix for `value`, or null when there is nothing to draw.
 *
 * Enrolment hands over an `otpauth://` URI that embeds the TOTP seed, so this
 * must never leave the page - no image service, no data URL in an `<img>` src
 * that an extension or a proxy could log. Drawing the modules ourselves keeps
 * the seed inside this component's own DOM.
 *
 * Nothing here throws: an empty value or a URI too long for any symbol degrades
 * to the placeholder below rather than taking the settings page down with it.
 */
function buildMatrix(value: string): boolean[][] | null {
  const uri = value.trim();
  if (!uri) return null;
  try {
    const qr = qrcode(0, "M");
    qr.addData(uri);
    qr.make();
    const count = qr.getModuleCount();
    const rows: boolean[][] = [];
    for (let row = 0; row < count; row += 1) {
      const cells: boolean[] = [];
      for (let col = 0; col < count; col += 1) {
        cells.push(qr.isDark(row, col));
      }
      rows.push(cells);
    }
    return rows;
  } catch {
    return null;
  }
}

/** One path for every dark module: a single element instead of thousands. */
function modulePath(rows: boolean[][]): string {
  const parts: string[] = [];
  rows.forEach((row, y) => {
    row.forEach((dark, x) => {
      if (dark) parts.push(`M${x} ${y}h1v1h-1z`);
    });
  });
  return parts.join("");
}

export default function MfaQrCode({ value, size = DEFAULT_SIZE, label = DEFAULT_LABEL }: Props) {
  const rows = React.useMemo(() => buildMatrix(value), [value]);

  if (!rows) {
    return (
      <p className="text-sm text-muted" data-testid="mfa-qr-placeholder">
        The QR code could not be drawn. Enter the setup key below instead.
      </p>
    );
  }

  const count = rows.length;
  const span = count + QUIET_ZONE * 2;

  return (
    <svg
      role="img"
      aria-label={label}
      width={size}
      height={size}
      viewBox={`${-QUIET_ZONE} ${-QUIET_ZONE} ${span} ${span}`}
      className="rounded-md"
      shapeRendering="crispEdges"
    >
      {/* White field, not a tailwind class: a QR code needs an opaque light
          background even on the dark theme, or no scanner can read it. */}
      <rect x={-QUIET_ZONE} y={-QUIET_ZONE} width={span} height={span} fill="#ffffff" />
      <path d={modulePath(rows)} fill="#000000" />
    </svg>
  );
}
