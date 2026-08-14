# Gate 2 Owner Checkpoint — Bounded Preview Experience

**Status:** Approved

**Approved:** 2026-08-14

**Evidence:** [BASELINE.md](BASELINE.md)

## Proposed v5.1 contract

Uploading and retaining original files remains independent from preview policy.
MakersVault will accept a file within the Gate 1 ingest/storage limits even when it
is too large or complex to preview automatically. Large file sets are not given a
batch quota; only active preview work is bounded.

Library cards use static thumbnails only:

1. use a server-extracted image/3MF thumbnail when available;
2. use a previously generated thumbnail when available;
3. otherwise enqueue one near-viewport background preview job; and
4. show a type-aware, terminal card state when the job fails or policy skips it.

No manual thumbnail upload is introduced.

## Proposed initial budgets

These are conservative v5.1 defaults, not upload limits. They will be configurable
within validated ranges for installations with different client hardware.

| Boundary | Automatic card default | Explicit detail-view ceiling |
|---|---:|---:|
| Active parse jobs | 1 | 1 |
| Queued near-viewport jobs | 8 | N/A |
| Job wall time | 10 s | 30 s |
| STL/OBJ original bytes | 16 MiB | 64 MiB |
| STL/OBJ triangles or faces | 100,000 | 500,000 |
| 3MF compressed bytes | 16 MiB | 64 MiB |
| 3MF expanded model data | 64 MiB | 256 MiB |
| 3MF archive entries examined | 256 | 1,000 |
| 3MF total triangles | 100,000 | 500,000 |
| Estimated geometry/output memory | 128 MiB | 256 MiB |
| STEP/STP automatic generation | Off | Isolated, 30 s maximum |

The automatic 100,000-triangle ceiling includes the corpus's medium STL, largest
OBJ, and 50,000-triangle multiplate 3MF, while intentionally excluding the
250,000- and 500,000-triangle stress models that contributed to the worst stalls.
Byte and complexity limits both apply so compressed or unusually encoded files
cannot evade the intended work bound.

Parsing must run in a terminable worker or equivalent isolated boundary. A timeout
that cannot stop the underlying work does not satisfy this contract. Main-thread
rendering must yield and the verification target is no preview-caused long task
above 50 ms. Only near-viewport jobs remain queued; leaving the library cancels
unstarted work.

## Proposed observable states

### Skipped automatically

Card copy:

> **Preview paused**
>
> This model is too large or complex for an automatic preview.

The card keeps normal model name, metadata, download, and slicer actions. “Paused”
is deliberate: the original is not corrupt or unsafe, and upload did not fail.
Opening details offers **Try interactive preview** only when the file fits the
larger detail ceiling. If it exceeds that ceiling, details explain that the
original can still be downloaded or sent to the slicer.

### Failed

Card copy:

> **Preview unavailable**
>
> MakersVault could not read this model preview.

Details show a safe reason such as “Malformed STL,” “3MF archive could not be
read,” “Timed out,” or “Browser preview unsupported.” A **Retry preview** action is
available for failed/time-out work. Retry never bypasses the hard detail ceiling
and is not an automatic loop.

### Pending and ready

- Pending work says **Preview queued** and shows its queue position only when useful.
- Active work says **Generating preview…** with a cancel action in details.
- Ready work uses the persisted static thumbnail on later visits without reparsing
  the original model.

## Persistence and cache truth

Persist `pending`, `ready`, `failed`, `skipped_policy`, and `retry_requested` with a
stable reason code, policy version, attempt count, and timestamps. A policy-version
change may make a skipped item eligible again; it must not silently retry every
page load.

Snapshot generation will return a Blob directly for upload. The CSP remains
unchanged; `data:` is not added to `connect-src`, and broad `unsafe-eval` is not
added for STEP. Successful generation must update the card immediately and survive
a new browser context.

## Decision requested

Approve or revise:

1. the words **Preview paused** for policy-skipped files;
2. the detail-only **Try interactive preview** path within the larger ceiling;
3. the proposed automatic/detail numeric defaults; and
4. the rule that STEP/STP receives no automatic card parse in v5.1 unless an
   isolated CSP-compatible implementation is proven.

## Owner decision

The owner approved the proposed observable states, detail-only override, numeric
defaults, and STEP/STP automatic-preview restriction on 2026-08-14. Implementation
may proceed without weakening the accepted Gate 1 CSP, adding manual thumbnail
uploads, or applying preview limits as upload limits.
