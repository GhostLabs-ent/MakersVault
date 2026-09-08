# Gate 13 security finding revalidation

**Date:** 2026-09-08

**Status:** 13A–13B accepted; approved 13C maintenance/archive/browser corrections verified;
browser qualification and advisory dispositions open, not release clearance

**Baseline:** audit entry `236c0fd` / application `1a209aa`; current verification
`1255933` after approved browser corrections, schema 17 unchanged

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

## Finding-by-finding disposition

Test filenames refer to `api/tests/` unless otherwise stated. Each resolution is
bounded to the original finding, not a claim that a subsystem has no other risks.

| ID | Current disposition | Evidence / remaining obligation |
|---|---|---|
| MV-SEC-001 — arbitrary bridge download/open | VERIFIED replacement boundary | Accepted Gates 1E/8; `test_handoff.py`, bridge `handoff_test.go`, `adapters_test.go`, `main_test.go`. Exact-file short-lived grants, paired origin, no redirects/default opener/remote executable authority. Real workstation scope remains C03 |
| MV-SEC-002 — default credentials/secret | VERIFIED fail-closed configuration and persistent bootstrap | `test_security_config.py`, `test_identity.py`, Compose secret rejection. Environment inputs cannot bypass an existing persistent account |
| MV-SEC-003 — redirect/DNS SSRF | VERIFIED transport regression boundary | `test_safe_http.py`: special/mixed DNS targets, connected numeric peer, each redirect, downgrade refusal, credential stripping; Gate 1D evidence. No fresh public-network import-provider certification claimed |
| MV-SEC-004 — vulnerable multipart pin | Historical pin replaced; current application-lock scan reports no advisories | 13C pip-audit checks all 35 runtime / 43 development locked dependencies with none skipped. This does not clear inherited runtime-image packages; G13-04 remains open |
| MV-SEC-005 — vulnerable Pillow pin | Historical pin replaced; current application-lock scan reports no advisories | Gate 1B compatibility and current image/parser tests, plus dated 13C Python lock scans. Runtime OS/interpreter/vendor findings remain separately open; G13-04 |
| MV-SEC-006 — unbounded uploads/archives | Bounded-ingest regressions pass; reviewed interpreter ZIP read paths mitigated | Approved Stored/Deflate-only guard at `ddf8cf4` rejects unsupported member methods before reads/partial imports; `test_archive_compression.py` verifies no unsupported open/decompressor calls, ZIP64 and original prepared handoff. Existing file/expansion/capacity budgets remain, without a library quota. CVE-2026-15310 remains in the interpreter inventory; G13-04 is not waived |
| MV-SEC-007 — general bearer in file URLs | VERIFIED removed in current build | `test_sessions.py::test_bearer_and_query_token_compatibility_paths_are_removed`; web `auth.test.ts`; separate scoped bridge grants and private/no-store file response tests. Frozen candidate residual unchanged |
| MV-SEC-008 — persistent browser bearer | VERIFIED replaced in current build | Protected HttpOnly host-only cookie sessions, digest-only server records, web auth/passkey tests. XSS could still act within a live page; cookies/CSP are not an XSS-immunity claim |
| MV-SEC-009 — login/session lifecycle | VERIFIED within single-process deployment | `test_login_security.py`, `test_sessions.py`, account/passkey tests: bounded throttling, expiry, session rotation/revocation. Distributed throttling is not implemented |
| MV-SEC-010 — production Vite server | VERIFIED static unprivileged serving | Current web Dockerfile, full web production build, fresh API/web non-root container smoke. 13C build-tool and runtime-image findings remain open despite this deployment boundary |
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
| Hostile file/remote server → vault | Bounded streaming, DNS/redirect transport policy, archive/image budgets, Stored/Deflate member preflight, regular no-follow mounted descriptors and persisted preview failures | CVE-2026-15310 application read paths mitigated at `ddf8cf4`, not a runtime-wide patch. Current browser load has a budget failure; provider behavior remains separate evidence |
| Vault → workstation | Exact supplied file/role/adapter grants, independently confirmed origin, local constrained executable configuration | Does not establish file or machine safety; OS/app launch qualification needs real platforms |
| Live state → raw recovery | Matched archive auditing; schema-17 public credentials retained; copied sessions and pending ceremonies revoked; recovery marker audited before startup exposure. 13B proves the joined production-Compose HTTPS sequence with the same signing secret | G13-02 verified on named development images; raw archives contain secrets and require operator protection. Fixture public credentials are not physical-device proof |
| Vault → portable archive | Independent bounded verification, content-only export, clean schema-12 reconstruction, no credentials/session/audit/provider activation; current scale/adversarial tests. 13B also proves schema-17 startup with only a new Administrator and Optional policy | Not raw rollback, merge or live restore; use private renameable staging before empty-volume population. No-copy bytes need separate preservation/remount |
| Source → distributable build | Pinned locks/base images/actions, local verification and release identity contract | Historical vulnerability scans and Gate 5 artifacts do not qualify current advisories or later artifacts |

## Owned residuals and review checkpoints

The MakersVault maintainer owns these decisions; local delivery work supplies the
tests. Review them at 13C and explicitly disposition them at 13D. Existing accepted
restrictions continue; this audit does not silently accept a new risk.

- **G13-01–03:** 13B repairs stale authentication/schema contracts and proves the
  current lifecycle; approved 13C corrections prove request ordering, Firefox trust
  and current functional browser/mount/corpus workflows. Chromium performance and
  the selected-release/platform matrix remain open. No auth or production policy
  was weakened to repair a harness.
- **G13-04:** approved targeted web/installer/runtime refresh passes the complete
  gate. Refreshed language locks report no advisories; image scans retain 181 API /
  3 web package matches. Explicit PSF branch ranges exclude seven interpreter
  matches, not all CPE findings. CVE-2026-15310's applicable archive paths now have
  the approved compression guard and bounded regression evidence at `ddf8cf4`. Other
  OS/interpreter/no-fix findings require further review and explicit dispositions
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
