# Gate 13C — current user workflows and release readiness

**Opened:** 2026-09-06, following owner acceptance of 13B at `2f61b37`.

**Status:** IN PROGRESS — APPROVED FOLDER-PICKER OPTIMIZATION VERIFIED;
three baseline Chromium organization runs pass unchanged enforced budgets, while
larger-folder stress and detail-preview timing remain unqualified.
[Implementation, full-gate source note and current evidence](FOLDER_PICKER_RESULTS.md)
follow the owner-approved [profiling proposal](CHROMIUM_PROFILE_RESULTS.md).
See also [browser correction evidence](BROWSER_FIX_RESULTS.md). No release scope
or replacement candidate selected. This is not a request to accept or close 13C.

**Entry verification:** `2c68d70`; accepted 13B evidence `2f61b37`. Application
behavior remains the local schema-17 implementation, not the frozen Gate 5 release.

## Bounded execution

1. Refresh stale browser assertions to the accepted current UI, retaining explicit
   behavior/performance assertions; record source/image/browser/corpus identities.
2. Execute cold/warm/detail/LightBurn previews, 600-Artifact/104-folder organization
   and current Trash/supporting/prepared workflows, plus mounted-import reporting.
   Repeat the supported browser engines where tooling permits. Unsupported metrics
   are unavailable, never measured zero. Do not change budgets to obtain a pass.
3. Revalidate current dependencies with dated advisory sources and distinguish
   application locks, development tooling, Go and runtime operating-system images.
   Scanner failures or unavailable databases are not clean scans. Remediation that
   expands application/dependency scope comes back to the owner with evidence.
4. Review current operator commands, HTTPS/cookie/origin posture and documented
   recovery/bridge/platform boundaries against the implementation.
5. Collect physical passkey and native workstation evidence from the owner, or
   request explicit supported-platform dispositions. Linux automation does not
   certify Windows/macOS/mobile, physical keys or local app launch/signing.
6. Present remaining release scope/revision and residual-risk decisions before
   candidate assembly, matched bridge/distribution qualification or final 13D.

Use generated fixtures, unique disposable projects, immutable local development
image identities and private temporary directories. Preserve historical Gate 5
evidence and the unrelated desktop draft. No user vault or unrelated workload may
be changed. No push, tag, publication, live deployment or feature expansion.

## Entry findings

- Organization browser assertions still expect pre-Trash `Delete…` behavior.
  Update tests to current recoverable Trash, cancellation and restore semantics.
- Production Secure cookies require HTTPS, including on LAN/VPN. Some operator
  prose still implies HTTP/VPN alone is a supported production browser posture;
  reconcile it without changing runtime security policy.
- 13B's shared session helper and production lifecycle pass, but they do not
  establish a full browser/corpus/mounted-import pass or current dependency safety.

## Evidence and owner decisions

### Initial advisory checkpoint (`4c38fcf`, preserved history)

- Recorded 13B acceptance and opened 13C at `fa273b6`.
- Added a read-only advisory audit helper, pinned scanner/container inputs,
  private raw reports and five tests that prevent failed/incomplete scans from
  masquerading as clean results. Captured fresh web, Python, Go and image scans.
- [Advisory review](ADVISORY_REVIEW.md): three affected web packages, including
  direct production `fflate`; no findings for the two Python locks, Go source or
  the two browser-harness locks. Runtime image scans add 283 API / 158 web package
  matches, including critical/high ratings and reported available fixes. Those
  are package matches requiring triage, not demonstrated app exploits or 441
  independent flaws. Nothing has been waived.
- Preserved [scan identities, counts and raw-report hashes](advisory-audit.json)
  and [all reduced image-match records](advisory-image-matches.json). The accepted
  13B entry image IDs and unchanged application locks identify what was scanned;
  the new helper/operator documents do not change application behavior.
- Corrected README, secure-deployment and reverse-proxy guidance: production HTTPS
  includes LAN/VPN; setup does not install TLS; unrelated cross-site UI/API splits
  do not work with current Lax cookies. Development mode and published fallback
  credentials are not production recovery workarounds. This is documentation/source
  review, not a new browser qualification of every proxy topology.
- `make verify-harness verify-release`: **12 Python harness tests, 5 Node session
  helper tests, three browser-script syntax checks and static release contract
  passed**. The 313 API / 32 web and joined lifecycle pass remain the named 13B
  evidence; the complete application gate was not rerun for this documentation/
  audit-tooling checkpoint.

### Approved remediation

The owner approved the following scope after checkpoint `4c38fcf` on 2026-09-06
(America/New_York). Execution is recorded in [remediation results](REMEDIATION_RESULTS.md).

1. Patch direct `fflate` to 0.8.3 and compatibly refresh the two affected build
   dependencies (`browserslist` 4.28.7, `postcss-selector-parser` 6.1.3); add bounded
   malformed-ZIP64 regression coverage. No broad `audit fix --force` or feature
   rewrite. General ZIP upload-worker isolation remains a separate scope decision.
2. Refresh supported, digest-pinned runtime bases/packages and review inherited
   Python installer/vendor packages. Preserve the Python release line unless a
   separate compatibility decision is needed; do not blindly follow CPE matches
   into a major upgrade. Re-scan replacements and explicitly disposition any
   remaining vendor/no-fix/unknown matches with evidence and owner risk decisions.
3. Run targeted regressions and the complete repository gate, name new local
   image identities, then resume the already-authorized current browser/workflow
   matrix without relaxing budgets, HTTPS or cookie security.

At the initial `4c38fcf` checkpoint, application code, dependency locks, runtime
Dockerfiles and release pins were unchanged. The subsequently approved maintenance
is now implemented locally at `39307f5` / `84b020d`; release pins remain unchanged.

### Maintenance verification and new residual checkpoint

- [Remediation results](REMEDIATION_RESULTS.md): complete `make verify` passes at
  clean `84b020d`: 313 API / 37 web tests, 12 Python harness / 5 Node client tests,
  Go/build/Compose/security checks, Chromium virtual-passkey smoke and joined
  production-HTTPS lifecycle. The exact audited images also pass HTTPS/security/
  persistence smoke; the record distinguishes those IDs from lifecycle-build IDs.
- Targeted web/installer locks and runtime bases are refreshed. Full/production
  web, Python runtime/development/installer, Go and browser-harness scans report
  no advisories for their stated scope/date. Image scans still report **181 API /
  3 web package matches**; all observations and hashes are preserved separately
  from the entry scan. Nothing is suppressed or waived.
- [Residual review](REMEDIATION_RESIDUALS.md): seven interpreter matches are
  excluded by explicit PSF branch ranges, not by a blanket CPE exemption. Remaining
  OS/interpreter findings stay open. Source inspection confirms an affected
  BZIP2/LZMA ZIP read path for CVE-2026-15310; existing outer byte/ratio limits do
  not bound its internal allocation. No production memory-exhaustion test is claimed.
- At that checkpoint, requested approval for the residual review's Stored/Deflate-only parsing guard
  and bounded regressions before changing archive compatibility. Conforming 3MF,
  ZIP64, original bytes and no-manual-thumbnail behavior must remain intact. Then
  resume the current browser/workflow matrix. No Python release-line migration,
  broader upload-worker redesign or residual-risk acceptance is implied.

### Approved archive guard and resumed workflows

The owner approved the bounded compatibility proposal after `78f6aa3`. Implementation
and the complete gate pass at `ddf8cf4`: **351 API / 45 web tests**, current passkeys,
HTTPS lifecycle/recovery and exact image identities. The images-only rescan retains
181 API / 3 web matches; remaining findings are unwaived. See
[guard results](ARCHIVE_GUARD_RESULTS.md), [verification](archive-guard-verification.json)
and [scan identities/hashes](archive-guard-audit.json).

The committed browser harness at `4fbdcdf` uses disposable production-HTTPS stacks,
container-local certificate trust plus wrong-hostname rejection, and current
Trash/restore workflows. Initial Chromium testing completed the functional
assertions but failed first cards at **1620.3 ms against <1000 ms**. The other
engine/corpus/mount evidence and next scoped decisions are in the
[browser record](BROWSER_WORKFLOW_RESULTS.md): WebKit functional, Chromium
preview/cache and mounted-import probes completed; Firefox remains stopped at TLS
preflight. A diagnostic Chromium repeat also timed out finding a restored item in
the searched library, so that visibility/synchronization issue remains open.
No budget, authentication policy, release pin or user library was changed.

All work stays local; no push/tag/publication/deployment.

### Browser correction and profiling history

The owner subsequently approved the diagnosed grid, fixture trust and timing
corrections. Full verification at clean `1255933` passes **351 API / 51 web tests**,
19 Python / 10 Node harness tests and the joined HTTPS lifecycle. The old build
fails the new race negative control; the fixed build passes all seven cases.
Firefox now passes TLS and organization workflows. See the
[new record](BROWSER_FIX_RESULTS.md) and its immutable image identities.
The same images' [fresh rescan](browser-fix-audit.json) retains 181 API / 3 web
matches; all reduced records equal the prior inventory and remain unwaived.

The current browser matrix is still **not performance-qualified**: Chromium A
records first cards at 584.4 ms but a 56 ms load-more long task; repeat B records
1433.2 ms first cards, a 713 ms navigation long task and a 55 ms folder-navigation
long task. The <1000 ms / ≤50 ms limits are unchanged. Request visibility and
Firefox trust corrections are verified, not still awaiting repair. The subsequent
owner-authorized [profiling slice](CHROMIUM_PROFILE_RESULTS.md) completes three
instrumented runs and two unprofiled controls on those unchanged images. It confirms
4,200 closed folder options at 40 cards, real DOM construction and costly driver
queries; large elapsed/CPU gaps remain only partially explained. Controls pass at
495.2/528.0 ms without replacing historical failures. The proposed on-demand folder
picker and separately reviewed benchmark improvements awaited approval at that
checkpoint. No application optimization, budget change or general root-cause claim
followed from those traces alone.
Focused checks pass 19 Python / 14 Node tests and static release verification at
the profiling harness checkpoint; its named full application pass remains `1255933`.
Successful three-engine functional and
preview/cache/mount probes are bounded evidence, not a blanket performance pass.
Historical timing is not reused. Physical-device and native-workstation
availability has been requested; no answer or platform limitation is assumed.
Release scope/revision, matched distribution qualification, final 13C acceptance
and 13D end-state review remain owner checkpoints. Gate 12 remains desktop-deferred
and the unrelated desktop draft remains untouched.

### Approved picker implementation and remaining checkpoint

The owner approved the bounded picker/benchmark slice on 2026-09-09. It is
implemented at `76b526d`; [results](FOLDER_PICKER_RESULTS.md) name all exact images,
attempts and failed development checks. Current paths remain visible; one searchable
dialog mounts on demand and moves only after explicit confirmation. Keyboard/focus,
conflict/deletion/permission, stale-view/error and Viewer checks pass in Chromium,
Firefox and WebKit, alongside all seven Chromium request-order cases. At 40 loaded
cards/104 folders, closed-card folder options drop from 4,200 to zero.

The full verification's executed inputs match `76b526d`: **351 API / 56 web tests**,
current passkey/security checks and joined HTTPS upgrade/restore/rollback/portable
lifecycle pass. The [verification record](folder-picker-verification.json) explains
that the unchanged API phase began before the two-line TypeScript correction; it
does not claim the invocation began at the final revision. Later harness-only
`53142f9` passes 19 Python / 21 Node tests and static release verification.

All three unprofiled 600-Artifact/104-folder Chromium repeats pass the unchanged
enforced budgets (first visible cards 546.9–865.2 ms). Firefox/WebKit organization
functional checks pass, with timing support/limits explicitly bounded. The separate
600/1,040 stress retains failed first cards (1,612.4 ms) and folder search (494.9 ms).
The mixed preview/cache functional probe completes but detail preview records a
1,074 ms long task: it is **not** a preview performance pass. Mounted-import
source-preservation checks pass. Every failure and historical observation remains.

Stress G also counted two selected cards before bulk completion. Source review
shows the failure message can precede refresh/final deselection. Harness-only
`10c7481` waits for completion and checks both exact IDs; fresh stress H verifies
only the failed ID remains selected. H still fails folder search (454.7 ms) and a
51 ms Trash task; G is not retroactively passed. Focused harness/static checks
again pass 19 Python / 21 Node tests. No application or budget changed.
An additional fresh 600/104 baseline on `10c7481` passes the strengthened exact-ID
assertions and unchanged budgets at 585.6 ms first cards. It supplements D–F;
neither stress failure nor the detail-preview pause is erased.

The [fresh exact-image audit](folder-picker-audit.json) retains 181 API / 3 web
matches; all reduced records equal the previous inventory, with nothing waived.
Next proposed bounded work is profiling the larger-folder startup/search path and
detail-preview pause before another code proposal. Sidebar eager menu/row rendering
is a source-review candidate, not a demonstrated explanation for all elapsed time.
Physical/native-platform evidence or explicit support limits, remaining advisory
dispositions, release scope/revision and matched distribution qualification remain
owner checkpoints. Gate 13C is not accepted or ready for closeout. No push, tag,
publication, deployment, frozen-pin change or Gate 12 expansion is authorized.
