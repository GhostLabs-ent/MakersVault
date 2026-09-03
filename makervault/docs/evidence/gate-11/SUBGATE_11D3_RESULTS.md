# Gate 11D-3 — stopped-instance and raw recovery results

**Date:** 2026-09-03

**Status:** Verified locally; owner acceptance pending

**Scope:** Recovery contract 5, schema-16 security-domain verification, raw-restore
session revocation and startup auditing, and interactive stopped-instance recovery
of one existing Administrator only

## Outcome

Gate 11D-3 completes the recovery portion of the approved Gate 11D contract. New
raw backups retain outer `makersvault-backup` format 1 and advance only the
schema-aware recovery contract to 5. No schema migration, content record, Artifact,
Project, Machine, managed file, or `.mvault` format changed.

Implementation commit:

- `3ed6991` — contract-5 verification, stopped-instance mutation boundary,
  restored-session revocation, startup recovery audit conversion, interactive
  existing-account recovery, deployment wrappers, regressions, and operator docs

## Contract-5 truth

The independent standard-library verifier now inventories and validates schema-16
accounts, roles, browser sessions, durable audit events, and recovery markers in
addition to the established content, revision, Trash, Project, and Machine graph.
It rejects missing required security structures; malformed identities, roles, and
account state; absent enabled Administrators; broken session ownership/digests/time;
malformed audit records or non-enumerated details; and invalid recovery markers.

New manifests exactly record the complete report. Contracts 2–4 and legacy
no-contract format-1 manifests remain supported as recorded report subsets, but
their restored contents must pass the complete current re-audit. Compatibility
therefore does not grandfather security corruption.

## Raw-restore truth

`restore.sh` still restores storage first and SQLite last, then re-snapshots both
volumes and proves exact equality with the independently verified archive. Only
after that proof, while API and web remain stopped, it:

1. opens the one exact regular `app.db` without following a symlink;
2. rejects a non-empty WAL and acquires a non-blocking exclusive file lock plus an
   exclusive SQLite transaction;
3. revokes every active restored browser session;
4. writes a bounded pending `raw_restore` marker; and
5. re-audits the changed database against the unchanged storage snapshot.

At the next API start, pending markers are converted transactionally into durable
`recovery.raw_restore` audit events before requests are accepted. The event contains
only the revoked-session count and canonical marker target; it contains no backup
path, archive digest, password, token, or recovery secret. Compatible pre-session
databases remain restorable; schema 14–15 sessions are revoked even though those
older schemas cannot store the later marker.

## Administrator-recovery truth

`scripts/recover-administrator.sh` records which services were running and creates
a new matched backup with `--leave-stopped` before prompting or mutating. The
password is read twice through `getpass`; there is no password command-line option.

The command independently verifies the archive and hashes its contained `app.db`
against the locked live file. In one transaction it updates one normalized existing
account only: reset password hash, enable, promote to Administrator, require password
replacement, revoke every session, and queue an `administrator_recovery` marker. It
never creates a bypass identity.

An Administrator-recovery-purpose backup may preserve exactly one readiness
finding: no enabled Administrator. This allows a disabled/demoted account to be
repaired. It is explicit in the contract-5 manifest and still fails normal
verification; every additional identity, session, audit, content, schema, or storage
finding rejects creation and recovery. A fully consistent ordinary backup also
satisfies forgotten-password recovery.

Any wrapper failure after shutdown leaves API and web stopped. Previously running
services restart only after the complete mutation succeeds, unless the operator
chooses `--leave-stopped`.

## Regression evidence

The focused matrix proves contract-5 round trip and corruption rejection, contract-4
compatibility re-audit, raw-restore revocation and exact content preservation,
lock/symlink refusal, exact-backup matching, missing-account refusal, the bounded
locked-out snapshot, startup event conversion/idempotence, and protected prompts.

```text
Focused recovery matrix: 55 passed in 14.09s
Complete API suite: all 294 collected tests passed
Shell syntax: backup.sh, restore.sh, recover-administrator.sh passed
Python static compilation and git diff --check: passed
```

The first complete API run exposed a historical migration-only fixture whose new
schema-16 database had not executed application bootstrap. Contract 5 correctly
reported it as not recovery-ready because it had no enabled Administrator. The
fixture now asserts that fail-closed readiness finding while continuing to prove
that every pre-v5.1 content record and byte survives migration unchanged.

## Repository verification

The complete `make verify` gate exited successfully on 2026-09-03:

```text
API: all 294 collected tests passed
Web: typecheck, 10 test files / 29 tests, and production build passed
Slicer bridge: go test ./... passed; production binary built
Compose/security: canonical, deployment, smoke, and benchmark manifests validated;
security policy checks passed
Container smoke: passed with schema 16
Release contract: verified for v5.1.0
```

The run used local disposable containers and volumes only. No image was pushed, no
deployment was changed, and no tag, release, or publication was made.

## Gate boundary

Gate 11D-3 is locally complete and awaits owner acceptance. Audit retention remains
mandatory and indefinite; MFA, API keys, OIDC/SSO, public registration, hosted
tenancy, object storage, online recovery, push, release, deployment, and publication
remain outside this subgate.
