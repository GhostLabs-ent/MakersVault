# Gate 11 — deliberate authentication evolution results

**Date:** 2026-09-04

**Status:** Complete and owner-accepted

**Entry commit:** `b5f3fd2`

**Closeout commit:** `a85048b`

**Schema:** 12 at entry; additive schema 16 at closeout

## Outcome

Gate 11 replaced one environment-password/JWT Administrator with a recoverable,
auditable shared-vault identity system. The owner accepted 11A, 11B, 11C, and each
11D slice sequentially, accepted 11D-3 on 2026-09-03, and then authorized Gate 11E.

The accepted closeout includes:

- persistent normalized accounts with Argon2id password hashes and no permanent
  environment-password bypass;
- opaque digest-only browser sessions, protected host-only cookies, strict Origin
  and CSRF enforcement, bounded expiry, and revocation;
- exactly three fixed shared-vault roles with deny-by-default classification of all
  95 HTTP routes and every internal system entry point;
- Administrator-created enrollment, forced temporary-password replacement,
  five-minute recent-password confirmation, and transactional last-Administrator
  protection;
- mandatory bounded secret-free audit with Administrator-only retrieval;
- recovery contract 5, restored-session revocation, startup recovery auditing, and
  interactive backup-first stopped-instance recovery of an existing account; and
- continued exclusion of identities, password hashes, sessions, audit, recovery,
  and authenticator material from frozen `.mvault` v1.

No content entity gained user ownership. The vault remains installation-shared;
roles control capabilities, not visibility of private objects.

## Consolidated security and recovery review

The closeout review traced login, session creation/authentication/revocation,
password changes, recent reauthentication, role checks, account administration,
last-Administrator safety, audit persistence/redaction, raw recovery, startup marker
conversion, and portable exclusion as one system.

The focused matrix passed on the accepted source:

```text
Identity/session/authorization/account/audit/recovery/.mvault matrix:
118 passed in 68.09s

Gate 11D-3 recovery matrix:
55 passed in 14.09s

Complete repository gate at 11D-3:
294 API tests; web typecheck/tests/build; bridge tests/build; Compose/security;
container smoke; release contract — all passed
```

The recovery matrix is the repeatable stopped-instance drill for this boundary. It
proves exact matched-backup verification, contract-5 corruption refusal, contracts
2–4 compatibility re-audit, copied-session revocation, pending-marker conversion,
exclusive lock and symlink refusal, exact pre-change database matching, existing-
account-only Administrator recovery, and unchanged content records/storage.

## Residual boundaries

- Production browser authentication requires HTTPS; trusted-LAN HTTP remains an
  explicitly weaker deployment posture.
- Login throttling is process-local for the supported single API process.
- Audit retention is indefinite and not user-configurable.
- Public registration, email recovery, private objects, per-object ACLs, hosted
  tenancy, MFA, API keys, OIDC/SSO, and anonymous access did not enter Gate 11.
- Local Docker verification is not an external penetration test.

## Publication state

Gate 11 was implemented, tested, documented, accepted, and committed locally only.
No commit or image was pushed; no tag, release, deployment, or publication occurred.

Gate 11E was separately authorized and its stronger-authenticator design was accepted
on 2026-09-04. Its schema-17 foundation is tracked independently in the 11E-1a
results and does not alter this accepted Gate 11 closeout.
