# Native UI qualification runner — not a shipping bridge

This separate executable requires `-tags makersvault_native_qualification` and is
excluded from ordinary builds. It adds exact early **UI-helper** self-dispatch only
here; `cmd/slicer-bridge`, installers, protocol handlers and file-worker dispatch
are untouched. It accepts no URL, root, account, executable or settings arguments.

`--inspect` prints source revision, Go runtime and CPU/OS identifiers only. It does
not open UI, inspect installed apps, prove desktop prerequisites or qualify anything.

`--ui-fixture` requires character-device input/output and an exact `START UI TEST`
confirmation. That is a local usability/consent guard, not authentication against
same-user processes. It starts the existing five-minute numeric-loopback consent
owner and makes one native browser-launch attempt. The console does not print the
nonce URL or selected path, and there is no default-opener/manual-URL fallback.
Ctrl+C revokes the owner. Closing the tab does not; expiry remains the backstop.

The browser and requested folder dialog are **real native UI**. All hints, accounts
and metadata are **synthetic in-memory fixtures**, clearly named as not a printer;
the selected path is never passed to a filesystem reader/worker. The placeholder
origin is `https://qualification.invalid`, never contacted. Default synthetic roots
need not exist. Choosing a real directory does not turn it into a real profile test.
This program creates no profile/evidence files, changes no handler, installs no app
and submits nothing to a vault. Native UI/providers may still browse, access network
locations or retain desktop state; this program is not an OS UI sandbox.

Local approval consumes and hashes only the synthetic review, then closes the owner.
The small JSON receipt contains runtime identity, fixed outcome, OS launch acceptance
and (on consumption) a synthetic review digest. It excludes paths, URLs, account names,
raw errors and preview bytes. `gate_qualified` is **always false**. Exit zero means
the harness completed an observation, not that the native UI scenario passed.
Human-observed page readiness, dialog behavior and cleanup are recorded separately.

Ordinary tests and qualification tests do not launch native dialogs. Qualification
tests inject a fake owner or use a real loopback host without calling its launcher.
Only an explicitly started manual run (or its fixed private UI child) dispatches UI.
Private child framing is not independent authentication. Do not expose or wrap the
private argument as a server endpoint, automation API or general URL opener.

Follow the [operator packet](../../../docs/MAKE_PLATE_NATIVE_QUALIFICATION.md).
Reader/hint execution, real profiles, installed slicer/bundle identity and matched
production dispatch remain separate gates; this tool cannot qualify those checks.
No macOS artifact or permission to bypass OS execution/security prompts is supplied.
