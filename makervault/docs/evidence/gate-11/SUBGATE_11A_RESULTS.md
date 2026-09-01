# Gate 11A — persistent administrator identity results

**Date:** 2026-09-01  
**Status:** Accepted

**Accepted:** 2026-09-01
**Scope:** Additive identity schema, password hashing policy, one-time
environment-to-database bootstrap, compatibility login, and portable-vault
identity exclusion only

## Outcome

Gate 11A replaces direct environment-password authentication with one persistent,
database-backed administrator without opening account creation, roles, permissions,
or the later session architecture. The existing validated environment administrator
is converted exactly once when the identity table is empty. After that transaction,
changing `AUTH_USERNAME` or `AUTH_PASSWORD` does not alter the persistent identity
and does not create a parallel login or recovery path.

Implementation commit:

- `0095f6e` — schema 13, persistent administrator bootstrap/authentication,
  Argon2id policy and benchmark, compatibility and portability regressions

## Regression-first evidence

The focused Gate 11A tests were first collected against the pre-implementation
tree. Collection failed as intended with:

```text
ModuleNotFoundError: No module named 'identity_service'
```

After implementation, the focused identity, login-security, migration, export,
and import set passed:

```text
58 passed in 47.79s
```

The complete API suite then passed:

```text
247 passed in 82.20s (0:01:22)
```

## Schema and transition truth

- Additive migration 13 creates `useraccount` with a stable ID, unique normalized
  username, display name, self-describing password hash, enabled state, password
  policy version, password-change marker, and creation/update/last-login times.
- Usernames are stripped, Unicode-normalized with NFKC, and case-folded for
  uniqueness and lookup. The user-visible spelling remains separate.
- The migration creates only an empty identity structure. Startup performs the
  one-time bootstrap transaction after migrations have completed.
- A normal Gate 11A password must contain 15–4096 characters. Unicode and spaces
  are accepted, composition rules are not imposed, and a bounded local list rejects
  obvious compromised/common choices.
- A valid legacy Gate 1 administrator password of 12–14 characters is preserved
  during conversion so the existing owner is not locked out. Its account is marked
  `password_change_required`; Gate 11A does not yet add account-management UI.
- Unknown, disabled, malformed, and wrong-password authentication fails closed.
  Unknown-user verification performs a dummy hash check to reduce user-existence
  timing differences.
- A successful login transparently rehashes an older encoded Argon2 parameter set.
  The current JWT and browser-storage behavior remains unchanged and is explicitly
  deferred to 11B.

## Password-hash policy and benchmark

The runtime dependency is pinned to `argon2-cffi==25.1.0`. The accepted local
policy is Argon2id with 64 MiB memory, time cost 3, parallelism 1, 32-byte hash,
and 16-byte salt. The API admits no more than two concurrent password-hash
operations so login pressure cannot multiply memory use without a bound.

The source-owned disposable benchmark ran in the API test image:

```json
{"argon2id":{"memory_kib":65536,"parallelism":1,"time_cost":3},"hash_seconds":0.1335,"max_operation_seconds":5.0,"max_rss_bytes":201326592,"peak_rss_bytes":122519552,"verified":true,"verify_seconds":0.1567}
```

Both operations remain well below the five-second ceiling and the measured process
peak remains below the 192 MiB benchmark ceiling. This is a local acceptance bound,
not a performance promise for every host; future hardware evidence may deliberately
revise the encoded policy and successful-login rehash path.

## Backup and portability boundary

- A raw stopped format-1 backup includes the schema-13 SQLite database and therefore
  the persistent password hash. It remains secret-bearing recovery material.
- `.mvault` v1 accepts a stopped schema-12 or schema-13 source but never exports
  `useraccount`, password hashes, credentials, sessions, or audit data.
- The clean importer intentionally reconstructs the frozen schema-12 content
  contract. First API startup then applies migration 13 and bootstraps a new local
  administrator from that installation's validated environment.
- Identity-aware raw-backup auditing and recovery ceremony remain 11D work. Gate
  11A does not claim that later recovery evidence early.

## Repository verification

The clean full-repository gate passed on 2026-09-01:

```text
make verify: passed
API: 247 passed in 82.20s (0:01:22)
Web: test-target verification image built successfully
Slicer bridge: go test ./... passed; production binary built
Compose/security: canonical, deployment, smoke, and benchmark manifests validated;
security policy checks passed
Container smoke: passed (direct and same-origin API, security headers,
512 MiB file policy, non-root API/web UIDs, schema 13)
Release contract: verified for v5.1.0
```

`pip check`, `git diff --check`, and the Argon2id benchmark also passed. No image
was pushed, no deployment was changed, and no tag, release, or publication was
made.

## Gate boundary

The owner accepted Gate 11A on 2026-09-01 and authorized Gate 11B. Acceptance
freezes only the persistent first-administrator and password-hash transition.
Additional users, roles, permissions, session cookies, CSRF, revocation, account
administration/recovery, audit events, MFA, API keys, OIDC, public registration,
hosted tenancy, push, release, and deployment remain unauthorized. Gate 11B may
implement the accepted session contract only.
