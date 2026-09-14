# Inactive native UI helpers — MP-1b-9b-1

Windows amd64/arm64 implementation foundation, **not native qualification**.
Production main has no dispatch/caller; existing pairing and file-open launchers
are unchanged. Linux native helpers remain the next checkpoint, not deferred;
macOS new local preset import remains owner-deferred. Unsupported targets refuse.
Neither helper slices, prints, opens model files or uploads anything.

## Local authority and lifecycle

The parent launches its exact `os.Executable` with one fixed private argument and
one bounded stdin frame. No command, executable, callback, HWND or picker starting
path comes from the wire. Browser input is only numeric IPv4 loopback HTTP, canonical
nonzero port, and the preview's 64-lowercase-hex nonce path; no query, credentials,
fragment or encoded alias. Syntax is not ownership: `LocalServer.OpenBrowser`
supplies only its own URL, permits one attempt, binds host/caller cancellation and
revokes the host on failure. Duplicate attempts do not revoke the first launch.
The launch caller context bounds that attempt; after success the host/session
context and expiry own the page lifetime. Success never means browser readiness.

Browser timeout 15s; folder timeout 90s, shortened by caller cancellation/deadline.
The separate UI supervisor has one active/unreaped child per parent, owned pipes,
1-KiB input, 32-KiB output and 4-KiB diagnostic limits. Any stderr or exit failure
discards output and returns a fixed code. Malformed, duplicate, aliased, nested,
oversized or partial/error-plus-path frames fail closed. A selected folder has no
exported JSON field; its path is returned only to a local owner through private IPC.
The existing pure Windows root policy rejects UNC/device/drive-root/traversal/ADS
syntax. Selection does not establish existence or filesystem safety; the separate
held-handle reader must still enforce all pre-open and profile-read boundaries.

Timeout/cancel kills only the UI helper, returns without a synchronous kernel wait,
and retains its slot until actual reap and pipe cleanup. Ordinary subprocess tests
exercise these properties on Linux, including blocked input/output and redaction.
This is not installation-wide exclusion, an OS memory sandbox, hard real-time
kernel/startup assurance or guaranteed parent-crash cleanup. The browser is not a
helper-owned descendant to kill: it may be a shared existing user process.

Windows UI environment is an explicit separate allowlist: SystemRoot, SystemDrive,
USERPROFILE, LOCALAPPDATA, APPDATA, TEMP and TMP, plus the fixed race-test exit option.
No PATH/COMSPEC/BROWSER or arbitrary parent credentials are copied. Desktop/profile
variables are needed for OS UI context; compatibility needs native testing. The
more restrictive **file-worker environment is unchanged**. No shell command,
PowerShell script, PATH lookup or fallback opener is used by this new package.

## Windows implementation and unqualified OS behavior

COM runs in a locked STA thread; kernel32 is the KnownDLL bootstrap, with explicit
System32-only loading of ole32/shell32. COM objects, task-allocated strings and any
returned browser process handle are released. Direct SyscallN pointer conversions
preserve Go pointer lifetime; 64-bit ShellExecute structure size/process offset are
compile-time checked. Windows test binaries include layout/flag tests but do not
open any real UI, even when later run natively.

`ShellExecuteExW` uses the literal `open` verb and validated URL, no command parameters,
directory or caller-selected application. It relies on the user's registered HTTP
handler. `SEE_MASK_NOASYNC` does **not** guarantee URI dispatch/readiness; acceptance
can precede page loading, and a browser might open despite a timeout. We revoke the
URL, never automatically retry, wait for or terminate the browser. `FLAG_NO_UI` is
not suppression of every OS security prompt. See Microsoft's [ShellExecuteExW](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shellexecuteexw)
and [SHELLEXECUTEINFO flags](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-shellexecuteinfow).

`IFileOpenDialog` requests one existing filesystem folder, explicit interaction,
no link dereference, no CWD change and no recent-document addition. Static title;
no remote owner window or starting folder. The returned filesystem path is bounded
and revalidated before private output. These flags constrain the selection; **they
do not confine Shell browsing**. OS UI may enumerate providers/network locations,
use remembered locations or retain other UI state. No no-I/O/no-history claim is
made. Before activation, native checks must cover Shell/provider behavior,
foreground/accessibility, cancellation/timeout, unavailable handler, environment
compatibility, Unicode paths and reparse/remote selection rejection. See Microsoft's
[dialog options](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/ne-shobjidl_core-_fileopendialogoptions)
and [COM dialog lifecycle](https://learn.microsoft.com/en-us/windows/win32/learnwin32/example--the-open-dialog-box).
GUIDs/vtable slots were checked against the [Microsoft SDK header](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/ShObjIdl_core.h)
on 2026-09-14; this mutable reference is not a pinned SDK or device qualification.

## Required next work

MP-1b-9b remains open: Linux helper implementation, asynchronous **consented** custom
folder selection in the local owner/session (never a raw HTTP path), then matched
private dispatch/native Windows qualification and real profile/version evidence.
Do not put a 90s dialog inside the existing 20s HTTP handler or raise that budget.
Independent installed-app/bundle versions, reader/hint lifecycle, owner Windows
Bambu Studio v2.8.0.6 and native UI must be qualified together before activation.
MP-1c still owns authenticated claim/review/commit, storage and portable/raw recovery.
