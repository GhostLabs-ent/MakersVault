const SOURCE_HOSTS: Array<[needle: string, label: string]> = [
  ["printables", "Printables"],
  ["thingiverse", "Thingiverse"],
  ["makerworld", "MakerWorld"],
];

/** The well-known host a `source_url` points at, for the "View original" badge. */
export function sourceHostLabel(url: string): string | null {
  try {
    const host = new URL(url).hostname.toLowerCase();
    for (const [needle, label] of SOURCE_HOSTS) {
      if (host.includes(needle)) return label;
    }
  } catch {
    // An unparsable URL still gets the generic badge.
  }
  return null;
}

/** Chip text for a provenance source: the well-known host, else the hostname. */
export function sourceChipLabel(url: string): string {
  const known = sourceHostLabel(url);
  if (known) return known;
  try {
    const host = new URL(url).hostname.replace(/^www\./i, "");
    return host || "Source";
  } catch {
    return "Source";
  }
}
