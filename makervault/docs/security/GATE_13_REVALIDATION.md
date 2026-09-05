# Gate 13 security finding revalidation

**Date:** 2026-09-05

**Status:** 13A evidence review; source/regression audit, not release clearance

**Baseline:** `236c0fd` / implementation `1a209aa`, schema 17

This is the current-development disposition of all sixteen findings from the
[original security review](../MakersVault_v5.1_Security_Analysis.md). The
[Gate 0–2 revalidation](GATE_0_REVALIDATION.md) remains historical evidence. Its
accepted JWT/session limitations still apply to the frozen Gate 5 candidate;
they are not current behavior in the later Gate 11 build.

The full repository verification passed on this baseline. This review joins that
regression evidence to the accepted gate records and the current trust boundaries.
It is not an external penetration test, a new dependency-advisory scan, a hardware
security-key test, or authorization for unrestricted public/hosted deployment.

## Finding-by-finding disposition

Test filenames refer to `api/tests/` unless otherwise stated. Each resolution is
bounded to the original finding, not a claim that a subsystem has no other risks.

| ID | Current disposition | Evidence / remaining obligation |
|---|---|---|
| MV-SEC-001 — arbitrary bridge download/open | VERIFIED replacement boundary | Accepted Gates 1E/8; `test_handoff.py`, bridge `handoff_test.go`, `adapters_test.go`, `main_test.go`. Exact-file short-lived grants, paired origin, no redirects/default opener/remote executable authority. Real workstation scope remains C03 |
| MV-SEC-002 — default credentials/secret | VERIFIED fail-closed configuration and persistent bootstrap | `test_security_config.py`, `test_identity.py`, Compose secret rejection. Environment inputs cannot bypass an existing persistent account |
| MV-SEC-003 — redirect/DNS SSRF | VERIFIED transport regression boundary | `test_safe_http.py`: special/mixed DNS targets, connected numeric peer, each redirect, downgrade refusal, credential stripping; Gate 1D evidence. No fresh public-network import-provider certification claimed |
| MV-SEC-004 — vulnerable multipart pin | Historical pin replaced; current advisory clearance outstanding | Gate 1B dependency/compatibility evidence, locked dependency checks, current upload/archive/resource tests. G13-04 requires fresh Python dependency scans before release qualification |
| MV-SEC-005 — vulnerable Pillow pin | Historical pin replaced; current advisory clearance outstanding | Gate 1B evidence and locked image/parser regression tests. Fresh advisory results are not inferred from passing behavior tests; G13-04 |
| MV-SEC-006 — unbounded uploads/archives | VERIFIED bounded-ingest regression boundary | `test_resource_limits.py`, `test_archive_limits.py`, `test_mount_scan.py`. Per-file/expansion/capacity budgets do not impose an ordinary library or multi-file batch quota |
| MV-SEC-007 — general bearer in file URLs | VERIFIED removed in current build | `test_sessions.py::test_bearer_and_query_token_compatibility_paths_are_removed`; web `auth.test.ts`; separate scoped bridge grants and private/no-store file response tests. Frozen candidate residual unchanged |
| MV-SEC-008 — persistent browser bearer | VERIFIED replaced in current build | Protected HttpOnly host-only cookie sessions, digest-only server records, web auth/passkey tests. XSS could still act within a live page; cookies/CSP are not an XSS-immunity claim |
| MV-SEC-009 — login/session lifecycle | VERIFIED within single-process deployment | `test_login_security.py`, `test_sessions.py`, account/passkey tests: bounded throttling, expiry, session rotation/revocation. Distributed throttling is not implemented |
| MV-SEC-010 — production Vite server | VERIFIED static unprivileged serving | Current web Dockerfile, full web production build, fresh API/web non-root container smoke. Development toolchain scans are still required |
| MV-SEC-011 — mounted symlink escape | VERIFIED descriptor/path regression boundary | `test_mount_security.py`, mounted scan and local ContentStore symlink tests. External no-copy bytes remain operator-owned |
| MV-SEC-012 — absent multi-user authorization | VERIFIED for accepted shared-vault scope | `test_authorization.py`: exhaustive routes/system services, fixed Viewer/Member/Administrator permission tests; account administration/last-Administrator tests. Private objects, ACLs and hosted tenancy are excluded, not secured by these roles |
| MV-SEC-013 — unsafe ZIP names | VERIFIED archive regression boundary | `test_archive_limits.py`, Project/history/export tests and adversarial `.mvault` verifier/import tests. Traversal/duplicate/non-regular and unowned members fail closed |
| MV-SEC-014 — browser parser exhaustion | VERIFIED policy/source boundary; current timing proof outstanding | Accepted Gate 2/5 worker/corpus evidence and current preview/resource regressions. G13-01 must rerun the browser corpus after replacing obsolete harness authentication; automatic STEP parsing stays off |
| MV-SEC-015 — missing browser/host headers | VERIFIED configuration/smoke boundary | `test_login_security.py`, current container response/header checks and web runtime configuration. TLS termination/HSTS are operator responsibilities; current deployment documentation review remains 13C |
| MV-SEC-016 — source/build/release hygiene | VERIFIED local controls; current release proof outstanding | Current lock/build/Compose/release-contract checks; Gate 5 SBOM, immutable identity and normalized rebuild evidence. G13-03 must qualify any later images/binaries; no publication/attestation result is invented |

## Cross-boundary review

| Boundary | Current enforcement and evidence | Limit |
|---|---|---|
| Browser → API | Exhaustive permission inventory; only health, password login, passkey-login completion and scoped redemption are non-session routes; exact-Origin/CSRF on cookie mutations; current-strength privileged authentication | One shared installation, not object privacy; production HTTPS remains mandatory |
| Hostile file/remote server → vault | Bounded streaming, DNS/redirect transport policy, archive/image budgets, regular no-follow mounted descriptors and persisted preview failures | Fresh whole-browser load results and provider behavior remain separate evidence |
| Vault → workstation | Exact supplied file/role/adapter grants, independently confirmed origin, local constrained executable configuration | Does not establish file or machine safety; OS/app launch qualification needs real platforms |
| Live state → raw recovery | Matched archive auditing; schema-17 public credentials retained; copied sessions and pending ceremonies revoked; recovery marker audited before startup exposure | Full current operator Compose lifecycle is G13-02; raw archives contain secrets and require operator protection |
| Vault → portable archive | Independent bounded verification, content-only export, clean schema-12 reconstruction, no credentials/session/audit/provider activation; current scale round trip and adversarial tests | Not raw rollback, merge, live restore or schema-17 login proof; no-copy bytes need separate preservation/remount |
| Source → distributable build | Pinned locks/base images/actions, local verification and release identity contract | Historical vulnerability scans and Gate 5 artifacts do not qualify current advisories or later artifacts |

## Owned residuals and review checkpoints

The MakersVault maintainer owns these decisions; local delivery work supplies the
tests. Review them at 13C and explicitly disposition them at 13D. Existing accepted
restrictions continue; this audit does not silently accept a new risk.

- **G13-01–03:** stale end-to-end harnesses and missing current lifecycle/release
  proof. Repair and rerun in 13B/13C, not a reason to weaken authentication.
- **G13-04:** fresh Python/web/Go/container advisory review is outstanding. Historical
  zero-finding scans are date-bound. New findings require owned remediation or an
  explicit supported-scope/risk decision before release.
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
