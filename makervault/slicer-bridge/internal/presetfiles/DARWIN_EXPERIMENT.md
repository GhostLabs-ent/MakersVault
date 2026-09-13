# macOS reader experiment — not a release backend

Only compiled with `makersvault_darwin_reader_experiment`. Default Darwin builds
still return `source_platform_unsupported`; no production bridge dispatch is added.
This is a native investigation of the reader boundary, **not** permission to weaken
MP-1b or claim macOS support from ordinary read tests.

The experiment walks a selected absolute root using held directory descriptors,
single-component `fstatat64`/`openat`, no-follow flags, local APFS checks and inode/
mode/link/size/mtime/ctime/birthtime/generation comparisons. Static special files,
symlinks, hard links and dataless entries fail before a data open. Opened files
are revalidated before reading; reads are read-only and retain shared budgets,
cancellation, redacted errors and no-partial-catalog behavior. No name resolution
through `/dev/fd`, `O_EVTONLY` read conversion, permission changes or source copies.

**Unmet properties:** pre/post metadata validation cannot undo the effect of
opening a raced-in special file. APFS/fSID checks happen after opening a component;
they do not prevent every mount/automount/recall side effect before rejection.
These are not Linux `O_PATH`/`NO_XDEV` guarantees. The test suite contains deliberate
FIFO counterexamples (no data transmission) which must be reported as safety gaps,
even when their regression tests pass. A local privileged attacker is not sandboxed.
Raw Darwin syscall/struct ABI checks on one Intel OS build do not qualify future
OS releases, Apple Silicon or a stable public-library distribution strategy.

Before enabling a default backend, resolve these properties with an OS-enforced
boundary and native negative controls, or obtain an explicit owner-reviewed
contract/support-scope decision. Do not silently convert this tag into a default,
add a weaker fallback, claim a whole-system sandbox, or change other platform readers.

Primary source review used Apple's pinned XNU `xnu-11417.101.15`, not a claim that
it exactly matches the owner's kernel build. [Open flags](https://raw.githubusercontent.com/apple-oss-distributions/xnu/xnu-11417.101.15/bsd/sys/fcntl.h),
[syscall definitions](https://raw.githubusercontent.com/apple-oss-distributions/xnu/xnu-11417.101.15/bsd/kern/syscalls.master),
[stat flags/layout](https://raw.githubusercontent.com/apple-oss-distributions/xnu/xnu-11417.101.15/bsd/sys/stat.h)
and [filesystem flags](https://raw.githubusercontent.com/apple-oss-distributions/xnu/xnu-11417.101.15/bsd/sys/mount.h)
inform the experimental ABI. The [open authorization path](https://raw.githubusercontent.com/apple-oss-distributions/xnu/xnu-11417.101.15/bsd/vfs/vfs_subr.c)
and [vnode open dispatch](https://raw.githubusercontent.com/apple-oss-distributions/xnu/xnu-11417.101.15/bsd/vfs/vfs_vnops.c)
do not establish metadata-only special-file handles. Apple's [event-only documentation](https://developer.apple.com/documentation/system/filedescriptor/openoptions/eventonly)
describes change monitoring, not an `O_PATH` equivalent. No Apple code was copied.
