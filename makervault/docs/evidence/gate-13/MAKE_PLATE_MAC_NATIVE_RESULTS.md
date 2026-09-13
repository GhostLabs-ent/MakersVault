# MP-1b-2 — first native macOS worker qualification

**2026-09-12 America/New_York** (captures on September 13 UTC).
**Entry:** `7f4fe3623b7fb6494008a3f3d7a66927e601c2bf`.
**Test/driver source:** `79ac9a04db63b996725bcf430973e60e1f7e5d67`.
**Runtime implementation:** unchanged from `60bd90c`.
**Status:** targeted Intel macOS execution verified; macOS reading and MP-1b remain open.

The owner offered a Mac for testing during macOS/discovery work. Read-only SSH
preflight observed **macOS 15.7.9, build 24G830, x86_64**, unprivileged UID 501.
No Go executable was found on the login PATH. The owner describes the machine as
running OpenClaw; its configuration, data, process inventory and service state
were not inspected or changed. No application/toolchain was installed.
Host/account details remain in private transport evidence, not this public ledger.
The supplied password was entered only at SSH's interactive password prompt; it
was not put in repository files, command arguments, environment or capture logs.

## What actually ran

Three test binaries and Go's `test2json` were cross-compiled with the already-local
Go 1.26.6 image
`sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`.
The build used no network, UID/GID 1000:1000, read-only sources and disposable
container caches. No production bridge executable was transferred or installed.
The SSH transfer used the existing known-host check and a private short-lived
control socket; the archive contained only our binaries, runner and three authored
synthetic JSON fixtures. The payload was 12,005,763 bytes, SHA-256
`10ffe2421ce3910736bd50edbe2748f230262e8eaf931ae74e61c9450671f530`.

Execution stayed in one freshly created mode-0700 directory beneath `/private/tmp`,
with `GOMAXPROCS=2`, serial test execution and 90-second per-package limits.
No actual slicer profiles, credentials, applications, handlers or vault were read.

| Native test scope | Unit tests passed | Limit |
|---|---:|---|
| Pure Bambu projection | 18 | Authored fixtures, not an installed slicer's profiles |
| Portable filename/root policies, cancellation and unsupported backend | 7 | Includes Windows **syntax**, not Windows native APIs; macOS reader correctly refuses access |
| Isolated worker/process and framing checks | 9 | Includes new macOS list/project refusal regression and existing synthetic hangs, blocked stdin, cancellation/reaping, busy slot, output limits, error redaction and invalid frames |
| Total | **34** | **38** top-level / **97** inclusive pass events including four seeded fuzz targets; zero fail/skip events |

`TestWorkerListAndProjectRoundTrip` and `TestWorkerProjectionIsAtomic` were explicitly
**not run**, because successful file access is unimplemented on Darwin. The runner
contains the exact positive test allowlist; their absence is not a skip/pass or a
waiver. `TestDarwinWorkerRejectsUnimplementedReader` separately proves that private
list/project calls return `source_platform_unsupported`, no partial metadata, and
release the ordinary worker slot. Production main still has no worker dispatch.

No native race detector or mutation fuzz campaign ran. This verifies ordinary
self-exec/anonymous-pipe behavior and synthetic timeout/cancel cases on this Intel
Mac, not uninterruptible kernel I/O, parent-crash cleanup, OS resource isolation,
Apple Silicon, native Windows, handler/browser launch or actual slicer support.

## Captures and attempts

Durable private root: `/home/vinnyc/.local/state/makersvault/verification`.
The [index](make-plate-mac-verification.json) and
[read-only checker](make-plate-mac-verify.cjs) bind sources, eight log hashes,
payload hash, counts, explicit omissions and cleanup results.

| Capture | Result |
|---|---|
| `containment-mac-native-build` | Successful 8.197-second preflight build at entry revision with the new Darwin test still untracked; retained, not final-source evidence |
| `containment-mac-native-build-final` | Successful 8.295-second clean-source build at `79ac9a0` |
| `containment-mac-native-run` | Successful 11.238-second transfer/native execution; exact source clean before/after |
| `containment-mac-native-cleanup` | Successful explicit removal of the verified fixture directory; absent afterward |

Initial noninteractive key authentication was unavailable; interactive password
authentication succeeded with strict known-host checking. The idle control master
expired before cleanup, so a subsequent batch check failed authentication; a fresh
interactive connection completed inspection and cleanup. No password retry failure
or host-key bypass occurred. The compression wrapper rejected standalone `sh` and
`ssh` commands; its policy was not changed. Native SSH and the file-based capture
driver handled transport. These are orchestration attempts, not hidden test failures.

Before deletion the directory was verified as non-symlink, owned by UID 501,
mode 0700 and containing only the eight transferred files (about 24 MiB unpacked).
Only that exact directory was removed. Its archive and logs remain locally
recoverable; the control connection was explicitly closed. No user data was deleted.

## Re-cock

The new Mac is available for further **scoped** native checks; this is not blanket
permission to install tools, alter OpenClaw, run privileged probes or change local
application handlers. Next continue Bambu manifest/known-root/local-selection work
and resolve the macOS read-only file boundary, then verify native filesystem cases
on this asset. Do not replace the currently unsupported backend with an unqualified
path-based fallback or treat event-only handles as Linux `O_PATH` equivalents.

Windows Dell/Bambu `v2.8.0.6`, YubiKey, Apple Silicon and actual Bambu/Orca/Prusa
qualification remain pending. MP-1c still couples consent/authorization, storage
and portable/raw recovery. No API/web/schema/dependency/runtime implementation,
full-gate run, image scan, historical-waiver transfer, release acceptance or push.
The only bridge-tree change is a Darwin-specific test. Older source-bound checker
results stay historical; they are not rewritten to ignore this new test file.
