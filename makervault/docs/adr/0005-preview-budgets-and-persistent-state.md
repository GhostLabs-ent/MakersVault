# ADR 0005: Bounded preview workers and persistent outcomes

**Status:** Accepted

**Accepted:** 2026-08-14

## Context

The accepted Gate 1 client parsed STL, OBJ, 3MF, STEP, and LightBurn content in
the browser. A one-at-a-time card queue limited request concurrency, but parsing,
ZIP expansion, WebGL setup, and snapshot encoding could still occupy the main
thread without byte, geometry, memory, or wall-time limits. Failed work was not a
durable outcome, so later visits retried the same source files. The generated
thumbnail conversion also violated the accepted CSP, while the OCCT STEP path
required string evaluation prohibited by that CSP.

Original files are vault content. Preview eligibility must never become an upload,
retention, download, or slicer-handoff limit.

## Decision

MakersVault treats card previews as derived, bounded, persistent work.

- Use embedded or already-generated static thumbnails before considering source
  parsing.
- Queue at most eight near-viewport jobs behind one active job across model and
  LightBurn preview paths.
- Fetch, parse, decompress, calculate geometry normals, render card images, and
  extract LightBurn images in terminable workers.
- Enforce the owner-approved automatic and explicit-detail byte, triangle/archive,
  estimated-memory, and wall-time limits exposed through authenticated server
  policy.
- Persist `pending`, `ready`, `failed`, `skipped_policy`, and `retry_requested`,
  together with a stable reason, attempt count, policy version, update time, and
  source.
- Produce a Blob directly and persist a normalized server thumbnail. Do not add
  `data:` to `connect-src`.
- Keep STEP/STP automatic parsing disabled. Do not add `unsafe-eval`; an original
  STEP file remains downloadable and eligible for normal handoff even when browser
  preview is unavailable.
- Keep interactive model work behind the detail view. Apply the larger detail
  ceiling, allow cancellation, and split WebGL initialization/render stages so
  they yield between frames.
- Make automatic, on-demand, and disabled modes apply consistently to model and
  LightBurn cards.

The initial defaults are the approved values in
[Gate 2 owner checkpoint](../evidence/gate-2/OWNER_CHECKPOINT.md). Operators may
change them through validated integer environment settings. A deliberate policy
version bump may reconsider old policy skips; normal startup must preserve terminal
outcomes.

## Consequences

- A cache miss costs one bounded worker job; a cache hit costs only a static image
  request.
- Pathological or unsupported files remain stored and usable while their cards
  show a safe terminal state.
- Schema version 4 adds only preview-state columns and an index; original content
  and existing metadata are unchanged.
- Worker termination provides a real timeout boundary, but configured ceilings
  still need conservative defaults because a browser worker is not a separate OS
  security sandbox.
- STEP has a polished fallback rather than an interactive v5.1 browser view.
- Interactive rendering favors bounded responsiveness over full device-pixel
  resolution and renders on changes rather than continuously.

## Migration and rollback

Migration 4 is additive. Existing records are classified on startup only when
they have no recorded outcome, their policy version is stale, a thumbnail exists,
or a stale `ready` state has lost its thumbnail. Recorded failure and skip states
otherwise survive restart.

Operational rollback sets preview mode to disabled, leaving existing thumbnails,
originals, and metadata intact. Code rollback across schema 4 may ignore the
additive columns; release rollback still restores the matched pre-upgrade database
and storage snapshot under ADR 0002.

## Superseding conditions

Revisit this decision before introducing server-side preview infrastructure,
distributed job runners, another database backend, a CSP-compatible isolated STEP
implementation, or device-specific policy negotiation.
