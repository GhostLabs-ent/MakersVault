# Gate 3 Owner Checkpoint — Deletion Before Trash

**Status:** Decision requested

**Evidence:** [BASELINE.md](BASELINE.md)

## Why this checkpoint exists

MakersVault currently permits permanent multi-model deletion, but only through the
Delete control on a selected card. Making that action prominent in the new selection
toolbar would make irreversible mass deletion easier before MakersVault has Trash,
restore, or revision history. The roadmap explicitly requires recoverable deletion
before broad destructive bulk operations become more powerful.

## Recommended v5.1 contract

Keep permanent asset deletion deliberately narrow until the Trash gate is accepted:

1. The selection toolbar includes **Delete…** so destructive behavior is not hidden.
2. With one model selected, **Delete…** opens a confirmation that names the model and
   states that its primary and supporting files will be permanently removed.
3. With two or more models selected, the action does not execute. It explains:
   **Permanent bulk delete requires Trash and restore support. Delete models
   individually for now.**
4. Remove the current implicit selected-card multi-delete path. This is an intentional
   safety correction, not a loss of stored data or organization capability.
5. A cancelled or failed single delete leaves the model selected. A successful delete
   reports completion and removes only that ID from selection.
6. No client or server action accepts “all matching models” for deletion.

Move, tag, and download remain available for any number of explicitly loaded and
selected IDs. This checkpoint does not impose a library-size, upload, selection,
move, tag, or download cap.

Folder deletion remains available because it does not delete asset bytes. Its new
confirmation will explicitly state both effects: direct models become unassigned and
direct child folders move to the root. It will not imply that descendants or model
files are deleted.

## Why this is the recommendation

- It makes the existing permanent behavior more legible without increasing its blast
  radius.
- It satisfies Gate 3's conservative-deletion requirement and the product rule that
  MakersVault must not silently delete user data.
- It avoids inventing a typed phrase, item cap, or multi-step dialog that can only
  make irreversible mass deletion look recoverable.
- It leaves a clean future transition: once Trash and restore are verified, the same
  toolbar action can move any explicit selection to Trash and permanent deletion can
  live inside the recoverable workflow.

## Decision requested

Approve or revise the recommended rule: permanent deletion remains one model at a
time in Gate 3, while recoverable multi-model deletion waits for the Trash gate.
