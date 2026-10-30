# ADR 0008: TOTP two-factor: enrolment, per-session verification and the admin policy

**Status:** Accepted

**Accepted:** 2026-10-30

**Implementation:** ticket `Mf-lg02`.

## Context

Every way into Curiarium was single-factor. A local account is a `users` row
and one password hash; an SSO account is an `oidc_identities` binding, and
whatever the IdP did to authenticate that person is invisible here; the
break-glass environment admin is one `AUTH_USERNAME`/`AUTH_PASSWORD` pair. The
threat this ticket answers is not the forgotten password, it is the *reused*
one: a password lifted from another site, or one typed into a phished form, is
enough to open an admin session, and from there to create users, purge the
trash, rewrite the storage template and delete snapshots. The second factor is
worth exactly as much as the distance between "the attacker has the password"
and "the attacker has the phone".

Four constraints shaped the design:

* **One self-hosted process, one SQLite file.** There is no factor service to
  call, no Redis to share state with, and no second worker that could hold half
  of a pending enrolment. Anything that needs a shared store - a pending-seed
  table with its own sweeper, a queue, a push provider - would add infrastructure
  this product does not have. The one exception already in the codebase, the
  in-process OIDC state dict, is the same shape: it is correct only because the
  API runs one uvicorn process (ADR 0006).
* **A lost phone must not lose the account.** Any factor without a recovery path
  turns a dropped handset into a support incident, and in a single-operator
  deployment there is nobody to call.
* **No lockout is acceptable at switch-on time.** The policy is admin-wide, so
  the mistake that matters is not "a user cannot sign in", it is "every admin
  route now refuses the only admin". A control that can be made unsatisfiable by
  the act of enabling it is a self-inflicted outage.
* **No new deployment surface.** Adding an environment variable means editing
  `docker-compose.deploy.yml`, `.env.example`, `README.md` and the configuration
  reference, and keeping them in step through two guards
  (`test_deploy_manifest_env.py`, `test_auth_docs.py`); worse, an environment
  variable cannot be toggled by an audited admin route, so the policy would
  change without an audit row. It is an appconfig value instead (see
  CONFIGURATION.md).

The ticket also had to decide what a *verified* factor means for a session, not
only for an account. That is the part with the most ways to get it wrong, and it
is why the marker in this design lives on `sessions`, not on `users`.

## Decision

1. **TOTP, RFC 6238, HMAC-SHA1, 6 digits, 30-second steps, a 160-bit seed.**
   RFC 4226 §4 recommends at least 160 bits and every authenticator app on the
   planet implements SHA1 by default, so interoperability wins over the marginal
   strength of SHA256 here. There is no Python OTP dependency: `hmac`,
   `hashlib`, `struct`, `base64` and `secrets` are enough, and the module is
   pinned against the RFC 4226 Appendix D vectors so "no dependency" does not
   mean "no reference implementation".

2. **The seed is stored as AES-256-GCM ciphertext under an `AUTH_SECRET`
   subkey, and it cannot be hashed.** This is the one place in the product where
   a stored secret must be *recoverable*: HOTP feeds the raw seed to HMAC, so a
   digest would be useless for verifying a code, and there is no way to design
   around that - the verifier needs the seed. `mfa.seed_key()` derives a
   domain-separated key (`curiarium/mfa-seed/v1`) exactly the way
   `auth.file_grant_key()` derives the file-grant key, and the nonce is fresh per
   encryption, so the same seed never produces the same blob twice. The
   consequence is that a database dump alone cannot mint codes; an attacker
   needs the environment secret as well. A rotated `AUTH_SECRET` makes every
   stored seed undecryptable, and `decrypt_seed` reports that as "no seed here"
   (`None`) rather than raising through a login request - see the Consequences.

3. **Recovery codes are HMAC-peppered, never bare sha256, and each is its own
   row.** Ten codes, ten characters from a 32-symbol alphabet with `I`, `L`,
   `O`, `0` and `1` removed, displayed `XXXXX-XXXXX`: 50 bits, about 1.1e15
   possibilities. Fifty bits is short enough that a bare sha256 is offline-
   crackable from a dump by brute force, so the digest is `HMAC-SHA256` under a
   second subkey (`curiarium/mfa-recovery/v1`) derived from `AUTH_SECRET`. The
   pepper is not in the database, which is what makes the dump worthless: without
   the key there is no digest an attacker can test a guess against.

4. **A recovery code is a row so single use is an atomic guarded UPDATE.** A
   JSON blob on `users` would have to be read, edited and written back, and two
   concurrent requests presenting the same code could both read the pre-use
   blob and both write a post-use one: a lost update, i.e. a code used twice.
   `mfa_recovery_codes` has one row per code, and consumption is
   `UPDATE ... SET used_at = ? WHERE user_id = ? AND code_hmac = ? AND used_at
   IS NULL` - exactly one request can see `rowcount == 1`. The unique
   `(user_id, code_hmac)` index keeps the set a set, and the plaintext codes are
   returned exactly once, from `POST /mfa/confirm` or
   `POST /mfa/recovery-codes`, and never stored or returned again.

5. **The acceptance window is ±1 step, and the matched counter is the one
   burned.** `mfa.matching_step` tries offsets `-1, 0, +1` in constant time,
   which absorbs the ordinary thirty seconds of drift between a phone's clock
   and the server's. The counter it returns is the one the submitted code is
   *for* (`step + offset`), never the wall-clock bucket: a code for counter `C`
   matches at wall steps `C - 1`, `C` and `C + 1`, and every one of those
   presentations returns `C`. The caller burns exactly that value in
   `users.totp_last_step`, through the guarded
   `UPDATE ... WHERE totp_last_step IS NULL OR totp_last_step < C`. The first
   presentation of a code therefore burns `C`, and a second presentation of the
   *same* code is refused in every bucket, while a different, on-time code for
   `C + 1` remains usable. The column is monotone, so a concurrent pair cannot
   both win, and the ±1 window is tolerance for clock error only, never a
   replay window.

6. **`sessions.mfa_verified_at` is per session, not per user.** Two-factor is
   proven *for a login*, so a session born from a password check that did not
   complete the challenge, or from an OIDC exchange, must start without the
   marker and can only be upgraded by proving a factor. A per-user flag ("this
   account has a seed", or "this account has ever verified") would bless two
   sessions it must not: a session opened before the account enrolled - the
   session doing the enrolling was not MFA-verified when it started, and the
   user may have enabled the policy later - and a stolen session, which would
   inherit the owner's earlier verification without ever presenting a code. The
   policy therefore reads the session row, and `sessions.create` accepts
   `mfa_verified_at` so `/mfa/verify` can open a session that is already `mfa_ok`
   in the same transaction.

7. **`/login` returns a challenge instead of a token pair when the account is
   enrolled, and the challenge is its own credential.** `auth.create_mfa_challenge`
   signs `{sub, typ: "mfa", username, iat, exp}` with a third subkey
   (`curiarium/mfa-challenge/v1`) for five minutes. The subkey is the isolation:
   `decode_access_token` verifies with `AUTH_SECRET` itself, so a challenge can
   never verify as an access token or as a file grant, whatever its claims say,
   and `require_auth` therefore needs no extra check. `auth.login` is untouched:
   it opens sessions, and the challenge exists precisely because no session
   should exist yet. Nothing is audited on the challenge path - no session came
   into existence, and `mfa.verify.succeeded` is the row that records the
   completed login.

8. **`POST /mfa/verify` is public because it runs before a session exists, and
   it is throttled on its own bucket.** It trades the challenge for the real
   token pair, so it cannot require a bearer token. Guesses are counted by a
   second `LoginThrottle` instance (`login_throttle.mfa_limiter`) keyed on the
   challenge's `sub`; sharing the password limiter would let a spray of wrong
   TOTP codes lock the password login out, and vice versa, which is a
   denial-of-service lever rather than a defence. An unparseable or expired
   challenge is a 400 (a bad request); a valid challenge with a wrong code is a
   401.

9. **A completed second factor is one audit row written in the new session's
   transaction, and a failed one is committed before the 401.**
   `mfa.verify.succeeded` (or `mfa.recovery_code.used` when a recovery code was
   spent) commits with the session and its token pair, so the login and its
   record are one fact. A failure stages `mfa.verify.failed`, **commits**, and
   only then raises: `HTTPException` unwinds the request's session, so raising
   first would roll the row back with the failed attempt and leave no trace -
   the same commit-before-raise order as the `/refresh` replay path in ADR 0007.
   No secret, code or digest ever reaches `target` or `detail`; the detail
   carries the method, a frozen reason and the client IP.

10. **SSO users skip the login TOTP step but are not exempt from the admin
    policy, and `POST /mfa/step-up` is how a session acquires the marker without
    a password.** The challenge is minted only by `/login`, after a local
    password check, and `auth.mfa_required(user)` demands both a stored seed and
    a `password_hash`; an OIDC exchange therefore opens its session directly and
    that row is born with `mfa_verified_at = NULL`. `enforce_admin_mfa` reads the
    session marker, not the login kind, so an OIDC admin session is refused on
    admin routes while the policy is on - the IdP authenticated a person, it did
    not prove a second factor to *this* application. `POST /mfa/step-up` (READ,
    so any authenticated caller may use it) checks a code against the caller's
    own seed and writes `mfa_verified_at` on the current session; it deliberately
    does not repeat the password re-check that enrolment carries, because the
    factor is the proof. Without it, the only way to upgrade a session would be
    to sign out and back in through `/login` with a password - a route that does
    not exist for an account whose `password_hash` is NULL. Step-up is therefore
    what keeps the policy from being an unconditional lockout for every session
    that did not come through the password challenge. It is not a substitute for
    enrolment, and the residual case where an account can do neither is stated
    in the Consequences.

11. **Break-glass is exempt, as an explicit `context.kind ==
    sessions.BREAK_GLASS_KIND` check, not a fabricated marker.**
    `permissions.enforce_admin_mfa` returns for break-glass before it reads the
    policy at all. The break-glass principal has `user_id = None`, so there is
    nowhere to store a seed and no row to hang a marker on; gating the bootstrap
    path on a secret that needs a user row it does not have is circular, and the
    first real `POST /users` already revokes every break-glass session. Exempting
    it by kind is honest about why; writing a fake `mfa_verified_at` somewhere
    would say the bootstrap admin had proved a factor it never had.

12. **A not-yet-verified admin is a 403 with one message, plus a marker for the
    not-yet-enrolled case, and the self-service routes stay reachable.** The
    detail is `"Multi-factor authentication required"` for both "this session
    has not stepped up" and "this account has no factor", and the second case
    adds `X-MFA-Enrolment-Required: 1` so the client can offer the enrol-now
    panel instead of a dead end. This is not a half-session: every `/mfa*` route
    is READ, not ADMIN, so the eight self-service routes remain callable from the
    same 403-ed session - which is exactly what makes the header actionable. The
    policy is read once per admin request (one primary-key SELECT) and lives in
    `permissions.py` beside the rank check, so authorization still has exactly
    one choke point; a viewer still gets the plain `DENY_DETAIL[ADMIN]`.

13. **No lockout is reachable through the policy switch itself, in code.**
    `POST /settings/mfa` refuses to set `require_admin = true` with a 409 unless
    the *calling session* is already `mfa_ok` and the caller's account is
    enrolled, so the one admin who flips the switch is provably able to satisfy
    it afterwards. `DELETE /mfa` then refuses an admin's own disable with a 409
    while the policy is on, so the factor the policy depends on cannot be removed
    from underneath it; turning the policy off is the way out, and that call is
    itself an admin route, so it needs an `mfa_ok` session - the same
    precondition the enable guard demanded, which the enrolled admin can
    re-establish from `/login` at any time. Both are code, not prose: they are
    the difference between "we think this is safe" and "this state is not
    reachable".

14. **Enrolment is sudo-gated and refuses an already-enrolled account.**
    `POST /mfa/enrol`, `/mfa/confirm`, `DELETE /mfa` and
    `POST /mfa/recovery-codes` all carry the caller's password and re-check it
    (`accounts.verify_password`) before doing anything; a wrong password is a
    403. A session token is what a hijacked browser already has, so a factor that
    could be planted or swapped with nothing but a session would be a takeover
    vector, not a second factor: while an account is enrolled, enrolment is a
    409, so a stolen session cannot add a second seed or replace the existing
    one. An SSO-only account (`password_hash IS NULL`) is refused with a 409 -
    its credential lives at the IdP, so there is no local password to confirm and
    the route will not guess.

15. **`POST /settings/mfa` writes its audit row unconditionally, even when the
    value is unchanged.** The row is an explicit policy assertion ("the admin
    says admins must use two-factor"), not a record of a column that happened to
    change, and the audit sweep needs a row for the route; `POST /login` has the
    same precedent. The value is stored through `settings_service` in the same
    transaction as the row.

16. **The QR code is rendered client-side from the `otpauth://` URI with
    `qrcode-generator`, never by a third-party service.** A QR image fetched
    from an external renderer is the seed in a URL parameter, leaving the
    deployment's boundary and landing in somebody's access log; that is a
    straightforward exfiltration of the factor being enrolled. `qrcode-generator`
    is MIT, has zero transitive dependencies, and draws an `<svg>` in the browser
    from the URI the API already returned. The URI is the same one an
    authenticator app would parse, so a user who cannot scan can type the secret.

17. **The seed is never logged, never returned after enrolment and never put in
    an audit `detail`.** `POST /mfa/enrol` returns the candidate secret once and
    persists nothing; `/mfa/confirm` returns the recovery codes once; every
    response carrying a secret or a code sets `Cache-Control: no-store`. The
    audit rows name the stage, the method and the counts, never the material.

## Consequences

An admin session now costs a password *and* a code while the policy is on, and
the policy cannot be switched on by an admin who could not satisfy it, nor have
the factor removed from under it while it is on.

Costs paid deliberately:

- **An `AUTH_SECRET` that is also the seed-encryption key means one rotation
  bricks every enrolled seed.** This is documented rather than solved: the same
  rotation already kills every session and every outstanding file grant, and the
  remedy for both is the same re-enrolment. A separate `MFA_SECRET` would be one
  more secret to back up and rotate, and a *fatal* one to lose - losing it would
  lose every seed silently. Weaker-but-obvious beats stronger-and-forgotten.
- **A database dump plus the environment secret is a second factor.** The seed
  is recoverable by design (point 2), so an attacker who has both the SQLite file
  and `AUTH_SECRET` can mint codes. That is the same blast radius as an attacker
  who has `AUTH_SECRET` alone - they can mint access tokens - so encryption does
  not widen the exposure; it narrows the dump-only case to nothing.
- **Recovery codes are 50 bits.** That is enough with the pepper (a dump alone
  cannot be brute-forced) and short enough to type from paper. A dump plus
  `AUTH_SECRET` can crack them, but that combination can already mint codes.
- **Four new nullable columns and one table.** `users.totp_secret`,
  `users.totp_enrolled_at`, `users.totp_last_step`, `sessions.mfa_verified_at`
  and `mfa_recovery_codes` (migration 012). All additive; an older build ignores
  them.
- **One more read on every admin request while the policy is on.** It is one
  primary-key SELECT for the policy plus the session and user rows the request
  already loads; nothing is cached, so an admin who is disabled, demoted or
  stepped down loses the effect on the next request.

Residual risks, stated plainly:

- **An SSO-only administrator cannot enrol a seed.** `POST /mfa/enrol` refuses
  an account with no local password because the IdP owns its credential, and
  there is no route that sets one. If the policy is switched on while such an
  account exists, that account's admin routes answer 403 with the enrolment
  header and neither enrolment nor step-up can fix it; another enrolled admin
  has to turn the policy off. The alternative - trusting an IdP claim as the
  second factor - would be a claim this application cannot verify, so the lockout
  is the smaller problem, and the enable guard at least stops the *enabling*
  admin from being the locked-out one.
- **The policy is only as strong as the enrolment it requires.** Nothing forces
  every admin to enrol; an admin who has not enrolled is refused admin access
  while the policy is on, but can still sign in, read the library and enrol
  afterwards. That is the intended "enrol now" path, not a hole.
- **A TOTP code is phishable in real time.** A code typed into an attacker's
  page is a code the attacker can submit within its 30-second step. Single use
  bounds it to one login; it does not make the factor phishing-proof. Hardware
  keys and passkeys are the answer to that, and they are not this ticket.
- **`totp_last_step` is per user, not per session.** Two sessions of the same
  account cannot both spend the same step - which is the point - so a user who
  signs in on two devices inside one 30-second bucket will need the code once,
  and the second device needs the next code or a step-up after the bucket rolls.
  This is a mild usability cost for a hard replay bound.

## Alternatives considered

- **A hash of the seed instead of encryption.** Impossible rather than rejected:
  HOTP feeds the seed to HMAC, so the verifier needs the plaintext. The only
  choice is plaintext-at-rest or recoverable ciphertext, and a database dump is
  the case the factor is supposed to survive.
- **A bare sha256 for recovery codes.** Rejected: 50 bits is offline-crackable
  from a dump once an attacker has a fast hash to attack, and peppering costs one
  HMAC and one subkey.
- **Recovery codes in a JSON column on `users`.** Rejected: single use would be a
  read-modify-write that two requests can interleave, and the whole point of a
  recovery code is that it works exactly once, including on a bad day.
- **A per-user `mfa_verified` flag.** Rejected: it would bless the session that
  enrolled before proving anything and any stolen session afterwards (point 6).
- **Staging the seed in a pending-enrolment table between `enrol` and
  `confirm`.** Rejected: it is exactly the shared state this deployment cannot
  maintain well (no worker sharing, a sweeper to write), and the confirm request
  already carries the candidate secret back, so the client can hold it for the
  thirty seconds it takes to scan a QR code.
- **A wider skew window (±2 or more steps).** Rejected: every extra step widens
  the set of wall-clock buckets in which a code for one counter is accepted,
  and one step is the drift a phone that syncs its clock actually has. It stays
  replay-free only because the *matched* counter is burned (point 5), so a
  wider window buys a larger guess surface and no real clock-error benefit.
- **Exempting OIDC sessions from the policy.** Rejected: a stolen IdP session
  would then reach every admin route, which is precisely the case this ticket
  exists to close. Step-up is the smaller cost.
- **Trusting an IdP claim (an `amr`/`acr` value, or a group) as the second
  factor.** Rejected: this application cannot verify what the IdP actually did,
  and a claim an operator can misconfigure is not a control. The local code is
  the proof.
- **An environment variable for the policy.** Rejected: it needs matching
  entries in the manifests, `.env.example`, `README.md` and this documentation,
  cannot be toggled by an audited admin route, and would let a restart change an
  admin's access with no record. It is an appconfig value
  (`mfa_require_admin`, default `false`) behind `POST /settings/mfa`.
- **A third-party QR rendering service.** Rejected: it puts the seed in a URL
  request to somebody else's server. `qrcode-generator` renders the same QR in
  the browser with no network call.

## Rollback

The code is revertible without a schema rollback. Migration 012 is additive -
three nullable `users` columns, one nullable `sessions` column, and one new
table with two indexes - so an older build ignores every object it added and
keeps working; re-applying 012 to a database that already has them is harmless,
like 004-011. Reverting the ticket removes the eight routes, the nine audit
actions, the policy check and the challenge branch in `/login`; existing
`mfa_recovery_codes` rows and stored seeds become inert data, and a later
re-apply can still decrypt them if `AUTH_SECRET` is unchanged.

The one operational note: turn the policy **off** before reverting the build if
admins are enrolled and the policy is on. An older build has no policy and no
check, so it cannot refuse anybody - the 403s disappear with the code - but the
`users.totp_secret` values remain, and re-applying the ticket picks the policy
value back up from appconfig. There is no data migration to undo and no UPDATE
that can grant back anything a revoke destroyed, so the rollback path for
authentication is the code revert.

## Verification

- `tests/test_mfa.py` pins the RFC 4226/6238 vectors, an
  `encrypt_seed`/`decrypt_seed` round trip and the wrong-key `None` (the
  `AUTH_SECRET`-rotation case), that two encryptions of one seed differ (fresh
  nonce), that `hash_recovery_code` is not the bare sha256 and changes with
  `AUTH_SECRET`, the guarded single-use UPDATE for both the step and a recovery
  code (including a two-thread race), the `-1/0/+1` acceptance and `-2/+2`
  rejection, and that a `step - 1` code burns `step - 1` while the on-time
  `step` code stays usable, plus a cross-bucket replay test showing the same
  code is refused in the following bucket.
- `tests/test_mfa_api.py` drives the whole flow through `TestClient(main.app)`:
  enrol, confirm, ten codes, `mfa_required`, verify, tokens, disable; an admin
  route 200 before the policy, 403 with `"Multi-factor authentication required"`
  after, 200 again after step-up; the enable 409 while the session is not
  `mfa_ok`; the disable 409 for an admin while the policy is on; the 503 set with
  auth disabled; that break-glass still logs in with the policy on; that a
  hijacked session cannot swap a factor (409 while enrolled, 403 on a wrong
  password); and `Cache-Control: no-store` on every response carrying a secret.
- `tests/test_migration_012.py` pins the ledger name, the five columns and the
  table with its two indexes, that re-applying 012 is idempotent, and that a v11
  database upgrades without touching existing rows.
- `tests/test_permissions_matrix.py` sweeps all eight new routes for the 90-route
  matrix (9 public / 33 read / 19 contribute / 13 write / 16 admin — the `write`
  bucket was split by `Mf-01f0`) and for the 503 set when auth
  is disabled or the mode refuses password sign-in (`AUTH_MODE=oidc`).
- `tests/test_audit_log.py` sweeps the seven audited routes with throwaway users
  (never the fixture admin, so `/login` never flips to a challenge mid-sweep) and
  has a dedicated 401 test asserting the `mfa.verify.failed` row survives the
  rejection.
- `tests/test_snapshots.py` pins `len(audit.ACTIONS) == 47`,
  `len(audit.ROUTE_ACTIONS) == 40` and the route-coverage sentence in
  `docs/AUDIT.md`.
- The web side is covered by `src/ui/settings/MfaQrCode.test.tsx` (an `<svg>` is
  built from the URI and no network call is made), `MfaSection.test.tsx`,
  `src/lib/api.mfa.test.ts`, and the updated `Login.test.tsx` /
  `App.test.tsx` / `App.role.test.tsx` / `Settings.test.tsx` /
  `SettingsRootMenu.test.tsx`.

## Superseding conditions

This ADR is superseded if any of the following becomes true:

- the seed stops being recoverable-ciphertext under `AUTH_SECRET` (a key
  management service, an HSM, or a deliberate plaintext-at-rest decision);
- `AUTH_SECRET` rotation acquires a re-encryption path, which would make the
  "rotation bricks every seed" consequence false;
- the verification marker moves from the session to the account, or the policy
  starts reading a per-user fact;
- the skew window widens, or the burned step stops being the counter
  `matching_step` returned;
- break-glass stops being exempt by `kind`, or is given a user row and becomes
  enrolable;
- recovery codes move out of their per-row table, or lose the HMAC pepper;
- the policy is turned into an environment variable or otherwise stops being an
  audited admin action;
- QR rendering moves off the client, or the seed leaves the deployment boundary
  to be rendered;
- an IdP claim becomes the accepted second factor for an SSO admin.
