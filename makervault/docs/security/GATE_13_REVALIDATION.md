# Gate 13 security finding revalidation

**Date:** 2026-09-12

**Status:** 13A–13B accepted; approved 13C maintenance/archive/browser/picker corrections verified;
browser qualification and advisory dispositions open, not release clearance

**Baseline:** audit entry `236c0fd` / application `1a209aa`; current application
`ea17494`, approved runtime containment following `ac4a051` S01/S02 hardening.
Complete verification and actual-process privilege checks pass; exact-image audits
are bound to lifecycle IDs. Prior closeout review is `b371ff8` on `c42614e`. Schema 17 unchanged.

This is the current-development disposition of all sixteen findings from the
[original security review](../MakersVault_v5.1_Security_Analysis.md). The
[Gate 0–2 revalidation](GATE_0_REVALIDATION.md) remains historical evidence. Its
accepted JWT/session limitations still apply to the frozen Gate 5 candidate;
they are not current behavior in the later Gate 11 build.

The expanded full repository verification and production-HTTPS lifecycle passed
at `2c68d70`; see [13B results](../evidence/gate-13/SUBGATE_13B_RESULTS.md).
This review joins that
regression evidence to the accepted gate records and the current trust boundaries.
It is not an external penetration test, a hardware security-key test, or
authorization for unrestricted public/hosted deployment. The separate dated
[13C advisory review](../evidence/gate-13/ADVISORY_REVIEW.md) now records fresh
dependency and image scans. Subsequent approved maintenance is verified in the
[13C remediation record](../evidence/gate-13/REMEDIATION_RESULTS.md): full gate,
joined production-HTTPS lifecycle and separately identified exact audited-image
smoke pass at `84b020d`. The subsequently approved
[archive guard](../evidence/gate-13/ARCHIVE_GUARD_RESULTS.md) passes the full gate
at `ddf8cf4` (351 API / 45 web tests) and preserves original prepared bytes.
Remaining findings in the [residual review](../evidence/gate-13/REMEDIATION_RESIDUALS.md)
are not waived; the interpreter inventory still includes the mitigated read-path issue.

The [browser correction record](../evidence/gate-13/BROWSER_FIX_RESULTS.md) adds a
full-gate/HTTPS lifecycle repeat at `1255933` (351 API / 51 web tests), old-image
negative control and seven passing request-order cases. Stale grid errors are
ignored only when superseded/departed; current 401 still requires sign-in. All
three engines pass fixture HTTPS and hostname-negative checks; Firefox now
completes organization workflows. Trust changes are disposable tooling, not a
production authentication or certificate-validation relaxation. Corrected timing
still records Chromium startup/interaction budget failures. The
[exact-image rescan](../evidence/gate-13/browser-fix-audit.json)
retains 181 API / 3 web matches, with no waiver or release clearance.

The subsequently approved [folder-picker slice](../evidence/gate-13/FOLDER_PICKER_RESULTS.md)
adds explicit-confirmation, source/view ownership and three-engine Viewer/permission/
stale-401 checks; full-gate inputs match `76b526d` (351 API / 56 web tests) under
the recorded TypeScript-only mid-run source note. Production authentication and
dependency locks are unchanged. The [September 9 exact-image scan](../evidence/gate-13/folder-picker-audit.json)
again retains 181 API / 3 web matches with full reduced-record equality checked;
no new language-lock scan or waiver is implied. Baseline organization repeats pass,
while larger-folder and detail-preview performance evidence remains unqualified.

The approved [sidebar-menu slice](../evidence/gate-13/SIDEBAR_MENU_RESULTS.md) passes
the full gate at committed `82cb2cc` (351 API / 58 web tests) and current HTTPS
lifecycle. Named three-engine picker/sidebar checks preserve Viewer restrictions,
current authorization refusal and exact action ownership, with explicit WebKit
synthetic-drop limits. Application authentication, API, Compose and locks are unchanged.
The [September 10 final-image scan](../evidence/gate-13/sidebar-menu-audit.json)
retains 181 API / 3 web matches. Web records are identical; three API Python records
(CVE-2026-17084, CVE-2026-15806, CVE-2026-15310) now list `fixed` / `3.15.0rc2` in
scanner metadata. Installed Python remains 3.11.16 and all three matches remain.
The exact deltas are retained, not called an installed fix or complete inventory
equality. No advisory is waived and no language-lock rescan or vendor-disposition
change is implied. The interrupted development-image audit remains separately recorded.

The subsequent [security closeout review](../evidence/gate-13/SECURITY_CLOSEOUT.md)
repeats all language and exact-image scans on unchanged `c42614e` inputs. Runtime
Python, production npm, Python build, harness locks and Go source scans are clean
within their stated scope. **Development scans at that checkpoint reported two moderate web
packages/one advisory and six Python package/advisory matches/five CVEs.** Image
inventory remains 181 API / 3 web with full reduced-record equality verified.
Seven PSF branch exclusions are freshly reconfirmed; 68 focused tests pass, and
isolated runtime inspection narrows several native preconditions. Outbound IDNA
normalization and remaining native/SQLite/raw-recovery risks stay open. S01/S02
patches were proposed, not yet authorized or installed at that checkpoint.

The owner subsequently approved [S01/S02 hardening](../evidence/gate-13/SECURITY_HARDENING_RESULTS.md),
implemented at clean `ac4a051`. Full verification passes 422 API tests, same-source
58-test web preflight, current smoke/passkeys and joined HTTPS lifecycle. Fresh
language scans are clean again, with no skipped Python dependencies; exact image
inventory remains 181 API / 3 web matches with reduced-record equality. Strict
IDNA2008 mitigates the reviewed outbound hostname path; the interpreter itself
remains matched/unpatched. Native/raw-recovery S04 risks remain unwaived, and
security acceptance is still open. The subsequent
[S04 decision checkpoint](../evidence/gate-13/SECURITY_RESIDUAL_DECISIONS.md) accounts
for 80 native CVEs: 11 proposed exact-image precondition exclusions, 10 priority
unresolved reviews and 59 scoped residual decisions, all owner-pending. It finds
no explicit no-new-privileges/capability policy in shipped Compose; disposable
probe isolation is not production containment evidence. The bounded containment
implementation is proposed for approval, not installed. Historical private temporary
reports are unavailable this session; committed records remain and the exact-image
benign component probe was repeated. Release raw evidence must be retained durably.

The owner subsequently approved [runtime containment](../evidence/gate-13/SECURITY_CONTAINMENT_RESULTS.md),
implemented at clean `ea17494`. Both canonical Compose manifests enforce
no-new-privileges and explicit capability policy; after initialization the API has
no remaining capabilities. Web has none. Full gate and current HTTPS lifecycle
pass (422 API / 58 reexecuted web / 25 Python harness / 28 Node tests), including
actual API/Nginx master/worker state, preview persistence and trusted recovery.
Native findings are not patched or waived; all S04 decisions remain pending.
Final audits match the exact successful lifecycle images and retain 181 API / 3 web
matches with unchanged reduced records. The earlier incomplete image scan is not
used as matched proof. New raw verification/audit evidence is retained in durable
private storage, with 86 retained-hash checks passing.

The subsequent [S04 owner proposal](../evidence/gate-13/SECURITY_DISPOSITION_PROPOSAL.md)
maps every native CVE to these exact images and proposes E11 exclusions, R59
time-limited local-qualification exceptions and H10 holds. The R set explicitly
includes critical-rated CVE-2026-12087/13221. A new private, benign component probe
corrects the zipdetails exclusion rationale and narrows one SQLite symbol question
without claiming a SESSION exclusion. At that checkpoint all decisions were owner-pending; no
scanner suppression, application change, release clearance or security closure.

On September 12 the owner [approved E11/R59 under C1–C7](../evidence/gate-13/SECURITY_OWNER_ACCEPTANCE.md).
The same-turn vendor review identifies stable fixes and reopens seven exceptions,
leaving 52 active local exceptions, E11 preconditions freshly reconfirmed and H10
unaccepted (17 open residual CVEs). Approval expires by October 12 00:00
America/New_York or earlier candidate freeze/13D/C6 trigger. This describes the
old-image checkpoint. The subsequently approved
[six-package update](../evidence/gate-13/SECURITY_NATIVE_UPDATE_RESULTS.md) at `6306ccf`
passes full verification (424 API / 58 reexecuted web tests), current HTTPS
lifecycle and exact-image containment. Only the six signed package versions change.
Current scans retain 189 API / 3 web matches: 20 vendor-fixed-version claims conflict
with scanner unknown ranges; seven new CVEs are explicitly reviewed. No old E/R
approval transfers. The subsequent [vendor/byte reconciliation](../evidence/gate-13/SECURITY_RECONCILIATION_RESULTS.md)
verifies all 20 targeted and six new PCRE2 IDs as fixed in the already-installed
packages. Current Debian fixed rows and authenticated archives match the exact
runtime (931 regular files); no further upgrade is needed for that group. Raw
scanner counts are unchanged. Native87 now comprises fixed26, proposed E2,
pending new-image R52 and unresolved H7. No new waivers: prepare the exact-image
E/R decision and handle H7 separately. Security and public release stay open.

## Finding-by-finding disposition

Test filenames refer to `api/tests/` unless otherwise stated. Each resolution is
bounded to the original finding, not a claim that a subsystem has no other risks.

| ID | Current disposition | Evidence / remaining obligation |
|---|---|---|
| MV-SEC-001 — arbitrary bridge download/open | VERIFIED replacement boundary | Accepted Gates 1E/8; `test_handoff.py`, bridge `handoff_test.go`, `adapters_test.go`, `main_test.go`. Exact-file short-lived grants, paired origin, no redirects/default opener/remote executable authority. Real workstation scope remains C03 |
| MV-SEC-002 — default credentials/secret | VERIFIED fail-closed configuration and persistent bootstrap | `test_security_config.py`, `test_identity.py`, Compose secret rejection. Environment inputs cannot bypass an existing persistent account |
| MV-SEC-003 — redirect/DNS SSRF | VERIFIED transport and strict outbound hostname boundary | `test_safe_http.py` and 68 new `test_remote_host_policy.py` cases verify IDNA2008 identity, rejection before DNS, numeric peers, Host/SNI, mixed/private answers, redirects, credentials and TLS refusal. S02 reviewed outbound path mitigated at `ac4a051`; not a runtime-wide Python patch or public-provider certification |
| MV-SEC-004 — vulnerable multipart pin | Historical pin replaced; current runtime/development locks report no advisories | Fresh pip-audit checks all 35 runtime / 43 development dependencies with none skipped. S01 HTTPX2/httpcore2 update removes the later development findings. Native/interpreter image findings remain G13-04 |
| MV-SEC-005 — vulnerable Pillow pin | Historical pin replaced; current runtime-lock scan reports no advisories | Gate 1B compatibility and current image/parser tests, plus dated 13C Python lock scans. Runtime OS/interpreter/vendor findings remain separately open; G13-04 |
| MV-SEC-006 — unbounded uploads/archives | Bounded-ingest regressions pass; reviewed interpreter ZIP read paths mitigated | Approved Stored/Deflate-only guard at `ddf8cf4` rejects unsupported member methods before reads/partial imports; `test_archive_compression.py` verifies no unsupported open/decompressor calls, ZIP64 and original prepared handoff. Existing file/expansion/capacity budgets remain, without a library quota. CVE-2026-15310 remains in the interpreter inventory; G13-04 is not waived |
| MV-SEC-007 — general bearer in file URLs | VERIFIED removed in current build | `test_sessions.py::test_bearer_and_query_token_compatibility_paths_are_removed`; web `auth.test.ts`; separate scoped bridge grants and private/no-store file response tests. Frozen candidate residual unchanged |
| MV-SEC-008 — persistent browser bearer | VERIFIED replaced in current build | Protected HttpOnly host-only cookie sessions, digest-only server records, web auth/passkey tests. XSS could still act within a live page; cookies/CSP are not an XSS-immunity claim |
| MV-SEC-009 — login/session lifecycle | VERIFIED within single-process deployment | `test_login_security.py`, `test_sessions.py`, account/passkey tests: bounded throttling, expiry, session rotation/revocation. Distributed throttling is not implemented |
| MV-SEC-010 — production Vite server | VERIFIED static unprivileged serving | Current web Dockerfile, full web production build, fresh API/web non-root container smoke. S01 fixes the later Vitest development advisory; runtime-image findings remain open despite this deployment boundary |
| MV-SEC-011 — mounted symlink escape | VERIFIED descriptor/path regression boundary | `test_mount_security.py`, mounted scan and local ContentStore symlink tests. External no-copy bytes remain operator-owned |
| MV-SEC-012 — absent multi-user authorization | VERIFIED for accepted shared-vault scope | `test_authorization.py`: exhaustive routes/system services, fixed Viewer/Member/Administrator permission tests; account administration/last-Administrator tests. Private objects, ACLs and hosted tenancy are excluded, not secured by these roles |
| MV-SEC-013 — unsafe ZIP names | VERIFIED archive regression boundary | `test_archive_limits.py`, Project/history/export tests and adversarial `.mvault` verifier/import tests. Traversal/duplicate/non-regular and unowned members fail closed |
| MV-SEC-014 — browser parser exhaustion | Preview-worker controls verified; specific fflate ZIP64 advisory patched | 13C updates direct `fflate` to 0.8.3 and passes five isolated regression cases. The old dependency negative control times out on the three malformed cases. General main-thread ZIP upload isolation is not implemented by that patch; current corpus timing remains G13-01 and automatic STEP parsing stays off |
| MV-SEC-015 — missing browser/host headers | VERIFIED configuration/smoke boundary | `test_login_security.py`, current container response/header checks and web runtime configuration. 13C corrects HTTPS/LAN/VPN and cookie-topology guidance; TLS termination/HSTS remain operator responsibilities, not automatically installed features |
| MV-SEC-016 — source/build/release hygiene | VERIFIED local controls; current release proof outstanding | Current lock/build/Compose/release-contract checks; Gate 5 SBOM, immutable identity and normalized rebuild evidence. G13-03 must qualify any later images/binaries; no publication/attestation result is invented |

## Cross-boundary review

| Boundary | Current enforcement and evidence | Limit |
|---|---|---|
| Browser → API | Exhaustive permission inventory; only health, password login, passkey-login completion and scoped redemption are non-session routes; exact-Origin/CSRF on cookie mutations; current-strength privileged authentication | One shared installation, not object privacy; production HTTPS remains mandatory |
| Hostile file/remote server → vault | Bounded streaming, DNS/redirect transport policy, archive/image budgets, Stored/Deflate member preflight, regular no-follow mounted descriptors and persisted preview failures | CVE-2026-15310 application read paths mitigated at `ddf8cf4`, not a runtime-wide patch. Larger-folder/detail-preview browser performance remains unqualified; provider behavior remains separate evidence |
| Vault → workstation | Exact supplied file/role/adapter grants, independently confirmed origin, local constrained executable configuration | Does not establish file or machine safety; OS/app launch qualification needs real platforms |
| Live state → raw recovery | Matched archive auditing; schema-17 public credentials retained; copied sessions and pending ceremonies revoked; recovery marker audited before startup exposure. 13B proves the joined production-Compose HTTPS sequence with the same signing secret | G13-02 verified on named development images; trusted operator-controlled raw snapshots only. SQLite read-only access and Python pre-audit/GNU tar extraction are not a hostile-native-input sandbox; closeout S04. Raw archives contain secrets. Fixture public credentials are not physical-device proof |
| Vault → portable archive | Independent bounded verification, content-only export, clean schema-12 reconstruction, no credentials/session/audit/provider activation; current scale/adversarial tests. 13B also proves schema-17 startup with only a new Administrator and Optional policy | Not raw rollback, merge or live restore; use private renameable staging before empty-volume population. No-copy bytes need separate preservation/remount |
| Source → distributable build | Pinned locks/base images/actions, local verification and release identity contract | Historical vulnerability scans and Gate 5 artifacts do not qualify current advisories or later artifacts |

## Owned residuals and review checkpoints

The MakersVault maintainer owns these decisions; local delivery work supplies the
tests. Review them at 13C and explicitly disposition them at 13D. Existing accepted
restrictions continue; this audit does not silently accept a new risk.

- **G13-01–03:** 13B repairs stale authentication/schema contracts and proves the
  current lifecycle; approved 13C corrections prove request ordering, Firefox trust
  and current functional browser/mount/corpus workflows. Further performance tuning
  is owner-deferred after `c42614e`, without converting failures to passes. The
  selected-release/platform matrix remains open. No auth or production policy
  was weakened to repair a harness.
- **G13-04:** approved [S01/S02 hardening](../evidence/gate-13/SECURITY_HARDENING_RESULTS.md)
  is implemented and verified at `ac4a051`. Fresh language audits are clean;
  exact images retain all 181 API / 3 web matches. The reviewed outbound
  CVE-2026-17084 path now uses strict IDNA2008; applicable CVE-2026-15310 paths
  retain their compression guard. Neither is a runtime-wide interpreter patch.
  Seven dated PSF branch exclusions remain. S04 native/raw-recovery residuals
  require fixes or explicit scoped owner dispositions
  before candidate qualification. No scanner suppression or risk waiver was added.
- **C03:** only Chromium with a virtual authenticator is currently exercised as a
  complete passkey ceremony; physical keys, platform prompts and other browser/OS
  combinations require evidence or an explicit supported-platform limitation.
- **C08:** process-local throttling/policy serialization and indefinite audit
  retention are accepted single-process constraints, not scalable/multi-tenant
  assurances. Retention changes require their own decision and recovery tests.
- **C01/C02/C06:** no API-key/OIDC/hosted tenancy/object-store authority is introduced;
  Gate 12 stays deferred to desktop with every business/privacy/non-lock-in test.
- Operators still own stable HTTPS origins, reverse-proxy configuration, raw archive
  protection, external source backups, and stopped-instance recovery access. No
  online/email recovery or undocumented environment-password bypass is assumed.

See [strategy traceability](../evidence/gate-13/TRACEABILITY.md) for reasons,
dependencies and review ownership of every carry-forward. Gate 13 remains open.
