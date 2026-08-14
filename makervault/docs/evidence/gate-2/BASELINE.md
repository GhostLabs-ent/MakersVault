# Gate 2 Baseline and Entry Record

**Gate:** 2 — Bound preview work and prove library responsiveness

**Status:** In progress — executable baseline harness created; preview policy unchanged

**Opened:** 2026-08-14

**Publication state:** Local only; owner deferred pushes until the coordinated v5.1 rollout

## Entry truth

Gate 2 begins from the accepted Gate 1 implementation at `235889e`. No preview
limit, timeout, cache policy, failure state, or skipped-file experience is being
selected before measurement.

The current executable preview paths are:

| Path | Current execution boundary | Current cache/failure truth |
|---|---|---|
| Server image thumbnail | Pillow decodes and bounds pixels, then stores a 512 px JPEG | Persistent file; delivered `private, no-store` |
| Embedded 3MF thumbnail | Server scans a budgeted archive and stores a JPEG | Persistent file; falls through to browser generation when absent |
| STL/OBJ card snapshot | Browser fetches, parses, frames, renders, and encodes on the main thread | Serialized queue; module memory plus successful server upload; no timeout or abort |
| 3MF card snapshot | Browser fetches, synchronously unzips, parses XML/geometry, renders, and encodes on the main thread | Same queue; a single complex archive can block all following cards |
| STEP/STP card snapshot | Browser fetches and passes bytes through OCCT/WASM before rendering | Same queue; no time/complexity budget |
| LightBurn card preview | Browser fetches and may synchronously unzip or scan embedded image data | Separate module cache; no shared queue, abort, persisted failure, or retry |
| Detail viewer | Browser performs interactive parsing and continuous WebGL rendering | Explicit open, but no size/time policy or isolation |

The serialized model-snapshot queue limits simultaneous model file fetches to one,
but it does not make work bounded: parsing and synchronous decompression remain on
the UI thread. Failed automatic previews visually return to “Waiting to generate
preview,” so failure is neither terminal nor explainable. A reload retries files
without a persistent thumbnail.

## Reproducible corpus contract

`benchmarks/preview/generate_corpus.py` creates exactly 20 deterministic,
non-private fixtures and a SHA-256 manifest. The set covers small, medium, large,
multi-part, multi-plate, image-heavy, and malformed STL, OBJ, 3MF, and STEP paths.
Generated binaries are ignored; source and generation rules are versioned.

The benchmark runner:

1. creates fresh project-scoped Docker volumes;
2. generates and uploads the corpus through the supported API;
3. launches a 1440×900 headless Chromium session;
4. measures cold library load, main-thread long tasks, event-loop drift, browser
   command round-trip latency, JS heap, active file requests, failures, and
   generated-thumbnail persistence;
5. reloads the library and repeats the measurements to expose cache behavior; and
6. removes the disposable containers and volumes on exit.

Run from the repository root with:

```sh
./makervault/scripts/preview-benchmark.sh
```

Chromium for the pinned Playwright core version must be installed once with
`cd makervault/benchmarks/preview && npm ci && npx playwright-core install chromium`.
The benchmark dependency is isolated from the production web image. Raw
machine-specific output is written to
`makervault/benchmarks/preview/.artifacts/baseline.json` and is not committed.

## Measurement interpretation

The report records WebGL vendor and renderer. Headless Chromium commonly uses a
software renderer; that is a useful conservative client profile but not evidence
that every end-user GPU will produce identical times. Numeric policy will be based
on bounded product behavior and multiple complexity signals, not one workstation's
elapsed time alone.

Cache hit rate is defined as thumbnail requests divided by thumbnail plus original
model-file requests during a visit. Generated-thumbnail POSTs show successful cold
work. Original-file requests on the warm visit expose failures or missing cache
state that would be repeated for the user.

## Captured baseline

The final uncontaminated run was captured at `2026-08-14T22:33:25Z` against the
accepted Gate 1 tip. Chromium 151 used ANGLE/SwiftShader software rendering on a
16-logical-core, 32 GiB host. The corpus contained 20 files totaling 66,037,534
bytes; two image-heavy 3MF files supplied embedded thumbnails and the other 18
required an original-file preview attempt.

| Measure | Cold visit | Warm reload |
|---|---:|---:|
| Cards visible | 353 ms | 83 ms |
| Preview pass settled | 6.68 s | 6.52 s |
| Original-file requests | 19 | 19 |
| Thumbnail requests | 2 | 2 |
| Generated thumbnails persisted | 0 | 0 |
| Max active original-file requests | 1 | 1 |
| Browser command latency, p95 / max | 115 / 332 ms | 109 / 337 ms |
| Event-loop drift, p95 / max | 133 / 320 ms | 99 / 302 ms |
| Long tasks, count / total / max | 12 / 1,837 / 337 ms | 12 / 1,679 / 336 ms |
| Peak JavaScript heap | 96.0 MB | 96.1 MB |
| Visible result | 17 images, 3 waiting | 17 images, 3 waiting |

The original-file count is 19 rather than 18 because the malformed 3MF is fetched
again by the fallback loader. On the warm visit, the effective request cache hit
rate was only `2 / (19 + 2) = 9.5%`; all 18 no-thumbnail assets were attempted
again.

### Baseline findings

1. Serialization is not responsiveness. The single active request prevents a
   request storm, but main-thread parse/render work still produced repeated
   100–337 ms stalls.
2. Successful canvas snapshots do not persist under the accepted CSP. The current
   `fetch(data:image/...)` conversion is blocked by `connect-src`, so the browser
   displayed snapshots but made zero generated-thumbnail POSTs. This must be fixed
   by producing a Blob directly, not by weakening CSP with `data:` connections.
3. STEP preview is not currently compatible with the accepted CSP. The OCCT path
   attempted string evaluation and failed because `unsafe-eval` is intentionally
   absent. Gate 2 must isolate or replace that path; it must not regress Gate 1 by
   enabling broad script evaluation.
4. Automatic failures are not observable. Malformed STL, 3MF, and STEP work ended
   in the same “Waiting to generate preview” state as untouched work. The malformed
   OBJ also produced invalid geometry diagnostics rather than a clear terminal
   state.
5. Embedded 3MF thumbnails are the only durable cache path in this run. They loaded
   without client geometry parsing on both visits and demonstrate the desired
   static-card behavior.
6. The corpus did not exhaust host memory, but 96 MB peak heap for a 66 MB synthetic
   page is not a product bound. A larger individual model can still allocate and
   block without a time, geometry, or output budget.

## Checkpoint still required

The baseline is captured. The owner decision is now requested in
[OWNER_CHECKPOINT.md](OWNER_CHECKPOINT.md). Preview behavior remains unchanged
until the observable skip/retry/detail experience is approved.
