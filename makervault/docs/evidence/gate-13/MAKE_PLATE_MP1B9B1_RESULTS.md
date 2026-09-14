# MP-1b-9b-1 — Inactive Windows UI helper foundation

**2026-09-14 America/New_York.** Owner directed continuation from MP-1b-9a.
Entry `5d634c3bba6f361e501649f365163da683a40772`; implementation
`e8eddf2c7bc0c58edafd493a121ef5febf9d644f`.
**Local foundation verified; native Windows execution, Linux helpers and MP-1b-9b
remain open. Nothing is activated in production.**

This checkpoint implements the Windows half first, with separate native qualification
still required. It does not defer Linux, close MP-1b, deliver end-user import, or
qualify the owner's Windows/Bambu installation. Production main/pairing/protocols,
API/web/schema 17, dependencies and all prior profile/file/worker/hint code are unchanged.

## Implemented boundary

- A separate private, single-use UI helper accepts only one browser or folder action.
  The parent uses its exact executable and fixed argument, with data over bounded
  private pipes. No shell, PATH lookup, arbitrary executable/command/title/callback,
  owner HWND, picker starting path or fallback opener. Main has no matching dispatch.
- Browser input has the exact local preview URL shape. The local server owner
  supplies **only its own URL**, permits one attempt and binds host/caller cancellation.
  Failure/timeout revokes consent and closes the listener; duplicate attempts do not
  cancel the first. Startup and launch perform no profile scan. No HTTP launch action.
- Windows amd64/arm64 uses locked-thread STA COM, System32-only ole32/shell32 loading,
  `ShellExecuteExW` and `IFileOpenDialog`. Compile-time 64-bit ABI size/offset assertions
  and Windows-only layout/flag tests are included; these are **compiled, not executed**.
  COM objects, allocated strings and optional browser process handles are released.
- 15s browser / 90s folder budgets, shortened by caller deadlines. One active or
  unreaped UI helper per parent, separate from the unchanged file-worker slot.
  Owned pipes, 1-KiB request / 32-KiB response / 4-KiB diagnostic ceilings; any stderr,
  nonzero exit, malformed/ambiguous frame or error-plus-path discards the result.
  Timeout/cancel kills only the helper and retains its slot until actual reap/cleanup.
- Windows UI copies only named desktop/profile environment variables, never arbitrary
  credentials or PATH/COMSPEC/BROWSER. This separate allowlist does not expand the
  file-worker environment. Native desktop compatibility remains untested.
- Picker output is private local authority, not a public JSON path or filesystem
  grant. The existing pure Windows root policy rejects unsafe syntax before output.
  Actual reading still requires the unchanged held-handle boundary and explicit
  consent. The asynchronous consent/session picker wiring is **not implemented**;
  no 90s dialog was added to the existing 20s HTTP handler.

The [source contract](../../../slicer-bridge/internal/presetui/README.md) records
exact limits, supported build tags, environment keys and remaining qualification.

## OS behavior not overclaimed

Shell launch acceptance is not browser readiness. Microsoft's `NOASYNC` semantics
do not provide a URI-load guarantee; the browser might open even when the helper
times out. The owner revokes the URL and never automatically retries, waits for
or terminates a potentially shared browser. Security prompts may still appear.
See [ShellExecute flags](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-shellexecuteinfow).

Filesystem-folder, single-selection, explicit-interaction, no-link-dereference and
no-recent-document flags constrain the returned selection, **not Shell browsing**.
OS UI can enumerate providers/network locations, use remembered locations or retain
other UI state. No no-I/O/no-history or picker confinement claim is made. These
effects must be checked before activation; the separate file reader is not a sandbox
for the OS dialog. See [Microsoft dialog options](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/ne-shobjidl_core-_fileopendialogoptions).

No hard-real-time kernel/startup bound, memory sandbox, installation-wide lock or
parent-crash cleanup guarantee. Ordinary killed-child tests are not uninterruptible
Windows kernel/Shell, foreground behavior, accessibility or native lifecycle proof.
Regular tests never dispatch a real Windows UI, even when later run on Windows.

## Source-bound verification

| Capture | Exit / duration | Observed result |
|---|---|---|
| `go-preflight` | 0 / 33.112 s | 194 unit / 206 top-level / 433 inclusive passes; race, formatting/vet and HTTP fixture build |
| `go-final` | 0 / 181.487 s | Same counts; six platform/architecture pairs, 36 builds, 12 short fuzz runs |
| `browser-final` | 0 / 15.365 s | 25 actual-HTTP scenarios against the completed final Go fixture |

All three fresh captures remain under the private verification root, prefixed
`containment-mp1b9b1-` and suffixed `-20260914`. **No failed verification capture in
this checkpoint**; previous gates' failures remain historical and unmodified.
Preflight captured a stable dirty implementation at the entry revision; final
Go/browser captures have clean runtime source at `e8eddf2`. No runtime/check-driver
edits occurred during their capture. Browser execution began only after the final
Go command completed successfully; the executable byte hash joins both captures.

**194 unit tests with race detection**, 12 seeded fuzz targets, **206 top-level /
433 inclusive pass events**, zero failure/skip. New tests cover exact URL syntax,
strict private frames, invalid input rejected before native action, atomic/redacted
responses, private folder JSON, platform refusal, environment allowlist, pre-cancel,
blocked stdin, hung child, busy slot, output/diagnostic overflow, malformed output,
start failure, sequential slot release and owned-URL launch/revocation/concurrency.
Native actions are injected fakes in these tests, not executed Windows APIs.

Go formatting/vet pass. Linux/Windows/macOS × amd64/arm64 compile the bridge and five
internal package-test binaries: **six targets / 36 builds**. Twelve mutation fuzz
targets each request 5s with two workers, including new private-UI framing and URL
validation; exact execution/elapsed counts are in the index. No failing corpus.
Short fuzzing and cross-compilation are not exhaustive or native-device proof.

The unchanged actual-HTTP browser harness passes **25 scenarios** using Chromium,
Firefox and WebKit headlessly on Linux at 1024×768 and 390×844. Six complete approval
flows cover **36 HTTP stages**, plus cancellation, foreign-origin refusal,
cross-origin referrer privacy and simulated launch-failure pipe teardown. Every
owned fixture exits and refuses new connections after teardown. The narrow review
screenshot was visually inspected: contained layout and visible controls.
The backend is synthetic/incomplete, not a real profile, API conformance test,
native Windows launch, physical tablet or screen-reader qualification.

[Go driver](make-plate-native-ui-check.sh), reused [browser driver](make-plate-local-server-browser.cjs),
[index](make-plate-native-ui-verification.json) and [read-only checker](make-plate-native-ui-verify.cjs)
join exact source/commands, mounted fixtures, executable, reports/screenshots and
**29 artifact hashes**, including capture metadata. The prior locked Playwright
tree is reused read-only and rehashed; no dependency install or toolchain upgrade.

Verification uses UID/GID 1000, offline disposable containers, read-only source and
fixture mounts, Go 1.26.6 image
`sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`
and Playwright 1.62.1 noble
`sha256:dcc5531e97840b9b5e794f2814476b21571c5124a3fca2267d73041f56e7580e`.
Formatting alone used a writable source mount. No host port publication or device
connection. Separately browsed Microsoft sources informed the native contract.
Release-contract check passes for v5.1.0. The existing ROADMAP whitespace warning
belongs to the owner's unchanged edits, not this implementation.

## Re-cock

Next **MP-1b-9b-2: bounded Linux native UI helpers**. Then complete asynchronous,
explicitly consented custom-folder selection in the owner/session without HTTP paths
or enlarged request deadlines. Keep production dispatch inactive until native
Windows reader/hint/UI/lifecycle, independent installed-app/bundle versions, real
profiles and matched early dispatch are qualified together. The Windows picker
must also be checked for Shell/provider effects and cancellation/foreground behavior.

MP-1c still couples scoped claim/review/commit, immutable storage, additive migration
and portable/raw recovery; MP-1d retains independent Bambu/Orca/Prusa conformance.
MP-2–4 remain unstarted. Owner-reported Windows Bambu v2.8.0.6 and physical YubiKey
remain unqualified. Mac-local import, CNC/CAM, Gate 12 desktop and further performance
tuning remain deferred; existing Mac file-open and browser scope is unchanged.

No production activation, live-vault mutation, remote import, slicing/printing,
native-device test, full-gate/security-image scan or waiver transfer. Historical
E4/R57/F26/H0 applies only to its old exact images. No gate closeout, push or release
publication. Owner ROADMAP and desktop architecture notes remain untouched.
