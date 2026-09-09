export type FolderDestination = { id: string | null; name: string };
type MoveSource = { id: string; name: string; folder_id?: string | null; current_revision_id?: string | null };

export function sameFolderMoveSource(current: MoveSource | undefined, original: MoveSource): boolean {
  return Boolean(current && current.id === original.id && current.name === original.name
    && (current.folder_id || null) === (original.folder_id || null)
    && (current.current_revision_id || null) === (original.current_revision_id || null));
}

export function filterFolderDestinations(options: FolderDestination[], query: string): FolderDestination[] {
  const needle = query.trim().toLocaleLowerCase();
  return needle ? options.filter(option => option.name.toLocaleLowerCase().includes(needle)) : options;
}

/** null means no selection; the empty string explicitly means Unassigned. */
export function canMoveToFolder(destination: string | null, current: string | null | undefined, options: FolderDestination[]): boolean {
  return destination !== null && destination !== (current || "")
    && options.some(option => (option.id || "") === destination);
}
