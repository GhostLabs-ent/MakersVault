# Local file access boundary — MP-1b-1 through MP-1b-5

Internal, read-only and **not called by the bridge CLI**. This is the first part
of MP-1b, not completed workstation discovery or a user-facing import feature.
The Linux backend is locally tested; the new Windows backend is implemented but
not natively qualified. New Mac-local preset import is owner-deferred from v5.1;
the tagged experiment remains excluded from normal builds, which fail closed. Cross-builds
do not qualify native behavior. No API, protocol, background scan or saved setting
is added. Do not activate this code until the remaining MP-1b boundaries are met.

## Operations

- [Content discovery/selection](DISCOVERY.md) binds actual machine identities,
  validates exact parent chains and projects bounded explicit choices under one
  held root and shared budget. Production remains inactive; ordinary saved-user
  files without explicit machine/instantiation headers need the next format slice.
- [Location planning/inspection](LOCATIONS.md) adds pure known-location candidates
  and bounded held-parent inspection of one explicit data root/account. It reads
  the system manifest and optionally lists one chosen user machine folder; it does
  not select an account, parse profiles, observe app versions or enable import.
- `ListJSON(ctx, root)` lists ordinary direct JSON children in an already selected
  local root. It neither recurses nor reads their contents. All directory entries
  count toward the 10,000-entry ceiling; listing is sorted, never partial on error.
  This is NOT Bambu manifest discovery: machine-model documents can also be JSON.
- `LoadBambu(ctx, inputs)` feeds explicitly selected basenames into the existing
  Bambu catalog, at most one system and one user root in one local namespace.
  Exact-name inheritance stays in the pure parser; no profile value becomes a
  filesystem path. A failed read/parse returns no catalog, including after earlier
  files succeeded. The caller must resolve/review candidates within the catalog's
  remaining budget. It does not send or save metadata.
- `ReadBambuManifest(ctx, root)` opens only the fixed `BBL.json` basename through
  the same held-handle boundary. `ParseBambuManifest(ctx, bytes)` is its pure,
  bounded projection. The local index retains only bundle version and exact
  `machine_list` name/basename pairs; model/filament/process lists, URLs and unknown
  settings are discarded. No referenced file, user folder or URL is visited.
  `SelectFiles` maps explicit exact identities, with no implicit all-selection,
  filename guessing or dependency expansion. This is **not** a selectable-printer
  list: machine entries also include inheritance and G-code templates. The future
  content operation now verifies these identities and parent chains; this index-only
  operation still does not offer presets or confer local selection/consent authority.
- `Input` cannot convey paths/files through JSON. This is defense in depth, NOT
  authorization: only a future locally consented adapter may construct it. No
  browser/server path, environment expansion or shell interpretation is permitted.

File operations impose a 15-second **cooperative** deadline; LoadBambu keeps the
parser's 10,000-file / 8-MiB-file / 128-MiB-total limits. It checks cancellation
between operations and reads. Regular-file kernel I/O can still stall. A bounded
isolated worker with parent-enforced timeout/cancellation is required before any
CLI activation. The [MP-1b-2 supervisor](../presetworker/README.md) now implements
that boundary, exercised through a test executable only; native and matched-main
integration remain pending. These direct file APIs themselves stay cooperative.

## Linux amd64/arm64 boundary

Only absolute clean non-root POSIX paths are accepted. Each ancestor is opened as
an `O_PATH` directory with `openat2` beneath the held parent, prohibiting symlinks
and magic links. Filesystem checks permit ext2/3/4, btrfs, xfs, tmpfs and overlay;
network/FUSE/automount/pseudo/unknown filesystems fail closed. This is a conservative
filesystem-family policy, not proof about a disk's physical backing. Local mounts
may occur on the way to the expressly chosen root. **Below** that root, `NO_XDEV`
also rejects bind mounts, including same-device mounts. Old kernels or seccomp
policies that lack the required boundary are unsupported; no weaker fallback.

Selected basenames reject traversal, separators, UNC/URL/ADS syntax, controls,
invalid UTF-8 and portable reserved names. Case-fold collisions fail closed.
Only regular files with a single hard link pass the confined `O_PATH` inspection;
FIFOs, sockets, devices, directories and symlinks are never opened for data. The
held regular inode is then opened read-only through the internally generated
`/proc/self/fd/<held descriptor>` path. Missing/restricted procfs fails closed.
This fixed internal handle conversion is not a profile include or arbitrary path.

The opened file's identity/mode/size/mtime/ctime/link count is compared across
conversion and reading. Directory metadata changes during listing/loading cause
failure. Held-root renames never redirect reads to a replacement pathname. These
checks detect observed changes, not an atomic multi-file filesystem snapshot:
previously read contents can change later. Refresh/review and content digests must
remain explicit; local privileged attackers/kernel compromise are not sandboxed.

Primary references: Linux v6.12 [openat2 UAPI](https://raw.githubusercontent.com/torvalds/linux/v6.12/include/uapi/linux/openat2.h),
[syscall numbers](https://raw.githubusercontent.com/torvalds/linux/v6.12/include/uapi/asm-generic/unistd.h),
[filesystem types](https://raw.githubusercontent.com/torvalds/linux/v6.12/include/uapi/linux/magic.h),
and the Linux man-pages project's [openat2](https://man7.org/linux/man-pages/man2/openat2.2.html)
and [O_PATH documentation](https://man7.org/linux/man-pages/man2/open.2.html).

## Windows amd64/arm64 boundary — native tests pending

Accept only explicit drive-absolute backslash paths with ordinary bounded components;
reject UNC, extended/device namespaces, drive-relative paths, ADS, reserved names,
dot components and trailing-dot/space ambiguity. These syntax tests run on Linux
too. Common filename collision checks now use Unicode simple-fold equivalence
instead of lowercase alone; this does not qualify all NTFS case behavior.

The native backend starts from a fixed local drive, requires NTFS plus a volume
GUID, and opens each component relative to its held parent with `NtCreateFile`,
`OBJ_DONT_REPARSE`, `FILE_OPEN_REPARSE_POINT` and existing-only disposition. Every
handle must remain on the same volume; reparse/device/offline/recall attributes
are rejected. No junction is followed even within the chosen root. Unknown volumes,
ReFS/FAT, network/removable drives and missing native primitives fail closed.
This is not proof about a physical disk's backing or every filesystem filter.

File metadata is checked before granting data access; `ReOpenFile` converts the
held ordinary single-link file to a read handle without re-resolving its pathname,
with reparse/no-recall flags. Read-sharing only means conflicting writes/deletes
may cause a retryable unavailable-source error while handles are held. No permissions
are changed or privileges enabled. Windows identity/size/mtime/attributes/creation
time checks are not Unix ctime parity or an atomic multi-file snapshot.

Primary contracts: Microsoft [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile),
[object attributes/reparse rejection](https://learn.microsoft.com/en-us/windows/win32/api/ntdef/ns-ntdef-_object_attributes),
[volume GUID paths](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew),
[volume information](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumeinformationbyhandlew),
[drive types](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdrivetypew),
[ReOpenFile](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-reopenfile)
and [path naming](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file).
Go 1.26.6's local Windows directory implementation was inspected for handle-based
enumeration. None of this source review substitutes for running the native tests.

## Remaining MP-1b work

Native Windows execution (including reparse/ACL/volume/placeholder and process
lifecycle cases), matched supervisor integration and startup/
cleanup qualification; native known-folder/hint acquisition and root/account
selection UI; ordinary saved-user format projection, real-profile conformance
and independently observed application versions. The
manifest's four-component bundle version is retained exactly, never promoted to
an installed application version. Malformed, ambiguous or over-budget manifests
fail without a partial index. The index parser permits at most 10,000 machine
entries, 8 MiB, depth 16, 250,000 value nodes and 2,048 keys per object; unknown
schema markers and unsupported reference shapes fail closed. The worker's 2-MiB
output limit can reject a large index even within the file/entry limits.

Bambu's pinned [BBL manifest](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/resources/profiles/BBL.json)
separates machine/model/filament/process lists and declares bundle `02.08.00.05`.
Its machine list includes script templates, not just instantiated printers. This
source review is not installed-device qualification. The pinned
[PresetBundle source](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/PresetBundle.cpp)
loads system vendor manifests and a separate user folder; its
[GUI data-root selection](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/slic3r/GUI/GUI_App.cpp)
also permits custom data directories. Do not infer loaded presets or an installed
version from a nearby directory name. No credentials/configuration or actual
workstation directories were read to implement this package.

Windows Dell/Bambu `v2.8.0.6` remains a required untested target. Authored tests use
generated temporary files and the original MP-1a synthetic documents. No model
upload limits or source bytes are changed; no server slicing or machine control.
