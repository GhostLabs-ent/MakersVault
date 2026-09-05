# Gate 13A — baseline and end-state inventory results

**Date:** 2026-09-05

**Status:** ACCEPTED by the owner on 2026-09-05 at evidence commit `c2e9f94`

**Tested entry:** `236c0fd14faf6cddb7e46a78657e6000cdb4d79f`

**Application implementation:** `1a209aa8711b1717aa4400d25cd269953eb1357a`

**Schema / recovery:** 17 / raw outer format 1, recovery contract 6; unchanged

## Outcome

The current local implementation passes its complete existing verification gate.
The strategy has a traceable delivered core, but Gate 13 cannot yet close: legacy
end-to-end verification still assumes JWTs/schema 5, current whole-instance
lifecycle evidence is incomplete, and later release/platform qualification has
not happened. These are explicitly owned findings, not silently accepted gaps.

The [traceability ledger](TRACEABILITY.md) maps 17 product/architecture commitments,
all ten invariants, four audit findings, and nine carry-forward groups. The
[security revalidation](../../security/GATE_13_REVALIDATION.md) reconciles all 16
original findings without treating historical vulnerability scans as current.
Gate 12 remains owner-deferred to desktop with every service and non-lock-in
obligation retained. Its deferral is not an excuse to defer current release safety.

## Current verification

Executed from the repository root against the unchanged application source:

```bash
make verify
docker run --rm makersvault-api-gate0-test python -m pytest --collect-only -q
docker run --rm makersvault-api-gate0-test python -m pytest -q
docker run --rm makersvault-web-gate0-test
docker run --rm makersvault-api-gate0-test \
  python tests/gate10_portable_scale_drill.py \
  --artifacts 1200 --large-payload-mib 64 --max-rss-mib 256 --batch-size 37
git diff --check
```

The full `make verify` returned zero. API and web were also executed directly in
their just-built test images so the recorded results do not rely on a cached web
build layer or compressed aggregate output. The scale drill was repeated to retain
its numeric report; the table below is the second successful run.

| Verification | Result |
|---|---|
| Complete repository target | PASS: API, web, bridge, Compose/security, container smoke, passkeys, release contract |
| API direct run | **313 passed in 140.53 s**; collection independently reported 313 |
| Web direct run | Typecheck PASS; **32 tests in 11 files passed**; production build PASS |
| Bridge | Tests and executable build passed through pinned Go container target |
| Deployment configuration | Canonical development/production/compatibility and smoke/benchmark overlays passed; missing production auth configuration still rejected |
| Fresh disposable install | Current non-root API/web smoke, schema 17, direct/same-origin cookie sessions, logout revocation and security headers passed |
| Chromium passkey drill | Chromium 151 virtual authenticator: one credential; registration, current-strength confirmation, required-Administrator policy and fresh password-plus-passkey login passed |
| Release contract | PASS for existing v5.1.0 identity/publication rules; **not** later exact-image runtime qualification |

Local test-image identities (not release images):

```text
API sha256:37fea412d5d1dbf54f205ff77f1cb1e5d10ebaa71136a0b45026d03458336e5a
Web sha256:ef916cb4c0c1d41a6cdbb38aa406cc45578cb6ab34643085ea877ddf7477397d
```

The existing browser-data freshness and >500 kB web chunk warnings remain visible;
no dependency/bundle change was made to hide them.

## Portable scale revalidation

The current source's fixture migrates to schema 17. Export → independent verify →
clean schema-12 import → re-export compared catalogs and payloads by name/SHA-256:

| Measure | Observed result |
|---|---:|
| Artifacts | 1,200 |
| Logical catalog records | 8,452 |
| Managed files / bytes | 3,479 / 67,186,682 |
| External records | 121 |
| Large deterministic incompressible payload | 64 MiB |
| Portable members compared | 3,790; semantic and byte equality passed |
| Export / verify / import / re-export | 5.466 / 1.329 / 45.923 / 5.144 seconds |
| Process-reported peak RSS, each worker | 140,926,976 bytes (about 134.4 MiB) |
| Enforced RSS ceiling | 268,435,456 bytes (256 MiB); passed |

This was a local Linux/Docker development-host run with another unrelated workload
active. Timings and reported RSS are observations, not end-user guarantees or a
controlled comparison to Gate 10. No unrelated workload was changed. The drill
uses private generated temporary data and deletes it on exit. Its clean import
does **not** start a schema-17 API or prove new-install authentication; 13B owns that
join. Real credential/session/audit exclusion is separately covered by the
schema-17 export regression in the 313-test matrix.

## Gate 13 required evidence — honest current state

| Required evidence | What 13A established | What still prevents final closure |
|---|---|---|
| Full strategy/invariant/security trace | Inventoried with source/tests and owned gaps | Owner review and final dispositions at 13D |
| Clean install | Fresh schema-17 development smoke and real browser passkey workflow | Current production/TLS/exact-image operator qualification |
| Representative upgrade | Schema-4 fixture and ordered/idempotent migration regressions pass through current schema | One current production-Compose operator upgrade/drill, including startup identity |
| Disaster restore and rollback | Current raw archive/corruption/legacy compatibility, session/challenge revocation, recovery marker and stopped-account tests pass | Joined schema-17 disposable restore/startup/rollback with matched bytes and identity state |
| Portable export/import | Current 1,200-Artifact content round trip and adversarial/secret-exclusion tests pass | Start the clean imported schema-12 vault on current schema 17 and prove fresh bootstrap/content preservation |
| Trust-boundary review | Current regression/source boundaries and all historical finding dispositions recorded | Fresh advisories, operator/real-platform review and explicit residual decisions |
| Re-baselined roadmap | Proposed ordering and carry-forward dependencies recorded | Owner accepts the achieved end state and next cycle; no automatic Gate 0 restart |

## Changes and next checkpoint

Documentation now separates frozen-candidate evidence, current runtime/test proof,
stale harnesses, explicit desktop deferral, and proposed future work. No application,
schema, manifest, dependency, or verification-harness code changed in 13A.
Historical gate evidence and the untracked desktop architecture draft are intact.

**Owner decision:** 13A accepted and 13B authorized on 2026-09-05. Proceed to
13B: repair the cookie/CSRF/schema
assumptions in the current-build harnesses and execute the joined disposable
upgrade/recovery/portable-startup workflow. Do not restore JWT compatibility, weaken
production cookie policy, or edit old results to qualify a new baseline.

Gate 13 remains **IN PROGRESS**. No later candidate was assembled or selected;
no user installation was deployed or modified; no push, tag, image publication,
external service, or release is authorized by these results.
