# MP-1b-3 — native macOS reader experiment; safety gate remains open

**2026-09-13.** Owner directs “Okay lets do it with the mac.” Entry `3bb5d9c`;
experimental implementation `ed97fdc`; corrected native-test source `907cddd`.
This is bounded local implementation/testing, not acceptance, installation or
publication. MP-1b and MP-1 remain **OPEN**.

## Outcome

The explicitly tagged experimental reader successfully lists and projects authored
Bambu JSON fixtures on the owner's Intel Mac. It is **not a release backend**:
two native counterexamples demonstrate unmet pre-open safety properties. Default
Darwin builds still return `source_platform_unsupported`; existing bridge file-open
protocols and production main are unchanged. There is no production worker dispatch,
real profile discovery, preset import API, schema change or real slicer launch.

| Native corrected execution at `907cddd` | Actual result | What it establishes |
|---|---|---|
| Default build: 34 unit tests, four seed-fuzz targets | Pass | Parser/policy, ordinary worker lifecycle and explicit unsupported-reader refusal |
| Experimental build: 42 ordinary unit checks, four seed-fuzz targets | Pass | Synthetic reads, source-byte preservation, held-root behavior, permissions, symlink replacement, bounded worker round trip and atomic rejection |
| Experimental build: two counterexample regression tests | Reproduced **FAILED safety properties** | Event-only FIFO open has an endpoint effect; a post-open check detects raced-in FIFO replacement too late to prevent opening it |

The Go runner reports 44 experimental unit tests because it counts the two expected
counterexample reproductions as passes. Combined totals are **86 top-level / 209
inclusive pass events**, zero Go fail/skip events. These are not 86 independent
security guarantees: shared tests run in both variants, subtests/seeds contribute
to inclusive totals, and the two counterexamples are explicit safety failures.
The two successful-reader worker tests excluded from the default variant both run
and pass in the experimental variant. No ordinary-read result closes the safety gate.

## Implementation and failed approaches

The [experimental backend and rationale](../../../slicer-bridge/internal/presetfiles/DARWIN_EXPERIMENT.md)
are compiled only with `makersvault_darwin_reader_experiment`. The reader uses held
directory descriptors, one-component `fstatat64`/`openat`, no-follow flags, read-only
handles and local APFS/type/link/dataless/identity checks. Shared parsing budgets,
cancellation, redacted errors and no-partial-catalog semantics remain. No alternate
backend, permission change, source copy or weakened fallback is selected on failure.

Native testing found `O_NOFOLLOW | O_NOFOLLOW_ANY` returns `EINVAL` on this Mac.
The corrected reader uses the stronger `O_NOFOLLOW_ANY` alone; its native flag
matrix requires that combination to fail and the individual strong flag to work.
Raw syscall numbers/stat layout are experimental, checked against pinned Apple
sources and this native OS, not a stable distribution or future-OS ABI guarantee.

Two deliberately isolated, no-data-transfer FIFO tests establish:

1. `O_EVTONLY | O_NONBLOCK | O_NOFOLLOW` creates a FIFO reader endpoint; an otherwise
   unpaired writer can then open. It is not demonstrated to be a metadata-only
   substitute for Linux `O_PATH`.
2. Checking metadata, opening a replacement FIFO and then checking the descriptor
   identifies the replacement **after** the endpoint was opened. Rejecting it before
   reading cannot undo that open effect.

Local APFS/fSID checks also occur after opening components; they do not establish
prevention of mount, automount or recall effects. No device, privileged mount or
dataless/recall fixture was exercised. No claim of whole-system sandboxing,
uninterruptible kernel-I/O termination, parent-crash cleanup or cross-process lock
is supported. This is evidence about the tested approaches, not proof that a safe
macOS implementation is impossible. Pinned Apple primary references are retained
in the experimental rationale; they are not claimed to match the owner's kernel
revision exactly, and no Apple implementation code was copied.

## Execution and retained failures

Observed native asset: macOS **15.7.9 / 24G830**, **x86_64**, unprivileged UID 501.
No Go toolchain was on PATH. Test binaries were cross-built with the existing pinned
Go image (`sha256:0d1d3a794be25f809dd2cb3160d8c73276c4056a9f8242a138e908ddeee7b6b6`)
in disposable network-disabled, UID 1000 containers with read-only source mounts.
The final build includes six default/experimental Intel test binaries, `test2json`,
the runner and three authored JSON fixtures in each variant. Two experimental
Apple Silicon test binaries only compile in the container; they were not executed
or installed. Native tests are serial, two Go processors, 90-second package limits.
No native race detector or mutation-fuzz run was performed.

All ten captures remain under the private operator verification directory; exact
source states, command argv, start/end times, exit codes and log hashes are retained
in each `result.json`. Host/account connection details are not copied into this
public report or index. Capture names below omit `containment-mac-reader-`.

| Capture | Source | Exit / actual result |
|---|---|---|
| `build-preflight` | Dirty entry `3bb5d9c` | 0; experimental cross-build only |
| `native-preflight` | Dirty entry `3bb5d9c` | **1**; ordinary opens fail, default 34 pass; experimental worker not run |
| `build-debug` | Dirty entry `3bb5d9c` | 0; adds native primitive diagnostics |
| `native-debug` | Dirty entry `3bb5d9c` | **1**; root open reports `EINVAL`; experimental worker not run |
| `build-final` | Clean `ed97fdc` | 0; historical attempt name, not the accepted final result |
| `native-final` | Clean `ed97fdc` | **1**; root-only flag change insufficient; child open still has conflicting flags; experimental worker not run |
| `linux-final` | Clean `ed97fdc` | 0; 80 unit tests/race, 84 top-level / 166 inclusive passes, vet, six target builds and four fuzz smokes |
| `build-corrected` | Clean `907cddd` | 0; corrected native flag matrix, default/experimental builds, experimental vet, formatting and two arm64 compile-only checks |
| `native-corrected` | Clean `907cddd` | 0; 34 default + 42 ordinary experimental checks + two reproduced safety gaps, eight seed-fuzz targets |
| `cleanup` | Clean `907cddd` | 0; all four owned remote fixture directories removed and absence verified |

The incorrect initial root-specific flag hypothesis and all three failed native
runs are retained, not relabeled as passes. A separate read-only Perl flag probe
against the fixed filesystem root identified the incompatible flag combination;
the corrected Go fixture repeats that matrix in the durable native capture.
Initial transport setup encountered unavailable key authentication and an overlong
SSH control-socket pathname; password-prompt authentication and a shorter private
socket resolved those setup issues without bypassing host-key verification.

The Linux run remains bound to `ed97fdc`, **not** a new full Linux rerun at `907cddd`.
The latter changes only Darwin experimental source/tests and two evidence drivers;
the new verifier asserts that exact change set. Linux fuzz execution counts are
151,958 (projection), 237,480 (portable name), 26,832 (Windows root syntax) and
16,136 (worker frame). Native corrected capture: 13:11:39–13:12:00 UTC, 21.065 s.
Its 22,467,055-byte fixture archive has SHA-256
`6ff138794d0bcb328d5fbd41ca97907f7799b3ea3e71fee08bd3cd1dbeb17516`.

Only fresh, owner-UID, mode-0700 `/private/tmp/makersvault-mp1b3.*` test directories
were used on the Mac. Four exact owned directories were inspected and removed,
their absence checked, and the SSH master closed. Local archives/logs remain for
recovery and audit. No real slicer profile, OpenClaw configuration/data, user model,
service or handler was read or changed; no app/toolchain was installed. The owner's
separate ROADMAP edit and untracked desktop architecture document remain untouched.

## Recheck and next checkpoint

The committed [index](mac-reader-verification.json) and
[read-only verifier](mac-reader-verify.cjs) join the current source to all ten
captures, recompute **21 hashes** (20 logs plus the corrected fixture archive),
check counts/failures/omissions, reproduce the explicit safety-gap interpretation
and check recorded cleanup plus the absent SSH socket. This recheck makes no Mac
connection and is not a repeat native test run. The first verifier draft incorrectly
expected a newline in the cleanup marker; its exact-string assertion was corrected
to the retained bytes, without changing the capture or its hash.

From the repository root, with private evidence retained:

```sh
node makervault/docs/evidence/gate-13/mac-reader-verify.cjs
python3 makervault/scripts/verify-release-contract.py
```

**Next: review an OS-enforced macOS file-opening boundary before activating a default
reader.** Establish pre-open regular-file and mount/recall constraints, stable native
API/distribution requirements and counterexamples that must fail closed. If the
available design cannot meet the accepted contract, return to the owner for an
explicit bounded contract/support decision; do not silently reduce protection or
drop macOS support. Existing Mac file-open support must remain separate from this
new preset-import feature. Keep the experiment disabled meanwhile.

Known-root/manifest/explicit selection/version discovery, matched consented main
integration, Windows native checks, remaining lifecycle qualification and MP-1c's
coupled API/migration/portable/raw recovery remain pending. Real Bambu/Orca/Prusa
profiles, owner Windows v2.8.0.6 and YubiKey behavior are not qualified here. CNC/CAM
and Gate 12 desktop deferrals remain; no new full app gate, image scan, waiver
transfer, release acceptance, push or publication is implied.
