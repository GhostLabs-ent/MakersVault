export function mountOwnership(copyFiles: boolean) {
  if (copyFiles) {
    return {
      label: "Copy into MakersVault",
      description:
        "MakersVault keeps a managed copy that remains usable if the mount is unavailable. " +
        "The mounted source stays read-only and is never changed or deleted.",
    };
  }
  return {
    label: "Index in place",
    description:
      "No primary file bytes are copied. The mount remains authoritative and must stay available. " +
      "Renaming is disabled, and deleting the MakersVault entry does not delete the source.",
  };
}

export function mountScanStatusLabel(status?: string | null) {
  return status ? status.replace(/_/g, " ") : "not run";
}
