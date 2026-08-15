# Gate 2 Evidence Review

**Gate:** 2 — Bound preview work and prove library responsiveness

**Status:** Accepted

**Evidence date:** 2026-08-14

**Accepted:** 2026-08-14

**Baseline commit:** `2ad0348`

**Approved contract commit:** `35aa158`

**Verified implementation:** `af57da3`

**Publication state:** Local only; owner deferred all pushes until the coordinated
v5.1 rollout

## Objective result

One model can no longer monopolize the library UI. Card parsing and rendering run
in a shared, terminable, one-active-job worker queue with explicit byte, geometry,
archive, memory, and wall-time ceilings. Successful work becomes a server-normalized
static thumbnail; failure, policy skip, and retry intent survive reload and API
restart. Original files remain governed only by the separate Gate 1 ingest policy.

No manual thumbnail-upload workflow was added. STEP/STP automatic parsing and the
old CSP-incompatible OCCT browser path are absent from the production bundle.

## Implemented contract

- One active model or LightBurn preview job and at most eight queued near-viewport
  card jobs.
- Automatic ceiling: 16 MiB source, 100,000 triangles/faces, 64 MiB expanded
  archive data, 256 entries, 128 MiB estimated geometry/output memory, and 10 s.
- Explicit detail ceiling: 64 MiB source, 500,000 triangles/faces, 256 MiB expanded
  3MF data, 1,000 entries, 256 MiB estimated memory, and 30 s.
- Static-card priority: embedded thumbnail, persisted generated thumbnail, bounded
  worker job, then visible terminal fallback.
- Persisted status/reason/attempt/policy/timestamp/source fields in additive schema
  migration 4.
- `Preview paused`, `Preview unavailable`, explicit retry, explicit oversized-detail
  confirmation, detail cancellation, and automatic/on-demand/disabled modes.
- Direct Blob thumbnail upload under the existing CSP; no `data:` connection or
  `unsafe-eval` relaxation.
- LightBurn ZIP directories are size/entry checked before worker decompression and
  use the same queue, timeout, persistence, and retry contract.

## Final deterministic measurement

The clean candidate run was captured at `2026-08-14T23:41:26Z` with Chromium 151,
ANGLE/SwiftShader, 16 logical CPUs, and 32 GiB host memory. The versioned corpus
contains 20 files totaling 66,037,534 bytes. Raw host-specific output remains an
ignored artifact at `benchmarks/preview/.artifacts/baseline.json`.

| Measure | Gate 1 baseline, cold | Gate 2 candidate, cold | Gate 1 baseline, warm | Gate 2 candidate, warm |
|---|---:|---:|---:|---:|
| Cards visible | 353 ms | 294 ms | 83 ms | 166 ms |
| Preview pass settled | 6.68 s | 5.15 s | 6.52 s | 4.88 s |
| Original-file requests | 19 | 16 | 19 | 0 |
| Thumbnail requests | 2 | 14 | 2 | 14 |
| Generated thumbnail uploads | 0 | 12 | 0 | 0 |
| Max active original requests | 1 | 1 | 1 | 0 |
| Browser command p95 / max | 115 / 332 ms | 8 / 33 ms | 109 / 337 ms | 4 / 64 ms |
| Event-loop drift p95 / max | 133 / 320 ms | 5 / 48 ms | 99 / 302 ms | 0.3 / 14 ms |
| Long tasks, count / max | 12 / 337 ms | 0 / 0 ms | 12 / 336 ms | 0 / 0 ms |
| Peak JavaScript heap | 96.0 MB | 10.5 MB | 96.1 MB | 11.5 MB |
| Visible terminal result | 17 images, 3 waiting | 14 images, 3 paused, 3 failed | 17 images, 3 waiting | Same persisted result |

The candidate intentionally reads 16 originals on the cold pass: twelve succeed
and persist; the 250,000-triangle STL is read then policy-skipped by complexity;
three malformed files fail safely. The 500,000-triangle STL is skipped from server
size metadata, STEP is skipped by format policy, and two 3MF files already have
embedded images. The warm model-file request count is zero, for a 100% static-image
cache share among attempted preview resources (`14 / (14 + 0)`).

The explicit detail probe opened a known STL in 310 ms with one active/original
request and zero long tasks. A separate deterministic LightBurn probe produced one
cold source request, one persisted thumbnail upload, zero warm source requests,
and zero long tasks. Expected headless software-driver diagnostics were recorded
separately; application console errors were empty.

## Exit-criterion evidence

| Gate 2 exit criterion | Status | Evidence |
|---|---|---|
| Non-private pathological corpus exists | Passed | Deterministic 20-file generator and SHA-256 manifest cover small, medium, large, malformed, multipart, multiplate, and image-heavy STL/OBJ/3MF/STEP inputs. |
| Concurrency and memory are bounded | Passed | Shared one-active/eight-waiting queue; worker byte/triangle/archive/estimated-memory/time checks; 10.5–11.5 MB observed peak heap. |
| A pathological model cannot block navigation | Passed | Cold, warm, detail, and LightBurn phases recorded zero long tasks; cold command latency p95 fell from 115 ms to 8 ms. |
| Repeat visits primarily use static thumbnails | Passed | Fourteen thumbnails and zero original model requests on warm reload versus 19 original requests at baseline. |
| Failure and retry are visible and repeatable | Passed | Three malformed fixtures remain visibly failed; three policy cases remain paused; API tests cover safe reasons, restart persistence, retry request, and invalid-reason rejection. |
| Interactive work is explicit and bounded | Passed | Detail-only worker uses larger limits, supports cancel, and a measured detail open completed with one active job and no long task. |
| Preview modes and type-aware fallbacks remain | Passed | Automatic/on-demand/disabled paths apply to models and LightBurn; embedded 3MF, generated model, generated LightBurn, malformed, oversized, and STEP fallbacks are exercised. |
| Original-file policy is independent | Passed | Preview ceilings only change derived status. The Gate 1 512 MiB per-file ingest contract and unlimited ordinary batch count remain unchanged. |

## Verification

| Check | Result |
|---|---|
| API migration/policy/route suite | Pass; 64 tests under Python 3.11 |
| Web type check and unit suite | Pass; 7 tests |
| Production web build | Pass; isolated 12.3 KB model worker and 9.0 KB LightBurn worker; no OCCT/WASM output chunk |
| Compose development/deployment validation | Pass |
| Fresh container smoke | Pass; schema 4, direct/same-origin API, security headers, 512 MiB ingest policy, non-root API/web |
| Bridge tests/build | Pass; unchanged protocol boundary |
| Complete repository harness | Pass; `make verify` against `af57da3` working tree |
| Deterministic browser benchmark | Pass; cold/warm/detail/LightBurn probes, no timeouts or application console errors |

The known production main-bundle size and stale browser-metadata warnings remain;
Gate 2 adds small isolated worker chunks and removes the OCCT/WASM output, but does
not claim to solve general application code splitting.

## Data, upgrade, and rollback result

Migration 4 adds preview state only. Startup classifies legacy records without
overwriting a current terminal result; embedded/generated thumbnail truth wins
over stale metadata. No original, supporting, prepared-print, or mounted file is
renamed, rewritten, rejected, or deleted.

Setting preview mode to disabled provides the operational fallback while retaining
cached images and all originals. A code rollback follows the matched database and
storage snapshot rule from ADR 0002; the additive columns do not require a lossy
down migration.

## Residuals and next decision

- STEP/STP remains downloadable and handoff-capable but has no v5.1 interactive
  browser parser. This is deliberate CSP containment, not a failed upload.
- The repeatable automated browser measurement is Chromium-based. Worker and
  OffscreenCanvas absence produces a safe terminal fallback; release Gate 5 should
  record the supported-browser matrix rather than implying untested parity.
- Browser file URLs retain the accepted Gate 1 query-token compatibility residual;
  Gate 11 still owns the final session/file-delivery architecture.

The owner approved Gate 2 closeout on 2026-08-14. Gate 3 may open from a measured
organization-workflow baseline; only one roadmap gate remains active at a time.
