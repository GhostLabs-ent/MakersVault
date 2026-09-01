# Gate 10D — operator workflow and encryption interoperability results

**Date:** 2026-08-31

**Status:** Verified; owner acceptance pending

**Scope:** Offline export/verify/import operator contract and user-owned standard
`age` outer envelope only

## Outcome

Gate 10D turns the accepted 10A–10C primitives into an explicit offline workflow.
`mvault_export.py`, `mvault_verify.py`, and `mvault_import.py` retain one canonical
JSON success result on stdout and now support opt-in canonical phase events on
stderr with `--progress`. Verified reports expose authoritative/derived content
totals and external-reference states; import reports the number restored unavailable
and requiring remount.

Local implementation commit:

- `0939ad0` — phase progress, explicit content/external summaries, stable
  cancellation exits, and workflow regressions.

## Operator contract

[`PORTABLE_VAULT_WORKFLOW.md`](../../PORTABLE_VAULT_WORKFLOW.md) defines secure
working permissions, stopped-state responsibilities, separate stdout/stderr
automation, export and independent verification, empty-instance import, external
remount interpretation, cancellation/retry behavior, and exit codes.

Ctrl-C returns `130`; validation/configuration failure returns `2`; success returns
`0`. Existing exporter and importer cleanup/recovery guarantees remain authoritative:
export removes unpublished work, verification mutates nothing, import removes
pre-publication staging, caught publication cancellation rolls back, and an
uncatchable interruption is recovered through the validated publication journal on
the next same-target invocation.

## Encryption boundary

ADR 0017 is implemented as documentation and ownership boundaries, not application
cryptography. The runbook uses the official external `age` CLI recipient/identity
workflow and the standard v1 outer envelope:

```text
library.mvault -> age recipient encryption -> library.mvault.age
```

MakersVault does not bundle/invoke `age`, add an encrypted format variant, accept
keys through the API, store identities/passphrases, escrow recovery material, or
claim secure plaintext erasure. Multiple recovery recipients, protected plaintext
staging, no-clobber output, independent post-decryption verification, lost-key
finality, and off-host recovery testing are explicit. Core import receives only a
successfully decrypted plaintext `.mvault`; wrong-key/envelope failure remains
outside MakersVault staging.

## UI decision

No UI orchestration was added. Export/import may run for hours and must not depend
on one browser request. Authenticated UI work remains deferred until a separately
approved durable job model proves authorization, restart, progress, cancellation,
cleanup, and bounded history.

## Focused evidence

```text
docker build --target test -t makersvault-api-gate10d-test makervault/api
docker run --rm makersvault-api-gate10d-test python -m pytest -q \
  tests/test_mvault_verify.py tests/test_mvault_export.py tests/test_mvault_import.py
44 passed

docker run --rm makersvault-api-gate10d-test python -m pytest -q
236 passed
```

The focused suite proves additive verifier summaries, JSON-only stdout, canonical
progress events on stderr, source/external summary propagation across export and
import, explicit stopped confirmations, stable cancellation exit `130`, and all
accepted 10A–10C archive, publication, rollback, and recovery behavior.

## Full repository evidence

```text
make verify
API: 236 passed
Web: production build/verification passed
Slicer bridge: tests and build passed
Compose/security: canonical manifests and production-secret rejection passed
Container smoke: direct/same-origin API, headers, 512 MiB policy, non-root UIDs, schema 12 passed
Release contract: v5.1.0 verified
```

The full repository gate completed successfully on 2026-08-31 from the local Gate
10D tree. It did not push, tag, publish, deploy, invoke `age`, handle an identity,
or contact an external storage provider.

## Gate boundary and next decision

Gate 10D is stopped at its owner checkpoint. Acceptance would freeze the offline
workflow and user-owned encryption boundary as Gate 10E inputs. Gate 10E, built-in
encryption/key custody, browser orchestration, S3, merge/live import, push, tag,
release, deployment, and publication remain unauthorized.
