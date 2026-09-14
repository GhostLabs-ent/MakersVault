# Local account choices and native hints — MP-1b-7

Internal foundation only. Production main does not dispatch the worker or acquire
hints. There is no new browser/API/CLI action, listener, saved preference, profile
import or automatically selected installation/account. New Mac-local preset import
remains owner-deferred, including native hints and account listing.

## Account choices are not selection

`ListBambuAccounts(ctx, chosenDataRoot)` holds the selected root and fixed `user`
child, enumerates direct entries in batches of 64, and checks confined metadata
handles. It never reads a manifest, account settings, sidecars or profile bodies;
it does not descend into account directories. `AccountChoices.Names` is sorted
**private local picker data**, not an import schema or authenticated cloud identity.
It deliberately has no active/default/selected field. A folder literally named
`default` is an ordinary choice requiring the same explicit selection as any other.

Every entry counts toward 10,000, including ignored ordinary single-link files.
Invalid portable names, case-fold collisions (also involving ignored sidecars),
symlinks/reparse points, special files, hard-linked files, unsupported filesystems,
mount boundaries, unavailable metadata and observed ancestry changes fail the
whole operation. No partial choices escape. Linux uses `O_PATH` with the existing
`openat2` boundary, including `NO_XDEV` below the selected root. Windows classifies
a relative metadata-only handle using the existing NTFS/volume/reparse checks,
without adding data/list access to that child handle. Directory entry type hints
are not trusted. Windows behavior is compiled, not natively qualified.

One cooperative 15-second context covers the listing; the private `accounts`
worker operation retains the parent's deadline, cancellation, single-worker/reap
slot and 2-MiB output ceiling. A legal 10,000-name list can exceed that byte ceiling
and must fail rather than truncate. The parent validates sorted portable bounded
choices and rejects cross-operation, unknown or partial results. Account/picks/
inputs are forbidden on the `accounts` request. Paths enter only via the existing
local-only request/private pipe, never public JSON authority.

An existing empty `user` directory returns an empty list. A missing/unreadable
`user` returns `source_unavailable`, not a fabricated empty success. The eventual
UI can separately offer an explicit system-only choice; it must not silently
choose that after a failed account listing. A directory can be listed even if its
contents are unreadable, missing or unsupported: enumeration is not qualification.
Subsequent explicit `discover`/`select` rescans the chosen account, and existing
empty-account semantics remain explicitly system-only. No listing token pins a
filesystem snapshot; observed changes fail, but this is not an atomic snapshot.

## Native hints are unobserved suggestions

`NativeBambuLocations(ctx)` obtains current-user hints on the **local workstation**
then calls the unchanged pure planner. It does not verify directory existence,
find executables, determine installed versions or select a Bambu release channel.
An explicitly chosen custom root still uses the separate pure planner and replaces
known-location candidates; native acquisition itself has no remote/custom input.

- Linux reads only `XDG_CONFIG_HOME`; only when empty/unset does it read `HOME`
  to propose `.config`. No passwd/NSS lookup or filesystem walk. Invalid nonempty
  XDG or absent/invalid home fails closed, with no fallback to another namespace.
  This stricter invalid-XDG refusal is deliberate; it is not a claim to reproduce
  every desktop library's fallback behavior.
- Windows asks `SHGetKnownFolderPath` for `FOLDERID_RoamingAppData`, current-user
  NULL token, with only `KF_FLAG_DONT_VERIFY`. It does not request create/init or
  default-path behavior. Fixed shell/allocator DLLs load with
  `LOAD_LIBRARY_SEARCH_SYSTEM32`, not working-directory/PATH search. Returned
  allocations are freed on success or failure; bounded path syntax still rejects
  UNC/device/relative roots. No `%APPDATA%` expansion or guessed home fallback.
- Native diagnostics become a fixed `source_hint_unavailable`; cancellation and
  unsupported-platform results are explicit. No private path is placed in errors.

The sanitized worker intentionally does **not** inherit HOME/XDG. MP-1b-8's
[consent foundation](../presetconsent/README.md) now calls `presetworker.NativeLocations`:
Windows native acquisition runs inside the existing hard-deadline worker via a
no-input `native-locations` operation; Linux copies environment strings and runs
the pure planner in the parent, with no filesystem/NSS lookup. Its child refuses
native hints rather than guessing from sanitized environment. Browser/server fields
cannot fill any hint. The direct `NativeBambuLocations` API remains cooperative.
`DONT_VERIFY` is not itself proof of bounded Shell latency or no internal OS work;
the worker isolates that call without changing the underlying provider/supervisor.
No real Windows known-folder call or installed-profile scan was performed here;
native Windows/lifecycle and matched-main qualification remain open.

## Primary contracts reviewed September 14, 2026

- Bambu's pinned [data-root logic](https://raw.githubusercontent.com/bambulab/BambuStudio/926a7192574bcb9b3a732e1ec59a46d79cb45466/src/slic3r/GUI/GUI_App.cpp) defines the Linux XDG/home roots and Beta/Internal suffixes already used by the planner.
- [XDG Base Directory Specification 0.8](https://specifications.freedesktop.org/basedir/0.8/) requires absolute environment paths and defines the empty/unset configuration default; our nonempty-invalid hint refusal is intentionally narrower.
- Microsoft [SHGetKnownFolderPath](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shgetknownfolderpath) defines current-user token selection, returned allocation and freeing obligations.
- [Known-folder flags](https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/ne-shlobj_core-known_folder_flag) distinguish non-verifying lookup from creation, initialization and default paths.
- [Known-folder identifiers](https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid) supplies the RoamingAppData GUID; [LoadLibraryExW](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw) specifies the System32-only search flag.

Source review is not proof about the owner's reported Windows Bambu v2.8.0.6.
The inactive local selector/consent foundation exists; server/launcher integration,
native hint/reader/lifecycle qualification, independent
installed versions/real profiles and matched main remain open. No API/schema,
normal upload limit, geometry, slicing or existing Mac file-open behavior changes.
