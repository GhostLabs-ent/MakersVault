const PALETTE = [
  { bg: "#fee2e2", text: "#991b1b", border: "#fecaca" },
  { bg: "#ffedd5", text: "#9a3412", border: "#fed7aa" },
  { bg: "#fef9c3", text: "#854d0e", border: "#fde68a" },
  { bg: "#dcfce7", text: "#166534", border: "#bbf7d0" },
  { bg: "#e0f2fe", text: "#075985", border: "#bae6fd" },
  { bg: "#e0e7ff", text: "#3730a3", border: "#c7d2fe" },
  { bg: "#f4e8ff", text: "#6d28d9", border: "#e9d5ff" },
  { bg: "#fce7f3", text: "#9d174d", border: "#fbcfe8" },
  { bg: "#f1f5f9", text: "#475569", border: "#e2e8f0" },
];

export function colorForTag(tag: string) {
  const normalized = tag.toLowerCase();
  let hash = 0;
  for (let i = 0; i < normalized.length; i++) {
    hash = (hash << 5) - hash + normalized.charCodeAt(i);
    hash |= 0;
  }
  const palette = PALETTE[Math.abs(hash) % PALETTE.length];
  return palette;
}
