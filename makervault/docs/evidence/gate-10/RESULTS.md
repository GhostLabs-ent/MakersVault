# Gate 10 Results — portable vault and storage abstraction

**Date:** 2026-08-31

**Status:** Verified; owner closeout pending

## Delivered

- **10A:** normative, deterministic, secret-free `.mvault` v1 plus a dependency-free
  streaming verifier and adversarial/golden fixtures.
- **10B:** capability-explicit `ContentStore`, proven local adapter, migrated local
  service seams, and stopped-instance streaming export with independent verification
  and atomic create-if-absent publication.
- **10C:** isolated clean-instance schema-12 import, provider-safe managed keys,
  complete graph/byte audits, external-remount truth, and journaled storage-first /
  SQLite-last publication and rollback.
- **10D:** offline CLI workflow, canonical progress/results, explicit external
  summaries, cancellation contract, and user-owned standard `age` outer-envelope
  documentation without application key custody.
- **10E:** representative scale/RSS/semantic equality drill, pinned format and raw
  backup compatibility, capacity/interruption evidence, failure matrix, and a
  documented no-go decision for S3 implementation.

## Preserved truths

- Raw server-backup outer format 1 remains disaster recovery and rollback; it was
  not renamed, replaced, or weakened.
- `.mvault` import is absent/empty schema-12 reconstruction only. There is no merge,
  overwrite, replace, live-instance, or reverse-import rollback mode.
- Managed bytes are complete and independently hashed. External no-copy records are
  explicit and restore unavailable until remounted; bytes are never invented.
- Secrets, sessions, provider credentials, mount activation, job/purge journals,
  quarantine, and deployment state never enter `.mvault` v1.
- `age` identities/passphrases remain wholly user-owned. MakersVault implements no
  cryptography, escrow, encrypted variant, or cloud dependency.
- `LocalContentStore` remains the only provider. No S3 claim, SDK, credential,
  endpoint, bucket, or partially supported driver exists.

## Evidence index

- [Gate 10 baseline and decisions](BASELINE.md)
- [10A results](SUBGATE_10A_RESULTS.md)
- [10B results](SUBGATE_10B_RESULTS.md)
- [10C results](SUBGATE_10C_RESULTS.md)
- [10D results](SUBGATE_10D_RESULTS.md)
- [10E results](SUBGATE_10E_RESULTS.md)
- [Portable format v1](../../MVAULT_FORMAT_V1.md)
- [Operator workflow](../../PORTABLE_VAULT_WORKFLOW.md)
- [Failure and rollback matrix](../../PORTABLE_VAULT_FAILURE_MODES.md)
- [Storage-provider evaluation](../../CONTENT_STORE_PROVIDER_EVALUATION.md)

## Final verification

The 2026-08-31 clean `make verify` run passed with 239 API tests, the complete web
test-target verification image, Slicer Bridge tests and production build, every
canonical/deployment/smoke/benchmark Compose configuration and security check, the
schema-12 container smoke drill, and the v5.1.0 release contract. `git diff
--check` passed before the run.

The representative drill additionally proved export, independent verify,
clean-instance import, and re-export over 1,200 Artifacts, 8,452 logical catalog
records, 3,479 managed files, 121 external references, and a deterministic
incompressible 64 MiB model. Every one of 3,790 portable members compared equal by
name and SHA-256, and each worker stayed below 68 MiB peak RSS against a 256 MiB
ceiling. Exact commands, timings, compatibility hashes, and failure injections are
recorded in the 10E results.

## Remaining authority boundary

All work remains local. Owner closeout does not itself authorize push, tag, release,
deployment, publication, provider connection, key handling, browser orchestration,
merge/live import, or Gate 11. Each requires its own direction under the
architecture runbook.
