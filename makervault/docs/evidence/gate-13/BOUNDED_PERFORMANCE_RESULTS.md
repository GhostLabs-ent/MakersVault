# Gate 13C — bounded performance pass and stopping point

**2026-09-10. Application/harness:** `c42614e9cc99b45e32ffd203a4f7e70cb4ff0b30`.
**Disposition:** implemented and checked; residual performance tuning deferred by
owner decision. Not a blanket performance pass or Gate 13C acceptance.

The owner authorized one further pass and explicitly preferred carrying remaining
stalls/API latency over spending substantially more time on them. This pass ends
that tuning work. Reopen with renewed owner direction or a materially worse
user-visible regression; security, supported-platform and release decisions remain
separate. Original thresholds and every historical failure are unchanged.

## What changed

`GET /folders` selects the four required database values instead of hydrating a
tracked `Folder` ORM instance for every row. It still returns validated `FolderOut`
objects with the same IDs, names, tags and parents. It still reads current data on
every request. No cache/invalidation mechanism, pagination/quota, dependency,
authentication, schema, Compose, GC setting or browser/viewer change was introduced.

All **354 API tests pass** (`make verify-api`, 144.84 s). Three new regressions prove:
1,040 entries retain exact fields without ORM load events; create/edit/reparent/delete
are immediately visible; unauthenticated listing remains rejected. Six focused
listing/organization tests also pass (read-only test mount emitted only a pytest
cache-write warning). The static release contract and diagnostic syntax checks pass.
This bounded pass did **not** rerun the full multi-component gate, native browsers,
recovery lifecycle or advisory scans. The previous 351 API / 58 web full gate and
scanned images remain explicitly historical at `82cb2cc`.

## API attribution, without overstating the improvement

[Diagnostic samples](bounded-performance-diagnostics.json) include instrumented
TestClient comparisons and two retained 30-request disposable production-HTTPS
captures. The latter use the old `82cb2cc` API with either the original endpoint or
the proposed projection injected only into that disposable process. The 80/4/2 tree
matches the 1,040-folder hierarchy, but the diagnostic has **no 600-Artifact workload**.

In the retained original HTTP capture, folder endpoint median/p95 were 14.2/81.2 ms;
cyclic garbage-collection callbacks recorded 2.0/70.7 ms. SQL cursor execution and
authentication were comparatively small. This attributes substantial time in some
captured API spikes to GC; it does not identify the cause of the separate browser
pauses, prove a memory leak, or justify changing global GC behavior.

The projection HTTP capture records endpoint median/p95 9.3/70.3 ms and total
request median/p95 22.1/82.1 ms, versus original 27.8/93.1 ms total. GC spikes remain.
These are separate diagnostic runs on a shared host, not a controlled speedup
percentage or qualification result. Preliminary TestClient repeats were mixed and
are retained, including the projection's higher tail on one repeat. Its per-row
conversion instrumentation applies only to the original path; do not treat that
comparison as equal-overhead benchmarking. SQL execution excludes row fetching and
hydration; nested timings overlap and component p95s must not be added together.

Reproduce the HTTP diagnostic while the historical images are available:

```sh
python3 makervault/docs/evidence/gate-13/folder-latency-probe.py
python3 makervault/docs/evidence/gate-13/folder-latency-probe.py --projection
```

The [driver](folder-latency-probe.py), [ASGI wrapper](folder-latency-asgi.py) and
[client](folder-latency-client.mjs) only operate on newly created fixture stacks.
The wrapper adds private fixture timing headers, not production telemetry. Earlier
exploratory probes used temporary copies; the retained driver adds portable paths,
argument validation and named-container cleanup without changing the measured
algorithm. An initial exploratory original HTTP capture also observed GC spikes
and total p95 97.3 ms; the retained original is a repeat, not a substituted failure.

## Final unprofiled browser checks

Both runs use these exact local images, version label `development-gate13b`:

- API: `sha256:b1c67e9f8dad2b29e72a816cc472da9130d02faddf9cd9d35b2a0bd18d633de0`.
- Web: `sha256:7aa39929cd656b8fddaac64d62bc67174f172980e2ab0a1ccad0f298786da5f2`.
- Browser: `sha256:1e23cb1539a3e04d9b5db3fb6da8cc89694a8d1358f8e5ac726157a32536caaa`.

Linux headless Chromium 151.0.7922.34 / Playwright 1.62.1, SwiftShader, 4 GiB browser
memory and 1 GiB shared memory. Runs were sequential after owned tests/builds and
diagnostic jobs completed; unrelated host work was untouched. This is not a quiet-host
or native/physical-browser comparison. TLS trust and hostname validation are unchanged.

| Run | Artifacts / folders | First cards | Folder search | Interaction long tasks | Folder API p50 / p95 | Result |
| --- | --- | --- | --- | --- | --- | --- |
| A | 600 / 1,040 | 471.0 ms | 59.3 ms | 0 observed | 22.8 / 108.2 ms | FAIL API <100 ms |
| B | 600 / 104 | 1,039.5 ms | 23.4 ms | 0 observed | 14.4 / 20.1 ms | FAIL first cards <1,000 ms |

The API tail remains effectively in the previous 108–113 ms range: **not resolved**.
The existing 20-request percentile convention makes reported p95 the maximum of
those 20 observations; no sample count or percentile definition changed.
B retains a 311 ms navigation task. It is unprofiled: the responsible function/native
wait is unknown, and the old preview trace's CPU measurements cannot be assigned to it.
Startup includes navigation and automated sign-in. A records no long tasks in this
sample; zero interaction tasks is not a claim that B has no startup stall.

Both organization runs complete functional assertions, including selection/conflict
ownership, tag/original-byte preservation, prepared/supporting visibility, navigation
and Trash restore. Neither is an overall passing run. Loaded-page DOM retains
8,611 elements / 400 folder rows in stress and 2,779 / 40 in baseline, with zero
closed action descendants. A's initial card snapshot precedes folder-tree arrival;
do not describe its zero initial rows as a changed default expansion policy.

B's separate preview probe completes: detail ready **286.3 ms**, one original-file
request and zero observed detail tasks; warm original-file requests/generated
thumbnail uploads are zero. Cold preview still records a **67 ms long task** and
1,186.6 ms cards readiness. This is not an all-preview performance pass. The 20-file,
66,037,534-byte synthetic corpus and four-triangle detail STL do not qualify arbitrary
large/prepared 3MF files. Retained console output includes a 401 and two SwiftShader
ReadPixels warnings; neither is established as the cause of the historical pause.
No additional native/scheduling investigation was started after this bounded check.

## Evidence and next work

[Browser records](bounded-performance-browser-runs.json) retain both complete runs,
including failures, startup records, preview/corpus metrics and raw artifact hashes.
The [read-only reducer](bounded-performance-analysis.cjs) accepts only `a` and `b`,
refuses unfinished runs, unexpected files and symlinks, and hashes private log bodies
without publishing them. Use `node .../bounded-performance-analysis.cjs a b` with
read access to the named private `/tmp/makersvault-g13c-bounded-0910{a,b}` directories;
do not loosen their permissions. For root-owned artifacts, mount only those exact
directories and the reducer read-only in a disposable local Node container.

Use the [existing browser runner](../../../benchmarks/browser-runtime/README.md)
with the identities above: A uses `--folder-stress --workflows organization
--browsers chromium`; B uses `--workflows organization preview --browsers chromium`.
Each requires a fresh output directory. No profiling or timing-budget changes.

Final evidence checks reproduce both browser records and all 16 raw artifact
hashes, reject four invalid reducer invocations, verify measured/source identities,
and resolve 179 local links. Owned fixture containers are gone; only the unrelated
host workload remains. Diagnostic source syntax and `git diff --check` pass.

**Stop performance tuning here.** G13-01 is carried as a known limitation under the
owner's time-box decision, not as a passing metric. Continue the separate advisory,
supported-platform and selected-release checkpoints only when authorized. Gate 12
remains desktop-deferred; Gate 13C is not automatically closed. No user vault, frozen
release pins or unrelated desktop draft changed. Nothing was pushed, published,
release-tagged or deployed.
