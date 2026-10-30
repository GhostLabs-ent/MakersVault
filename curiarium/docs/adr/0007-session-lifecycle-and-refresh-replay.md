# ADR 0007: Session lifecycle: rotation, a bounded grace window and refresh replay

**Status:** Accepted

**Accepted:** 2026-11-04

**Implementation:** ticket `Mf-7op4`.

## Context

The access token is a short-lived JWT, but it is not stateless. Every guarded
request runs `auth.require_auth`, which decodes the token and then reads the
session row back (`sessions.get`) and checks it on the same connection
(`sessions.is_live`, which already tests `revoked_at IS NULL`). The row, not the
token, is the authority. That is why revoking a session, disabling the account
or deleting the user takes effect on the very next request with no cache to
invalidate and no epoch to bump.

The refresh token is opaque and stored only as a sha256 hash. Each refresh
rotates it: `sessions.rotate` writes a fresh hash over the old one in one
UPDATE guarded by the presented hash, so two concurrent refreshes cannot both
win. Before this ticket the loser simply received a 401. That is a defensible
single-use rule, but two tabs in one browser share one session row, and a tab
that wakes from sleep holding the token it slept with is not an attacker: it is
the ordinary case the rule punished with a forced sign-in. The same was true of
a client whose first refresh response was lost on the network.

The other half of the problem is what to do when a superseded token is
presented. Treating every old hash as theft is the usual refresh-token-reuse
detection, but the response matters: revoking every session of the user makes a
single stale token a denial-of-service lever against its own owner.

## Decision

1. **Keep one generation of rotation history.** Migration 011 adds
   `sessions.previous_refresh_token_hash` and `sessions.rotated_at`. Only a hash
   is stored, never a token, and `previous_refresh_token_hash` is deliberately
   not unique: it only ever holds a hash that has already been superseded. One
   generation is enough for the grace path described below; keeping more would
   keep more old tokens interchangeable with the live one.

2. **A superseded token is accepted once, for 60 seconds.**
   `sessions.REFRESH_GRACE_SECONDS = 60` is a module constant, not an
   environment variable, because it is a correctness bound rather than a
   deployment preference. When the presented hash equals
   `previous_refresh_token_hash` and the row was rotated at most 60 seconds ago,
   `rotate` performs a second full rotation and returns `ROTATE_GRACED`. The
   grace path updates the same row in one guarded UPDATE, guarded on both the
   current and the presented hash, so it has the same TOCTOU discipline as the
   ordinary path. The new `previous_refresh_token_hash` is assigned from the
   pre-update `refresh_token_hash` in the same statement, so the intermediate
   hash is stashed atomically and the original token becomes older than the one
   generation that is kept.

3. **A longer window is worse, not friendlier.** The grace window is exactly
   the interval in which a stolen refresh token is interchangeable with the
   victim's live one. Sixty seconds covers a tab waking and re-sending the
   token it held; an hour would make a stolen token replayable for an hour with
   no benefit to any honest client, because an honest client refreshes
   immediately, not eventually.

4. **A previous-generation token outside the window is a replay: 401, revoke
   that row only, and one staged audit row.** `rotate` returns
   `ROTATE_REPLAYED` after calling `sessions.revoke` on the one row.
   `POST /refresh` stages `session.refresh_replayed`, **commits**, and only then
   raises its 401. The commit-before-raise order is load-bearing: raising first
   would unwind the request's session and roll the revoke and the audit row back
   together. The row carries the sid as its target and `{"client_ip"}` as its
   detail; neither a token nor a hash is ever written or logged.

5. **Only that session row is revoked, never the user's other devices.**
   Revoking every session of the owner is the aggressive reading of reuse
   detection, and it hands anyone who obtains one stale token a way to sign the
   victim out everywhere. The session that presented the old token is the one
   whose refresh chain was broken, so it is the one that is killed.

6. **A hash older than one generation is a side-effect-free 401.** This is the
   anti-spray property: an unknown or garbage token, or a token older than the
   single generation the row remembers, returns `ROTATE_STALE` and changes no
   row. Otherwise anyone could spray guesses and revoke sessions without ever
   holding a valid token. `POST /refresh` deliberately writes no row on that
   path either, because nothing happened.

7. **A normal refresh writes no audit row.** The same session minting a fresh
   token is not an event; a row per refresh would flood the log with the
   absence of a decision. Only `ROTATE_GRACED` and `ROTATE_REPLAYED` emit. The
   route is therefore in `audit.ROUTE_ACTIONS`, not in `EXEMPT_ROUTES`, and the
   two actions are the only ones it may write.

8. **No revocation epoch, no short-TTL cache and no token blacklist were
   added.** `auth.require_auth` already reads the session row on every request
   and `sessions.is_live` already tests `revoked_at is None`, so revocation is
   already zero-latency. An epoch or a cache would either add latency or create
   a second source of truth for a fact that is already read from the row, and a
   blacklist would be a third place to forget to consult. The existing
   behaviour is pinned by regression tests instead of reimplemented.

9. **The four session routes are ownership-scoped, not a second permission
   mechanism.** `GET /me/sessions` and `DELETE /me/sessions/{session_id}` are
   READ, because a viewer must be able to see and revoke their own devices. The
   handler compares the loaded row's `user_id` with the caller's and answers
   **404**, never 403, for a foreign id: a 403 would tell the caller that
   somebody else's session exists. `GET /users/{user_id}/sessions` and
   `DELETE /sessions/{session_id}` are ADMIN, like every other
   user-administration route.

10. **The session list never serialises a hash.** `SessionOut` has exactly the
    fields the client renders (`id`, `username`, `kind`, `device`, `user_agent`,
    `client_ip`, `created_at`, `last_used_at`, `current`) and no field for
    either hash. The boundary is the model, not a handler that remembers to
    strip fields.

11. **Dead rows are swept unconditionally.** `session_prune.run_forever` runs a
    daemon thread from `main.lifespan` without an env gate, because there is no
    deployment that wants expired and long-revoked sessions kept. A tick deletes
    only rows whose refresh token has expired (their access token is necessarily
    dead too) or that were revoked longer than 24 hours ago, and writes one
    count-only `session.prune` row in the same transaction - and only when it
    deleted something. No env var was added, so the deploy manifests stay put.

## Consequences

The two-tab race stops forcing a sign-in as long as the second presentation
arrives within one minute, and the client no longer has to be told about a
token it no longer holds. A stolen token is no longer useful after its first
rotation plus sixty seconds, and a replay is recorded as a fact with an actor
and a session id. Revoking a device from a browser works for every role,
including a viewer revoking its own laptop.

Costs paid deliberately:

- **One more generation of a secret's hash exists at rest.** Migration 011 keeps
  a superseded sha256 for up to the grace window (and until the next rotation
  overwrites it). It cannot be replayed after the window, but it is more
  material than a single current hash.
- **The audit log gains five actions and two of them come from a public
  route.** `POST /refresh` needs no session to be called, so its grace and
  replay rows are the one audited surface reachable without a bearer token.
  They carry only a sid, a client ip and the actor copied from the row.
- **A background thread is now always running.** It is a daemon, its stop event
  is held by the lifespan and set on shutdown, and it ticks hourly after a
  five-minute start delay, so the cost is one small DELETE per hour.
- **`ROUTE_ACTIONS` and `ACTIONS` grew.** `POST /refresh` moves out of
  `EXEMPT_ROUTES`, so the log's coverage sentence has to say why a normal
  refresh is silent.
- **`POST /logout` now also kills a session through a one-generation-stale
  token.** Logout resolves the presented hash through
  `sessions.find_by_presented_hash` so signing out with the token a tab woke up
  with still works, which means the previous hash reaches the same revoke as
  the replay path does - without a row, because `/logout` stays exempt. That is
  not a new lever: the same token already revokes the same single row via
  `/refresh`, and the blast radius is one session row by design.

Residual risks, stated plainly:

- **The hibernating-tab case is bounded, not eliminated.** A tab that sleeps
  across a rotation and wakes after the 60-second window arrives with a
  one-generation-stale token, is treated as a replay, and revokes the session it
  shares with the other tabs in that browser. The next request from those tabs
  is a 401 and the user signs in again. That is the intended trade: an attacker
  holding the same token gets exactly one outcome, and an honest tab has sixty
  seconds and one reload to use it.
- **A race between two tabs is still a race.** Both may present the same token
  in the same instant; the guarded UPDATE makes exactly one the winner, and the
  loser is the grace path only if it arrives inside the window. Outside it, the
  loser is the replay path.
- **The grace path does not extend the refresh session.** `refresh_expires_at`
  is absolute from login and untouched by rotation, so a stolen token cannot
  keep a session alive past its 30-day ceiling by refreshing forever.

## Alternatives considered

- **A longer grace window (hours, or "until the next rotation").** Rejected: it
  widens the interval in which a stolen token is interchangeable with the
  victim's, and an honest client does not need it.
- **Revoke every session of the user on a replay.** Rejected: it turns one stale
  token into a denial-of-service lever against the owner. Reuse detection is
  about killing the broken refresh chain, which is one row.
- **401 for any hash older than the current one, with no history at all.** The
  pre-ticket behaviour. Rejected because it forces a sign-in for the ordinary
  two-tab and lost-response cases.
- **A revocation epoch, a short-TTL cache or a token blacklist.** Rejected as
  redundant: `auth.require_auth` already re-reads the row and `is_live` already
  checks `revoked_at`, so these would add latency or a second source of truth
  for a fact already read on every request. The zero-latency behaviour is now
  pinned by a regression test rather than assumed.
- **Per-device sessions instead of one row per browser session.** A larger
  change to login, the client and the UI. The grace window solves the reported
  race without a token model change.
- **An environment variable for the grace window or the sweep cadence.**
  Rejected: both are correctness details, and an env var would force matching
  entries in `docker-compose.deploy.yml`, `.env.example` and the configuration
  reference for no operator benefit.

## Rollback

The code change is revertible without a schema rollback: migration 011 only adds
two nullable columns and one index, so an older build ignores them and keeps
reading `refresh_token_hash`. Reverting the ticket restores the single-use
rotation behaviour (an old token is a 401) and stops the sweep thread; the
columns and the background thread's rows are harmless leftovers. If the sweep
itself misbehaves, setting its start delay high or reverting `main.lifespan` to
not start it stops the deletes without touching authentication. Deleting rows
cannot undo a revoke, so the rollback path for authentication is the code revert,
not an UPDATE.

## Verification

- `tests/test_session_rotation.py` drives the real `POST /refresh` through
  `TestClient(main.app)`: the interleaved double rotation is graced once and
  audited once, the same token replayed again is a side-effect-free 401, a token
  aged one second past `REFRESH_GRACE_SECONDS` revokes only its own session and
  leaves the other session live and working, and an unknown hash changes no row.
- `tests/test_sessions_api.py` pins the exact `SessionOut` key set (no key
  contains `hash`), the 404-not-403 foreign-id rule, the 503 set when auth is
  disabled, and that revoking a session kills both the access token and an
  outstanding `?sig=` file grant on the next request.
- `tests/test_audit_log.py` sweeps every audited route and asserts the grace row;
  its dedicated replay test asserts the 401, the revoke and the
  `session.refresh_replayed` row are all present afterwards.
- `tests/test_session_prune.py` pins what a tick deletes, the count-only
  `system` row and that the thread waits on `stop.wait`, never `time.sleep`.
- `tests/test_migration_011.py` pins the ledger name, the add-only column set,
  the non-unique index and that re-applying 011 (or upgrading a v10 database)
  preserves existing session rows.
- `tests/test_permissions_matrix.py` pins the 82-route matrix and that the two
  admin session routes deny viewer and editor.

## Superseding conditions

This ADR is superseded if any of the following becomes true:

- the grace window is made configurable, or its length changes materially;
- replay handling stops revoking the session, or starts revoking more than the
  one row;
- a revocation epoch, cache or token blacklist is introduced, which would make
  the "no second source of truth" decision in this ADR false;
- sessions become per-device rather than one row per browser session;
- the session routes stop answering 404 for a foreign id (for example by
  exposing ownership or returning 403);
- the sweep's retention window or its unconditional start changes.
