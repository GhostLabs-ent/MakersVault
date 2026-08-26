export const PROJECT_PERMANENT_CONFIRMATION = "PERMANENTLY DELETE PROJECT";


export function projectTrashCountsLabel(counts: {
  member_count: number;
  active_member_count: number;
  trashed_member_count: number;
  relationship_count: number;
}): string {
  const retained = `${counts.member_count} retained item${counts.member_count === 1 ? "" : "s"}`;
  const trashed = `${counts.trashed_member_count} item${counts.trashed_member_count === 1 ? "" : "s"} in model Trash`;
  const relationships = `${counts.relationship_count} relationship${counts.relationship_count === 1 ? "" : "s"}`;
  return `${retained} · ${trashed} · ${relationships}`;
}


export function responseDownloadFilename(
  disposition: string | null,
  fallback: string,
): string {
  const match = (disposition || "").match(/filename="?([^";]+)"?/i);
  return (match && match[1]) || fallback;
}
