# MP-1b-9b-2 — Inactive Linux browser/folder helper foundation

**2026-09-14 America/New_York.** Owner authorized the Linux helper checkpoint.
Entry `810918e391148d6edfcabd8fe980c6a02de5fe27`; implementation
`47943b075370b48a28fa8e862e450c87aacf1d03`.
**Local policy/exec/lifecycle foundation verified; actual desktop qualification and
MP-1b-9b remain open. Production dispatch stays inactive.**

## Delivered boundary

- Linux amd64/arm64 maps the existing private browser/folder requests to fixed
  `/usr/bin/gio open -- <owned-preview-URL>` or directory-only `/usr/bin/zenity`
  with static title/acceptance label. No shell, helper PATH search, arbitrary
  options, initial root, fallback launcher or new Go dependency.
- The self-worker checks root-owned, non-group/other-writable `/usr/bin` ancestry
  using no-follow O_PATH handles. It requires an executable regular ELF without
  set-ID bits or capabilities, rechecks the held identity, and executes through
  its held fd. Scripts, symlinks/alternatives, writable/user-owned/special inputs
  and unknown attribute failures are refused. CWD is `/` in the child only.
- Native exec replaces the worker with the **same PID**, preserving the parent's
  timeout/cancel/kill/reap slot ownership. Browser stdio is redirected to checked
  `/dev/null` before exec, so a long-lived browser cannot retain private IPC pipes.
  Native GIO/browser diagnostics are discarded; GIO exit status signals launch
  completion, not page readiness. Post-redirection exec failure exits nonzero.
- Folder output requires a successful exit, clean diagnostic pipe, one canonical
  absolute UTF-8 path and exactly one newline. No trimming, path cleaning, URI
  conversion or multiple-result splitting. Cancel exit 1 discards partial output
  only after clean pipe completion; diagnostics/overflow still fail. Pre-exec
  failures retain bounded fixed-code JSON; successful JSON paths are refused.
- Linux desktop environment is allowlisted and reconstructed: canonical local
  home/config/runtime paths, local X11/simple Wayland and one conventional local
  session-bus socket. No inherited loader/GTK injection, arbitrary credentials,
  BROWSER, Zenity exit overrides or D-Bus tcp/abstract/autolaunch/fallback addresses.
  A fixed system PATH is provided for desktop handlers, not helper discovery.

The [Linux source contract](../../../slicer-bridge/internal/presetui/LINUX.md)
records exact arguments, environment keys, native stream semantics and prerequisites.
The Windows native implementation/ABI tests and its environment allowlist are
unchanged. The older file/hint/worker providers, production main/pairing/protocols,
API/web/schema 17 and Go dependencies are unchanged.

## Qualification boundaries

This implementation needs conventional root-owned ELF tools at `/usr/bin`, procfs
fd access and a local desktop/session-bus layout. Missing tools, headless environments,
symlinked/nonstandard packaging and other bus layouts fail unavailable; they are not
silently qualified. No packages were installed, real desktop handler changed, host
dialog opened or workstation profile read. A read-only container availability probe
found the retained browser image lacked the native tool set; this is not a native
UI pass. No broad Linux support or release-scope waiver follows from these tests.

The user's registered HTTP handler is intentional for the private preview only,
not a model-file/slicer fallback. Native GIO/GTK and desktop services remain trusted
OS components. Executable checks do not attest packages, dynamic libraries, mounts
or transitive desktop handlers. The URL becomes a local process argument; it is not
hidden from same-user inspection or guaranteed absent from desktop-side logs.

Folder selection does not grant profile-read consent or establish filesystem safety.
GTK/providers may browse/resolve locations, use portals, create folders or retain
UI/recent state. `GIO_USE_VFS=local` is not a sandbox. Only the helper PID is owned;
kill/reap does not prove cleanup of provider/service UI or a shared browser. Native
Windows/Linux desktop tests must check cancellation, timeout, foreground/accessibility,
Unicode, unsafe selections, side effects and actual version/handler compatibility.
No hard-real-time kernel, parent-crash cleanup or complete import claim.

Primary sources reviewed: GNOME [GIO open](https://github.com/GNOME/glib/blob/main/gio/gio-tool-open.c),
[Zenity directory selection](https://github.com/GNOME/zenity/blob/master/help/C/file-selection.page),
[native output](https://github.com/GNOME/zenity/blob/master/src/fileselection.c) and
[exit codes](https://github.com/GNOME/zenity/blob/master/src/util.c). These mutable
sources informed the implementation, not a pinned installed-version qualification.

## Verification

| Capture | Exit / duration | Observed outcome |
|---|---|---|
| `go-preflight` | 0 / 33.041 s | 200 unit / 213 top-level / 444 inclusive passes, race, formatting/vet, HTTP fixture build |
| `go-final` | 0 / 186.000 s | Same counts; six targets / 36 builds; 13 short mutation fuzz runs |
| `browser-final` | 0 / 16.706 s | 25 actual-HTTP scenarios against the completed final-source fixture |

Three fresh private captures, prefixed `containment-mp1b9b2-` and suffixed
`-20260914`, remain under the private verification root. No failed verification
capture in this checkpoint. Prior failed gate captures/checkers remain unchanged.
Preflight ran against stable dirty source at entry; final runtime source is clean
at `47943b0`, with identical start/end revisions/status. No source/check-driver
editing during captures. Browser execution began after the final Go command exited.

**200 unit tests with race detection**, 13 seeded fuzz targets, **213 top-level /
444 inclusive passes**, zero failure/skip. New tests cover command/environment
allowlists, unsafe display/bus/root/output cases, cancel/diagnostic precedence,
root-owned executable policy and actual held-fd exec. A harmless system `true`
binary and test-only self-exec fixture exercise Linux exec; the latter checks same
PID and `/dev/null` on all standard streams. An intentional exec failure verifies
that redirected diagnostics cannot become false success. No real GIO/Zenity UI
is dispatched by regular tests. This is ordinary Linux process evidence, not a
simulated-dialog result represented as native desktop qualification.

Formatting/vet pass. Linux/Windows/macOS × amd64/arm64 compile bridge plus five
internal package-test binaries: **36 builds**. Thirteen mutation fuzz targets each
request 5s with two workers, including Linux native-result parsing. Exact reported
execution/elapsed counts are in the index; no failing corpus. Short fuzzing and
cross-compilation are not exhaustive or native-device proof.

The unchanged actual-HTTP browser harness passes **25 scenarios** across Chromium,
Firefox and WebKit at desktop/narrow viewports. Six approval flows cover **36 HTTP
stages**; cancellation, foreign-origin refusal, outbound-referrer privacy and
simulated launch-failure teardown also pass. The synthetic fixture binary hash
joins Go and browser evidence. The narrow screenshot was visually inspected with
contained layout and visible controls. No physical tablet or screen reader tested.

[Go driver](make-plate-linux-ui-check.sh), reused [browser driver](make-plate-local-server-browser.cjs),
[index](make-plate-linux-ui-verification.json) and [read-only checker](make-plate-linux-ui-verify.cjs)
bind exact source, commands/mounts, counts, fixture executable and **29 artifact
hashes**, including metadata. Previous locked Playwright dependencies are reused
read-only and rehashed. All test containers run offline as UID/GID 1000, with
read-only source/fixtures and no host port publication. Formatting alone used a
writable source mount. Pinned Go 1.26.6 and Playwright 1.62.1 noble images are recorded
in the index; no dependency/toolchain upgrade. Release contract passes for v5.1.0.

## Re-cock

Next **MP-1b-9b-3: asynchronous, explicitly consented custom-folder selection in
the local owner/session**. Do not pass raw paths through HTTP or put a 90s dialog
inside the existing 20s handler. Keep launch/reader dispatch inactive until matched
native Windows/Linux desktop, reader/hint/lifecycle, real profiles and independently
observed installed-app/bundle versions are qualified together.

MP-1c still couples authenticated claim/review/commit, immutable storage, additive
migration and portable/raw recovery. MP-1d retains independent Bambu/Orca/Prusa
conformance; MP-2–4 remain unstarted. Windows Bambu v2.8.0.6 and physical YubiKey
remain unqualified. Mac-local import, CNC/CAM, Gate 12 desktop and further performance
tuning remain deferred; existing Mac file-open/browser scope is unchanged.

No production activation, live-vault mutation, slicing/printing, full-gate/security
scan, waiver transfer, gate closeout, push or publication. Historical E4/R57/F26/H0
remains exact-image historical evidence only. Owner ROADMAP/desktop notes untouched.
