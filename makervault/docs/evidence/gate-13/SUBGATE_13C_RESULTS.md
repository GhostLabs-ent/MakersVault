# Gate 13C — current user workflows and release readiness

**Opened:** 2026-09-06, following owner acceptance of 13B at `2f61b37`.

**Status:** IN PROGRESS — REMEDIATION APPROVED; no release scope or
replacement candidate selected. This is not a request to accept or close 13C.

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

### Completed at this checkpoint

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

No application code, dependency locks, runtime Dockerfiles or release pins were
changed at this checkpoint. All work stays local; no push/tag/publication/deployment.

### Still outstanding

Browser assertion refresh and current cold/warm/detail/LightBurn, organization/
Trash, supporting/prepared and mounted-import runs have **not** been completed in
13C. Historical timing is not reused. Physical-device and native-workstation
availability has been requested; no answer or platform limitation is assumed.
Release scope/revision, matched distribution qualification, final 13C acceptance
and 13D end-state review remain owner checkpoints. Gate 12 remains desktop-deferred
and the unrelated desktop draft remains untouched.
