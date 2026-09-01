# Gate 10E — scale, compatibility, and closeout results

**Date:** 2026-08-31

**Status:** Accepted; Gate 10 closed

**Accepted:** 2026-08-31

**Scope:** Portable-vault scale, semantic equality, compatibility, interruption,
failure documentation, and storage-provider evaluation only

## Outcome

Gate 10E proves the accepted 10A–10D implementation as a complete local
portable-vault system without adding a provider or expanding restore authority.
The source-owned disposable scale drill generates a mixed schema-12 vault, runs
export, independent verification, clean import, and re-export in separate measured
processes, then compares every portable catalog and payload member by name and
SHA-256.

Local implementation commit:

- `c532b2f` — representative portable-vault scale drill, CI-scale semantic/byte
  regression, and explicit export/import capacity-failure cleanup tests.

## Representative scale result

```text
docker run --rm makersvault-api-gate10e-test \
  python tests/gate10_portable_scale_drill.py \
  --artifacts 1200 \
  --large-payload-mib 64 \
  --max-rss-mib 256 \
  --batch-size 37
```

```json
{"artifacts":1200,"batch_size":37,"external_records":121,"large_payload_bytes":67108864,"logical_catalog_records":8452,"managed_bytes":67186682,"managed_files":3479,"max_rss_bytes":268435456,"portable_members_compared":3790,"semantic_and_byte_equal":true,"workers":{"export":{"elapsed_seconds":5.237,"peak_rss_bytes":67776512},"import":{"elapsed_seconds":45.585,"peak_rss_bytes":67776512},"reexport":{"elapsed_seconds":5.103,"peak_rss_bytes":67776512},"verify":{"elapsed_seconds":1.338,"peak_rss_bytes":67776512}}}
```

The fixture covers nested Folders, active and Trash Artifacts, two-Revisions
histories, managed and missing external current content, prepared G-code/metadata,
derived thumbnails, Projects, memberships, relationship chains, Machine profiles,
Artifact-machine associations, portable settings, thousands of small files, and
one deterministic incompressible 64 MiB model. All four worker processes remained
below 68 MiB peak RSS and the 256 MiB evidence ceiling. The source and restored
archives had 3,790 logical/payload members with identical names and digests; header
creation time and closing checksum inventory are intentionally not semantic
equality inputs.

The committed CI-scale drill repeats the same four-phase equality and RSS contract
with a smaller fixture on every API suite run.

## Compatibility and recovery evidence

```text
pytest focused portable stack: 47 passed
pytest complete API suite: 239 passed

pytest pinned v1 golden + raw format-1/recovery contracts + import interruption:
7 passed
```

The targeted compatibility run proves:

- the `.mvault` v1 gzip bytes retain pinned SHA-256
  `1c2edb89454fd141237c36c649cd78362523dff0c6c52b851ab0eec327318d04`;
- raw server-backup outer format 1 still verifies for the legacy no-contract shape,
  recovery contract 2/schema 8, pre-Gate-7E schema 10, and pre-Gate-9D contract
  3/schema 12 with current re-audit;
- simulated storage-first process death is rolled back on the next invocation; and
- caught keyboard cancellation after storage publication restores absent targets.

New capacity injections prove export publishes no partial output after `ENOSPC` and
import publishes no target after payload-staging `ENOSPC`. Existing adversarial
tests continue to cover corruption, limits, unknown versions/features, external
absence, non-empty targets, graph/projection mismatch, hostile journals, and
publication rollback.

## Failure and rollback documentation

[`PORTABLE_VAULT_FAILURE_MODES.md`](../../PORTABLE_VAULT_FAILURE_MODES.md) records
corruption, capacity, configured limits, unsupported version/feature, no-copy
external states, cancellation, uncatchable interruption, wrong/lost `age` recovery
material, plaintext-retention, clean-target, and rollback behavior. It explicitly
states that v1 has no exact capacity preflight and that raw format-1 backup—not
portable reverse import—is the in-place rollback mechanism.

## Storage-provider decision

[`CONTENT_STORE_PROVIDER_EVALUATION.md`](../../CONTENT_STORE_PROVIDER_EVALUATION.md)
records a no-go decision for S3 in Gate 10. The current seam proves local behavior
but does not yet model provider-neutral multipart staging, conditional commit,
unknown timeout outcomes, materialization cache, quota, pagination, versioned
reversible deletion, cross-domain SQLite reconciliation, credentials/TLS, or a
named-provider conformance matrix. No SDK, endpoint, bucket, credentials, or driver
was added or exercised.

## Full repository evidence

The final clean repository gate passed on 2026-08-31:

```text
make verify
API: 239 passed in 65.45s
Web: test-target verification image built successfully
Slicer bridge: go test ./... passed; production binary built
Compose/security: canonical, deployment, smoke, and benchmark manifests validated;
                  security policy checks passed
Container smoke: passed (direct and same-origin API, security headers,
                 512 MiB file policy, non-root UIDs, schema 12)
Release contract: verified for v5.1.0
```

`git diff --check` also passed before the run. The verification used local test
containers only; it did not push an image or commit, contact a storage provider,
handle an encryption key, deploy, tag, release, or publish anything.

## Gate boundary and next decision

Gate 10E and Gate 10 were accepted by the owner on 2026-08-31. Acceptance freezes
`.mvault` v1, the local `ContentStore`, offline operator/encryption boundary,
clean-instance restore, scale/compatibility evidence, and the S3 no-go decision.
Any provider implementation, built-in key custody, merge/live import, browser job
orchestration, push, tag, release, deployment, and publication remain unauthorized.
The owner's next direction opened only Gate 11's discovery and policy checkpoint;
Gate 11 schema and implementation remain separately gated.
