# Local file access boundary — MP-1b-1

Internal, read-only and **not called by the bridge CLI**. This is the first part
of MP-1b, not completed workstation discovery or a user-facing import feature.
Windows/macOS backends remain unimplemented and fail closed; their cross-builds
do not qualify native behavior. No API, protocol, background scan or saved setting
is added. Do not activate this code until the remaining MP-1b boundaries are met.

## Operations

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
- `Input` cannot convey paths/files through JSON. This is defense in depth, NOT
  authorization: only a future locally consented adapter may construct it. No
  browser/server path, environment expansion or shell interpretation is permitted.

Both operations impose a 15-second **cooperative** deadline; LoadBambu keeps the
parser's 10,000-file / 8-MiB-file / 128-MiB-total limits. It checks cancellation
between operations and reads. Regular-file kernel I/O can still stall. A bounded
isolated worker with parent-enforced timeout/cancellation is required before any
CLI activation; no goroutine is used to hide an uninterruptible read.

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

## Remaining MP-1b work

Windows/macOS native handle/reparse/mount/local-volume implementations and tests;
hard-deadline worker isolation; adapter-owned known locations and local root
selection; manifest-only machine discovery (not model/process/filament documents),
user namespaces and independently observed versions. Bambu's pinned
[PresetBundle source](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/libslic3r/PresetBundle.cpp)
loads system vendor manifests and a separate user folder; its
[GUI data-root selection](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/slic3r/GUI/GUI_App.cpp)
also permits custom data directories. Do not infer loaded presets or an installed
version from a nearby directory name. No credentials/configuration or actual
workstation directories were read to implement this package.

Windows Dell/Bambu `v2.8.0.6` remains a required untested target. All tests use
generated temporary files and the original MP-1a synthetic documents. No model
upload limits or source bytes are changed; no server slicing or machine control.
