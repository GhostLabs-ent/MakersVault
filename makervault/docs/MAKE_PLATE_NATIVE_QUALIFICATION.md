# MP-1b-9b-4 — Native qualification operator packet

**2026-09-15. Status: package preparation, not device qualification or activation.**
MP-1b-9b-4a prepares a separately tagged native-UI runner, tests, source-bound builds
and this checklist. MP-1b-9b-4b performs explicitly approved workstation UI checks.
Matched native hints/readers, real profiles and observed versions remain required
after those UI checks; a successful synthetic preview cannot close MP-1b or MP-1.

## Authority and safety boundary

- Do not deploy, publish, register handlers, change default apps, install dependencies
  or alter security controls. No remote Mac access; Mac-local import remains deferred.
- Use a non-administrator workstation session. The runner needs local UI access,
  not a password, Bambu login, printer credentials, SSH access or YubiKey.
- This packet is preparation only. Confirm the exact target, operator availability
  and permission for native browser/dialog interaction before execution. Do not
  infer profile-read or remote-access permission from owning a device.
- Native UI may browse providers/network locations, retain state or open a shared
  browser. Avoid private/remote paths. No guarantee of zero OS-side I/O or history.
  Cancellation kills the owned helper, not necessarily provider UI/shared browsers.
- The operator types an exact local confirmation before every UI run. Ctrl+C stops
  the owner; closing the browser tab does not. Keep the console available. A five-minute
  session expiry and 90s picker budget remain unchanged.
- If OS policy, SmartScreen, antivirus or other execution controls block the unsigned
  development executable, record **blocked** and stop. Do not bypass those controls.

## Required observations before device checks

Record only non-secret facts. Do not send device IDs, serial numbers, local paths,
account names, nonce URLs, form tokens, raw profile files or screenshots containing them.

| Item | Current truth | Needed before qualification |
|---|---|---|
| Windows device | Owner has a Dell tablet | Windows version/build and System type (x64/ARM64), interactive operator and explicit UI-test permission |
| Bambu Studio | Owner-reported `v2.8.0.6` | Independently observed full About build; no automatic mapping to public 2.8.2.61 fixtures |
| Browser | Unobserved native handler | Default browser name/full version, actual page readiness and behavior |
| Linux desktop | Not established | Distribution/version, CPU, desktop/session type and permitted interactive workstation |
| Linux native tools | Implementation expects fixed trusted `/usr/bin/gio` and `/usr/bin/zenity` | Installed versions/packaging and policy-compatible local session; missing/nonstandard prerequisites are not a pass |
| Profile bundle | Not observed | Separate read-only, explicitly scoped real-profile/version checkpoint; **not accessed by this runner** |
| Security key | Owner has YubiKey | Existing separate physical-key checks remain open; irrelevant to this UI fixture |

## Package selection and first non-UI check

The [qualification runner](../slicer-bridge/qualification/preset-native/README.md)
is built only with `makersvault_native_qualification`, separately from the shipping
bridge. Four candidate artifacts are prepared: Windows/Linux × amd64/arm64. Do not
use an emulated architecture run to qualify the untested native architecture.
Executable hashes/source identity are recorded in the
[verification index](evidence/gate-13/make-plate-native-qualification-verification.json).
No installer, handler registration, native Go installation or package-manager step.

After confirming the target and approved transfer method, copy **only the matching
executable** from the source-bound private final capture. Keep it in an ordinary
user-owned working folder. Check its SHA-256 against the index before running it.
Do not transfer the whole private evidence directory or distribute a preflight build.

Windows PowerShell, x64 example (ARM64 uses the correspondingly named artifact):

```powershell
Get-FileHash .\preset-native-windows-amd64.exe -Algorithm SHA256
.\preset-native-windows-amd64.exe --inspect
```

Linux amd64 example:

```sh
sha256sum ./preset-native-linux-amd64
./preset-native-linux-amd64 --inspect
```

Inspection prints only build/runtime identifiers and `gate_qualified: false`. It
does not inspect installed slicers, contact the vault, open UI, prove prerequisites
or establish native support. Stop on a hash/source mismatch or unsupported runtime.

## Approved UI run

Once target/permission and inspection are recorded, run the same executable with
`--ui-fixture` from an interactive console **without output redirection**. Read the
notice and type `START UI TEST` only if you approve the described native actions.
Character-device checks are a usability guard, not a security authentication boundary.
The console must successfully display the notice before confirmation is accepted.

The program starts the existing loopback owner and makes one native browser-launch
attempt. The displayed vault address must be `https://qualification.invalid`; it is
an inert label, not contacted. A native launch failure revokes the owner. Do not
paste an invented URL, switch to a fallback opener or reconfigure the default browser
to turn a failed observation into a pass. Start a fresh run only after recording it.

All hints, account choices and preview data are **synthetic in memory**, including
`SYNTHETIC UI TEST - NOT A PRINTER`. No selected directory is opened by the metadata
backend; the executable has no file-worker dispatch. The native dialog itself can
browse filesystem/provider state. This runner cannot verify actual preset reads,
native location hints, slicer launch, installed versions, import, printing or slicing.

## Scenario matrix — separate fresh run for each row

Record `not run`, `passed`, `failed` or `blocked`, exact binary hash/source and the
specific native observations. OS launch acceptance alone never passes readiness.

| ID | Action after initial consent notice | Required observation / limit |
|---|---|---|
| NQ-01 | Start UI fixture; navigate with keyboard/tablet | Correct page actually loads in the observed browser; focus/controls usable, no horizontal overflow; synthetic origin visible |
| NQ-02 | Choose custom folder; select a harmless local directory; refresh; explicitly confirm folder, system-only source, fixture preset and preview | Native dialog visible/usable, folder unselected until chosen, no path rendered in custom choice/review, only synthetic metadata; exact approval closes owner |
| NQ-03 | Start picker; cancel **in the native dialog**; refresh | No metadata read or automatic fallback, fixed cancellation warning; explicit retry/start-over still possible |
| NQ-04 | Start picker; use page **Cancel folder selection**; refresh | UI remains responsive, cancellation visible; no replacement dialog queued before previous callback ends; separately note any lingering OS/provider UI |
| NQ-05 | Start picker; press Ctrl+C in owner console | Owner revokes the page and cancels helper; reloading the old page fails; explicitly record whether dialog/provider UI remains |
| NQ-06 | Leave picker open past its 90s budget, then refresh | Fixed timeout/failure, no implicit selection/read, no late success; note actual observed timing, not a hard-real-time guarantee |
| NQ-07 | Keep owner open without approval until five-minute expiry | Owner closes; old URL becomes unusable; closing a tab earlier is **not** evidence of owner shutdown |
| NQ-08 | Select an existing harmless Unicode-named local directory | Native display and explicit selection behave correctly; synthetic metadata still contains no selected path; do not create/delete user data automatically |
| NQ-09 | Missing/restricted browser or Linux-tool/session prerequisites on a separately approved suitable test environment | Fail unavailable without fallback or handler/dependency changes; otherwise mark not run, never break the tablet's working configuration to manufacture the case |
| NQ-10 | Unsafe/remote/provider selection cases only on a separately approved controlled fixture environment | Record UI/provider I/O and returned-selection refusal separately from reader confinement; this synthetic runner **cannot prove no-follow/reparse filesystem-read safety** |

Do not deliberately browse real remote shares, sensitive profiles, device namespaces
or untrusted mounts on the user's workstation. Preserve unsupported/blocked cases.
A program exit or disappearance of its helper does not prove OS service/provider
cleanup, parent-crash cleanup or deletion of desktop history.

## Result handoff and follow-on gate

The runner emits a small terminal JSON receipt with source/runtime identity, fixed
outcome, OS browser acceptance and optional synthetic-review digest. It never emits
the nonce URL, selected path, account name, raw preview or native diagnostic. Copy
that receipt and a sanitized observation row below; do not redirect an interactive
run or include raw UI/provider logs. Exit zero is an observation, **not qualification**;
`gate_qualified` always remains false.

```text
Scenario:
Status: not run | passed | failed | blocked
Date / target OS-build / CPU / browser-version:
Executable SHA-256 / source revision:
Observed page and dialog behavior:
Observed cancellation/timeout/provider side effects:
Sanitized runner receipt:
Remaining limits / follow-up:
```

No result rows are populated by preparation or container tests. The packet initially
qualifies **zero** native devices. Review each observed environment independently.
After UI evidence is accepted, prepare the separate matched native hint/reader and
explicit real-profile/version checkpoint. Production activation still requires those
checks and reviewed dispatch; MP-1c retains authenticated claim/review/commit and
the coherent storage/migration/portable/raw-recovery work. MP-2–4 remain unstarted.
