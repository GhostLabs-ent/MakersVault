# Gate 13C — current user workflows and release readiness

**Opened:** 2026-09-06, following owner acceptance of 13B at `2f61b37`.

**Status:** IN PROGRESS — PICKER AND APPROVED SIDEBAR-MENU SLICE IMPLEMENTED;
current Chromium baselines retain one startup failure; larger-folder browser timing
passes but folders API p95 fails. Overall performance remains unqualified.
[Implementation, full-gate source note and current evidence](FOLDER_PICKER_RESULTS.md)
follow the owner-approved [profiling proposal](CHROMIUM_PROFILE_RESULTS.md).
The [residual diagnosis](RESIDUAL_DIAGNOSIS.md) led to the approved
[on-demand sidebar-menu implementation](SIDEBAR_MENU_RESULTS.md) at `82cb2cc`.
Its full gate passes 351 API / 58 web tests and current HTTPS lifecycle; exact
detail native wait and folder-API latency remain separate investigative tracks.
See also [browser correction evidence](BROWSER_FIX_RESULTS.md). No release scope
or replacement candidate selected. This is not a request to accept or close 13C.

**Entry verification:** `2c68d70`; accepted 13B evidence `2f61b37`. Application
behavior remains the local schema-17 implementation, not the frozen Gate 5 release.

**Latest bounded follow-up (2026-09-10):** [folder-list projection and performance
disposition](BOUNDED_PERFORMANCE_RESULTS.md), application `c42614e`, 354 API tests
passing. The owner authorized one final pass and accepts carrying remaining
performance issues for now. Further tuning is deferred, not a benchmark pass or
automatic 13C closeout. Other security/platform/release obligations remain unchanged.

**Security closeout review (2026-09-10):** [decision package](SECURITY_CLOSEOUT.md)
and [fresh all-phase audit](security-closeout-audit.json) on unchanged `c42614e`
images. Production language scopes are clean; development tooling has new findings.
All 181 API / 3 web image matches remain recorded; seven Python branch exclusions
are revalidated, and 68 focused security tests pass. S01 tooling refresh and S02
hostname hardening are proposed for approval. Native-image/raw-recovery dispositions
remain S04. Review complete does not mean security accepted or 13C closed.

**Approved S01/S02 implementation:** [hardening results](SECURITY_HARDENING_RESULTS.md)
at clean `ac4a051` pass the complete gate: 422 API tests, the same-source 58-test
web preflight, current smoke/passkeys and joined HTTPS lifecycle. Fresh language
audits are clean; exact images retain all 181 API / 3 web matches with reduced-record
equality. Strict outbound IDNA2008 mitigates the reviewed application path, not the
whole interpreter. S04 residual-risk acceptance and platform/release proof remain open.

**S04 follow-up:** [per-CVE decision checkpoint](SECURITY_RESIDUAL_DECISIONS.md)
records 11 proposed exact-image precondition exclusions and 69 unwaived residual
CVEs (10 prioritized for uncertainty/raw-input/native review). Fresh exact-image
component observations match prior evidence. Proposed runtime containment requires
owner approval; the probe's isolation flags are not shipped Compose defaults.
No new full-gate/advisory scan or risk acceptance is claimed. Historical private
temporary logs are unavailable this session; durable candidate raw evidence is required.

**Approved containment implementation:** [results](SECURITY_CONTAINMENT_RESULTS.md)
at clean `ea17494` pass the full gate, 422 API / 58 reexecuted web tests, 25 Python /
28 Node harness tests and current HTTPS lifecycle. Actual application processes
have five empty capability sets and no-new-privileges; default/custom-ID ownership,
read-only imports, restart and generated-preview persistence remain supported.
Failed attempts are retained and new raw evidence is durable/private. The final
audit matches the exact lifecycle images, retaining 181 API / 3 web findings with
unchanged reduced records. S04 exceptions and Gate 13C remain unaccepted.

**S04 owner package:** the [current proposal](SECURITY_DISPOSITION_PROPOSAL.md)
recommends E11 exact-image exclusions, R59 time-limited local-qualification
exceptions (including two critical Perl CVEs), and H10 holds. All 80 decisions are
still pending, with explicit C1–C7 conditions, owner and expiry proposed. Even E/R
approval would leave H10/G13-04 and Gate 13C open. The new benign exact-image CLI /
SQLite-symbol probe is durable evidence, not another full-gate or advisory scan.

**September 12 owner decision:** [E11/R59 approved under C1–C7](SECURITY_OWNER_ACCEPTANCE.md),
with H10 unaccepted. Fresh vendor fixes reopen seven R exceptions, including both
critical Perl entries; E11 preconditions are reconfirmed and 52 local exceptions
remain active. Seventeen residual CVEs remain open. The October 12 00:00
America/New_York deadline is subject to earlier freeze/13D/C6 triggers. The
six-package proposal at that checkpoint was subsequently approved for implementation.

**Current native update:** [verified at clean `6306ccf`](SECURITY_NATIVE_UPDATE_RESULTS.md)
with exactly six signed package-version changes, 424 API / 58 reexecuted web tests,
full HTTPS lifecycle and exact-image containment. Fresh scans retain 189 API / 3 web
matches: 20 vendor-fixed-version records conflict with scanner unknown ranges,
and seven newly seen CVEs are separately triaged. No old-image E/R acceptance
transfers. The wrapper-interrupted attempt is preserved;
the subsequent full run passed. Security/Gate 13C acceptance remains open.

**Current reconciliation:** [vendor and exact-byte evidence](SECURITY_RECONCILIATION_RESULTS.md)
verifies all 20 targeted plus six newly seen PCRE2 CVEs as fixed in the existing
pins. Six authenticated archives match 931 runtime regular files; no further
package update is needed for this group. The prior 189 API / 3 web raw matches
remain, including 28 for the verified fixes. Native87 now comprises fixed26,
proposed E2, pending new-image R52 and unresolved H7; no new acceptance. Prepare the
image-specific E/R decision and handle H7 separately. No rescan, application change,
full-suite repeat, waiver transfer or security/release clearance in this review.

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
That proposed diagnostic work is now complete; see the follow-up below. It does
not establish sidebar rendering as an explanation for all elapsed time.
Physical/native-platform evidence or explicit support limits, remaining advisory
dispositions, release scope/revision and matched distribution qualification remain
owner checkpoints. Gate 13C is not accepted or ready for closeout. No push, tag,
publication, deployment, frozen-pin change or Gate 12 expansion is authorized.

### September 10 residual diagnosis and proposed next slice

Six fresh runs on the unchanged application/images separate real sidebar DOM cost
(8,800 closed-menu descendants) from 405–475 ms test-driver label queries. The
captured detail pause is 1,039.5 ms elapsed but about 1.0 ms renderer-thread CPU,
before the model request; observed context creation is under 8 ms. The exact native
wait remains unresolved, not attributed to model parsing, GPU or Docker. The final
unprofiled stress still fails search, interaction and the separate folders API p95.

[Evidence and proposals](RESIDUAL_DIAGNOSIS.md) retain all attempts and limits.
Opt-in diagnostic harness `3101b68` passes 19 Python / 28 Node tests and static
release checks. No application change, new full-gate result, image scan or waiver
is claimed. Next checkpoint: approve or revise lazy sidebar-menu contents plus the
scoped exact-name textbox locator, then reverify unchanged-budget baseline/stress
and keyboard/permission/action behavior. Detail native-wait and API-time profiling
remain distinct tracks; this proposal does not claim to fix them. Gate 13C stays open.

### Approved on-demand sidebar menus

The owner approved the bounded menu/locator proposal; it is implemented at `82cb2cc`.
[Current results](SIDEBAR_MENU_RESULTS.md) retain full-gate verification, all failed
development attempts and the final-image workflow records. Closed contents are no
longer constructed; root expansion, paths, actions, permissions and upload limits
are unchanged. The baseline's 40-card DOM drops from 3,659 to 2,779 elements.

All 17 picker/sidebar scenarios pass in Chromium/Firefox (H) and WebKit (J), with
WebKit's native synthetic-entry failure explicitly separated from its FileList-only
DOM-event fixture. No native filesystem-drag qualification is claimed. All seven
ordering cases pass. The complete gate at committed `82cb2cc` passes 351 API /
58 web tests, security/passkeys and joined HTTPS lifecycle; later functional harness
`7b0bb6e` separately passes 19 Python / 28 Node checks and static release contract.
The menu optimization does not resolve every historical startup, preview or API
observation, accept Gate 13C, change release pins or authorize publication.
Current Chromium baseline runs C/F pass, but E fails first cards at 1,368.5 ms.
Both stress runs D/G pass browser timing and fail folders API p95 at 113.3/108.3 ms.
All five runs have zero observed interaction tasks and 16.4–74.8 ms folder search;
navigation tasks and every historical failure remain recorded. Next proposal is
separate API timing and intermittent startup/detail-wait attribution before another fix.
