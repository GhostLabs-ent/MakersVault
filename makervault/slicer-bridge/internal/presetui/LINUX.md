# Linux native UI foundation — MP-1b-9b-2

**Inactive:** no main dispatch, installed-handler mutation or end-user preset import.
The bridge runs on the slicer workstation, not the Docker server. This checkpoint
uses system GIO/Zenity without a new Go dependency, helper service or package install.
Policy and ordinary Linux exec/pipe behavior are tested in isolated containers;
actual GIO/Zenity desktop/version/provider behavior still requires qualification.

## Fixed invocation and executable boundary

The parent sends one private frame to its own executable and supervises its PID.
On Linux that worker replaces itself with a held native executable, **same PID**:

- Browser: `/usr/bin/gio open -- <exact-owned-preview-URL>`.
- Folder: `/usr/bin/zenity --file-selection --directory`, fixed MakersVault title
  and acceptance label. No initial filename/folder, multiple selection, save mode,
  arbitrary button, remote window ID or user/server-defined CLI options.

Only those two tool names are selected by production helper code. Starting at `/`,
O_PATH handles classify every `/usr/bin` component without following symlinks.
Ancestry must be root-owned directories without group/other write or set-ID bits;
the tool must be a root-owned executable regular file with the same restrictions.
The held inode is reopened via `/proc/self/fd`, identity/mode rechecked, capability
xattrs rejected, and four ELF magic bytes checked before executing that held file.
Scripts, symlinks/alternatives, user-owned tools, writable ancestry, special files,
unknown capability-query failures and missing tools are refused. Execution does
not re-resolve the original tool pathname. Child CWD is `/`.

These are local executable-selection controls, **not** signed-package verification,
dynamic-library/loader/desktop-handler attestation, privileged-mount defense or an
OS sandbox. The user's registered HTTP handler is intentionally used for this one
local preview URL; it is never a model-file/slicer fallback. Tools, libraries,
desktop configuration and the current user session remain trusted OS components.
GIO or GTK may contact desktop services or launch other processes. Only the helper
PID is owned/killed; no process-group kill targets a potentially shared browser.

## Environment and prerequisites

Only HOME, XDG_CONFIG_HOME, XDG_DATA_HOME, XDG_RUNTIME_DIR, DISPLAY, WAYLAND_DISPLAY,
XAUTHORITY and DBUS_SESSION_BUS_ADDRESS cross the Linux self-worker boundary.
The exec stage reconstructs a validated environment, adding fixed
`PATH=/usr/bin:/bin`, `LANG=C.UTF-8`, `LC_ALL=C.UTF-8`, `GIO_USE_VFS=local`.
The helper itself has no PATH search; registered desktop handlers may resolve their
own executables through that fixed system PATH. No inherited BROWSER, loader/GTK/GIO
injection variables, arbitrary credentials, or Zenity/DIALOG exit-code overrides.
The older file-worker environment and Windows UI allowlist are unchanged.

HOME and XDG_RUNTIME_DIR are required canonical absolute paths. Optional config/data
and Xauthority paths use the existing Linux root syntax policy. At least one local
X11 display (`:0`, `:0.0`, `unix:0`) or simple Wayland socket name is required. No
remote X11 hostname, arbitrary Wayland path or traversal. The only accepted session
bus address is `unix:path=<XDG_RUNTIME_DIR>/bus`, optionally with a validated 32-hex
GUID; the address is reconstructed without that GUID. No tcp/abstract/exec/autolaunch,
percent escapes or fallback address list. An omitted address uses the same explicit
local socket, not D-Bus auto-discovery. No bus is contacted by environment validation.

This implementation therefore needs a conventional `/usr/bin` GIO/Zenity desktop,
readable procfs fd links and that local session-bus layout. Headless servers,
nonstandard/symlinked packaging and other bus layouts fail unavailable; they are
not silently qualified. Native desktop prerequisites and support wording must be
reviewed before activation; no distro-wide compatibility or release-scope waiver.

## Output and lifecycle

The existing parent owns pipes, 15s browser/90s picker deadlines, cancel/kill and
actual-reap slot release. No extra wrapper child is left behind by native exec.
Browser stdin/stdout/stderr are redirected to checked Linux `/dev/null` (character
device 1:3) **before** exec. A browser cannot inherit private response/diagnostic
pipes or prolong EOF. GIO success is its exit status, not absence of diagnostics,
browser readiness, page load or absence of a later application failure. Exec or
stdio-redirection failure after this point exits nonzero, never empty false success.
GIO/native-browser diagnostics are intentionally discarded, not persisted.
The nonce URL becomes a local GIO/browser argument after the private-frame phase;
there is no concealment claim against same-user process inspection or desktop logs.

Folder success requires exit 0, no stderr and exactly one UTF-8 absolute canonical
path followed by one newline. No trim, split, URI conversion or path normalization:
ambiguous/multiple results, control characters, root `/` and unsafe syntax fail.
Exit 1 becomes cancelled only after all pipes complete without diagnostics/overflow;
any partial output is discarded. Other exits fail. Pre-exec errors retain bounded
fixed-code JSON frames; Linux never accepts a successful JSON path frame instead
of native tool output. No raw path is sent to HTTP, logs or the vault.

Selection is not read consent, existence/type proof or filesystem confinement.
GTK/provider dialogs may browse or resolve links, enumerate locations, use portals,
create folders or retain UI/recent state; `GIO_USE_VFS=local` is not a sandbox.
The independent held-handle profile reader still enforces its pre-open boundary.
Native qualification must check foreground/accessibility, Unicode, cancellation,
timeout/provider cleanup, remote/reparse selections, desktop side effects and
default-handler behavior. Killing the helper does not prove portal/provider UI or
desktop-service cleanup, parent-crash cleanup or a hard-real-time kernel deadline.

## References and next checkpoint

GNOME's [GIO open implementation](https://github.com/GNOME/glib/blob/main/gio/gio-tool-open.c)
uses the registered URI handler and reports launch completion, not page readiness.
Zenity's [file-selection documentation](https://github.com/GNOME/zenity/blob/master/help/C/file-selection.page),
[selection output](https://github.com/GNOME/zenity/blob/master/src/fileselection.c) and
[exit-code handling](https://github.com/GNOME/zenity/blob/master/src/util.c) explain
the fixed directory flag, newline output and cancel status. Mutable sources reviewed
2026-09-14; no installed version or pinned vendor build is qualified by that review.
Direct portal IPC was considered; this slice does not add a D-Bus client dependency
or claim that using GTK tools avoids portal/backend effects.

Next MP-1b-9b-3 connects asynchronous, explicitly consented custom-folder selection
to the local owner/session, never raw HTTP paths or a 90s dialog inside a 20s handler.
Native Windows/Linux desktop, real profile/version and matched early-dispatch checks
remain mandatory before activation. MP-1c retains authenticated persistence/recovery.
