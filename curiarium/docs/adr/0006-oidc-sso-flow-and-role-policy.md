# ADR 0006: OIDC/SSO login with the Authorization Code flow, PKCE, and a claim-to-role policy

**Status:** Accepted

**Accepted:** 2026-10-30

**Implementation:** ticket `Mf-4c24`.

## Context

Until now a deployment had exactly two ways in, and both were local: a password
account in `users`, or the `AUTH_USERNAME`/`AUTH_PASSWORD` environment admin,
which is break-glass only and stops authenticating the moment a real account
exists. The consequence is stated in
[`docs/PERMISSIONS.md`](../../../docs/PERMISSIONS.md): the break-glass path is a
single account, `POST /login` is throttled per submitted username, and an
operator who wants their identity provider to be the source of truth had no
option at all. Multi-user accounts landed in `M3-*`; SSO was left as "owned by
another ticket" and that ticket is this one.

What an external identity provider brings that the local model does not have is
a **claim set chosen by somebody else**. Everything hard about this decision is
that sentence. A claim is attacker-influenced input on the one code path that
mints a session, so every claim that could raise a privilege level is a place
where a misconfigured IdP, a compromised tenant, a group named `admin` for
unrelated reasons, or an operator typo could hand out administrator access to
this deployment's library, audit log and user table.

Verified facts at the time of this decision:

- The authorization contract is `permissions.ROUTE_PERMISSIONS`, enforced by
  dependency declaration and checked at boot by
  `permissions.assert_routes_classified`. Ranks are `public` < `read` < `write`
  < `admin` (`permissions.LEVEL_RANK`), and `accounts.DEFAULT_ROLE` is
  `viewer`, so an account created without an explicit role is read-only.
- `users.role` is re-read on every request (`sessions.role_for`), never trusted
  from the token, so **the stored row is the authority** for what an account may
  do.
- The audit log is append-only with a fixed taxonomy (`audit.ACTIONS`) and a
  coverage guard (`audit.assert_audit_coverage`) that refuses to boot when a
  mutating route is neither audited nor exempt with a reason. A new login path
  with no action would fail that boot.
- The API's outbound HTTP client is `httpx` (`api/safe_http` covers the import
  paths); an `httpx` exception embeds the request URL and, for a JSON error
  body, the response text. Discovery, JWKS and token responses are exactly the
  responses that carry a client secret and a signed `id_token`.
- Nothing in the codebase stores a per-provider identity: `users` has a unique
  `username` and a `password_hash`, and `UserSession` has a `kind` column
  (`sessions.PASSWORD_KIND`, `sessions.BREAK_GLASS_KIND`). There is no row that
  says "this account at this issuer is that user here".

## Decision

1. **SSO is an opt-in second front door, not a replacement for the first.**
   `config.OIDC_ENABLED` (default `False`) is the single master switch. With it
   off, `api/routers/oidc.py` is still included by `main.API_ROUTERS` — so the
   four routes exist and the matrices stay total — but every one of them answers
   503, exactly as `/login`, `/refresh` and `/logout` do when `AUTH_ENABLED` is
   false. Local password login, the break-glass environment admin, the login
   throttle in `api/login_throttle.py` and the signed file-grant path
   (`auth.require_auth_or_file_grant`) are untouched by this ticket and keep
   working with SSO on or off.

2. **The flow is Authorization Code with PKCE, server-side, and the code never
   reaches the browser.** `GET /auth/oidc/start` mints a `state`, a `nonce` and
   a PKCE `code_verifier` in `api/oidc.py`, stores them in a pending-state dict
   keyed by `state`, and answers a 302 to the IdP's `authorization_endpoint`
   with `response_type=code`, `client_id`, `redirect_uri`, `scope`
   (`OIDC_SCOPES`, default `openid profile email`), `state`, `nonce`,
   `code_challenge` and `code_challenge_method=S256`. `GET /auth/oidc/callback`
   consumes that state entry once, exchanges the code at the token endpoint with
   the verifier over the API's own outbound client, and then parks a **handoff
   code** — not a session — for the browser. PKCE means an intercepted
   authorization code is useless without the verifier, which never leaves the
   API process.

3. **Identity binds on exactly one thing: a persisted `(issuer, subject)` row.**
   Migration 10 adds `oidc_identities` with a unique `(issuer, subject)`
   constraint, and `api/oidc.py` resolves an SSO login by that pair and by
   nothing else. Binding by username or by email is refused on purpose: both are
   attacker-claimable at a misconfigured or malicious IdP, and either would be
   an account-takeover path onto an existing local account. A verified
   `preferred_username` or `email` is display material at most — it is never
   looked up, and it never selects a row.

4. **Claims can produce a `viewer`, and at most an `editor`.**
   A newly provisioned SSO account is created through `accounts.create_sso_user`
   with `role=accounts.DEFAULT_ROLE` (`viewer`) and `password_hash=None`, so it
   can never be replayed against `POST /login` and it has no local credential to
   steal. The single escalation is `editor`: a principal whose groups (the claim
   named by `OIDC_GROUPS_CLAIM`, default `groups`) intersect
   `OIDC_EDITOR_GROUPS` is provisioned as `editor`. Nothing else about a claim
   set changes a role.

   **Amended (2026-10-30, Mf-sg2t):** the role a newly provisioned SSO account
   gets is now `oidc.default_role()` — `OIDC_DEFAULT_ROLE`, default `viewer`, whose
   accepted set is **derived** as every role in `accounts.ROLES` except `admin`
   (`oidc.claim_grantable_roles()`), with `admin` refused at boot exactly like
   `OIDC_ADMIN_GROUPS` — while an `editor` group match still wins over that
   default. This **supersedes the provisioned-role enumerations elsewhere in this
   record**: Decision 7 ("an OIDC-provisioned user is a `viewer` or an `editor`")
   and the threat-table row about first-provisioning lockout are stale in letter
   only, because both arguments are about which roles a claim can reach and
   neither depends on the default being `viewer`. The *Superseding conditions*
   clause that sends "a different default" to a new ADR is read as the
   claim-mapping default fixed in this decision, not as this operator knob: no
   claim gained a role it could not reach before, which is why this is a dated
   amendment rather than a new record.

5. **`admin` is structurally unreachable from claims, and a stored role is never
   rewritten.** `OIDC_ADMIN_GROUPS` exists only to be refused: a non-empty value
   fails the boot validator, so a deployment cannot ask for claim-based admin
   even by accident. On re-login, the role of an *existing* account is read from
   `users.role` and left exactly as it is — a claim cannot promote a `viewer` to
   `editor` after the fact, cannot demote an `editor`, and cannot touch an
   `admin`. Promotion is `PATCH /users/{user_id}` by an admin, through the one
   path that already has a last-admin invariant on it. The reason is the audit
   trail: a role that a group membership can change is a role with no history
   and no human in the loop.

6. **The two allow-lists compose with AND, never OR.** `OIDC_ALLOWED_GROUPS` and
   `OIDC_ALLOWED_DOMAINS` are CSV allow-lists. When both are configured a
   principal must satisfy **both** — a group match *and* a verified email
   domain — to be let in. A security control composes restrictively: OR would
   mean that an operator who sets a domain list "as well" has silently widened
   the gate that the group list was narrowing, which is the fail-open direction.
   An empty list means "no restriction from this axis", and a boot with **both**
   empty is refused: "no restriction at all" is not a configuration this ticket
   will start.

7. **Only an enabled admin can bootstrap an SSO account, and there is no
   loosening of the break-glass rule to make that easier.**
   `POST /auth/oidc/exchange` refuses to provision a new account unless at least
   one enabled `admin` row already exists in `users`, and it says so with
   `sso_error=no_admin_bootstrap`. The reason is the last-admin invariant: an
   OIDC-provisioned user is a `viewer` or an `editor`, never an `admin`, so a
   deployment that lets its first account be an SSO user would have zero admins
   and no path to `PATCH /users/{user_id}` — an empty `users` table is what keeps
   the break-glass environment admin alive, and provisioning a viewer empties
   that path without filling the gap. So the operator creates the first admin
   locally, and only then does SSO start admitting people.
   `auth.revoke_break_glass` is deliberately **not** loosened or reused here: it
   exists to retire the environment admin when the first real account is
   created, and stretching it to cover OIDC provisioning would be a second
   coupling between two unrelated lifetimes.

8. **The handoff code travels in the URL fragment, is single-use, and lives 120
   seconds.** The callback parks the code in the handoff dict and redirects to
   the SPA with `#sso_code=<code>` — never `?sso_code=`, because a query string
   reaches browser history, `Referer` headers, container access logs and the
   reverse proxy, which is the leak ADR 0005 spent a whole ticket closing. The
   fragment is not sent to any server. `POST /auth/oidc/exchange` consumes the
   code once (popping it before the lookup, so a race cannot redeem it twice),
   refuses one older than 120 seconds, and only then opens a `UserSession` of
   `sessions.OIDC_KIND`. A rejection takes the same fragment route back with
   `#sso_error=<code>`, so the failure path needs no session either.

9. **`sso_error` is a frozen enum with fixed client copy, and no IdP free text
   ever reaches a URL.** The failure redirects carry a code from a closed set
   declared in `api/oidc.py` (`oidc.SSO_ERRORS`) and mirrored by `SSO_ERROR_COPY`
   in `web/src/lib/api/auth.ts`: `state_missing`, `state_unknown`,
   `state_replayed`, `state_expired`, `cookie_mismatch`, `nonce_mismatch`,
   `token_invalid`, `provider_unavailable`, `provider_rejected`,
   `group_not_allowed`, `domain_not_allowed`, `no_admin_bootstrap` and
   `exchange_failed`. `provider_rejected` is separate from
   `provider_unavailable` because a user cancelling at the IdP is not a
   transient outage, and "try again shortly" is the wrong advice for it. Each
   has one sentence of copy of its own, and an unknown code falls back to the generic line — the client
   never derives text from the value. An IdP `error` parameter echoed back from
   the provider, an error body, an exception string and a raw `sso_error` from a
   query string are never rendered: an attacker-supplied string in a redirect
   target is a reflected-content problem the deployment does not need.

10. **Nothing from discovery, JWKS or a token response is ever logged.** The
    `httpx` client is wrapped so that a failure is reported as a class and a
    status, never as the exception text — an `httpx` exception embeds the
    request URL and the response body, and those responses carry the client
    secret and the `id_token`. The audit row for a successful SSO login carries
    exactly `{"kind", "client_ip", "issuer"}` — no claim set, no email, no
    subject, no token. `kind` is `sessions.OIDC_KIND`, which is the same shape
    `login.succeeded` already uses for its local counterpart.

11. **`GET /auth/oidc/callback` mutates no user, session or identity row.** It
    reads the discovery document, verifies the `id_token` signature and claims,
    parks the handoff code, and redirects. Provisioning, identity binding,
    session creation and the success audit row all happen in
    `POST /auth/oidc/exchange`, which is the single mutating step of the whole
    flow. The one exception to "no mutation" on the callback is deliberate and
    narrow: a rejected response writes a `login.oidc.failed` row through
    `audit.record`, which opens and commits **its own** transaction. That row's
    `detail` carries exactly `{"kind", "client_ip", "issuer", "sso_error"}` —
    the frozen enum value and the issuer, never the `state`, the `code`, the
    `id_token` or any provider free text. The
    callback therefore writes no row of its own, joins no request transaction,
    and cannot leave a half-applied identity link behind — the failure record
    and the absence of a mutation are the same design, not a contradiction.

12. **The `id_token` is verified against the IdP's JWKS, with asymmetric
    algorithms only.** The token's `iss` must equal `OIDC_ISSUER`, `aud` must
    contain `OIDC_CLIENT_ID`, `exp`/`iat` are checked with no leeway beyond PyJWT's default, the
    `nonce` must match the one stored with the pending state, and the signature
    is checked against a key from the issuer's JWKS. `alg=none` and every HMAC
    algorithm are refused outright: an HS256 token signed with the client secret
    is a token the *client* can mint, and accepting it would make the client
    secret an identity authority.

13. **The redirect URI is derived, not accepted.** It is
    `${PUBLIC_URL}/auth/oidc/callback`, computed in `api/oidc.py`; no route
    parameter, no request field and no stored value can override it, and the
    callback never honours a `next`, `redirect_uri` or `return_to` from the
    request. `PUBLIC_URL` is therefore load-bearing when SSO is on, and the boot
    validator refuses `OIDC_ENABLED` with an empty `PUBLIC_URL` rather than
    guessing an origin.

14. **The boot validator fails closed on every half-configuration.**
    `oidc.validate_oidc_configuration()` runs from `main.lifespan`, next to
    `auth.validate_auth_configuration()`, so it refuses the **start** of the
    process rather than the import of a module (a test can import the app
    without triggering it). Every check below applies only when
    `OIDC_ENABLED` is true, and it refuses when any of `OIDC_ISSUER`,
    `OIDC_CLIENT_ID` or `OIDC_CLIENT_SECRET` is missing; when both allow-lists
    are empty; when `OIDC_ISSUER` is not `https://`; when `OIDC_ADMIN_GROUPS` is
    non-empty; when `AUTH_ENABLED` is false; and when `PUBLIC_URL` is empty.
    Each refusal names the variable at fault. A partially
    configured sign-in path that silently authenticates nobody is a support
    ticket; one that silently authenticates *everybody* is an incident, so the
    answer is to not boot.

15. **The pending-state store and the handoff store are in-process dicts, and
    that is a stated contract, not an implementation detail.** They live in
    `api/oidc.py` as module-level dicts. They die with the process, so a restart
    mid-flow invalidates an in-flight login (the user retries; the failure is a
    `sso_error`, not a session). They are also **not shared between workers**:
    today that is correct because the API runs a single uvicorn process with no
    `--workers`, but it is a latent contract. Running multiple workers would
    break the flow in a way that looks like a random failure — a `/start` on
    worker A and a `/callback` on worker B see different dicts — so before
    `--workers` is ever raised, the pending-state and handoff stores must move to
    a shared store (a table with an expiry, or Redis), and
    `docs/architecture/CONFIGURATION.md` must say so. Anyone tempted to add
    workers should read that sentence first.

16. **The four OIDC routes are public, because they run before a session
    exists.** `GET /auth/oidc/status`, `GET /auth/oidc/start`,
    `GET /auth/oidc/callback` and `POST /auth/oidc/exchange` are declared
    `permissions.PUBLIC`: by the time any of them could present a bearer token
    the login they are performing has not happened yet. That is safe because
    each of them is gated by something stronger than a route-level role — the
    signed state, the PKCE verifier, the single-use handoff code, the allow-list
    and the admin-exists precondition.

17. **Provisioning is one transaction, and the account it creates is inert
    locally.** `POST /auth/oidc/exchange` creates the `users` row, the
    `oidc_identities` row, the `UserSession` row and the `login.oidc.succeeded`
    audit row in one transaction, so a failure leaves no half-linked account: no
    user without an identity, no identity pointing at nothing, no session
    without its record. The new row has `password_hash = NULL`, which is what
    makes it unusable at `POST /login` — `accounts.verify_password` has nothing
    to compare against, so the account cannot be brute-forced locally, and
    `accounts.create_user`'s hashing path is what a *local* account still uses.

Threat model — each control, and the attack it stops:

| Control | Attack it stops |
|---|---|
| Identity binds only on persisted `(issuer, subject)` (migration 10) | **Claim spoofing of a local account**: a hostile or misconfigured IdP asserts `preferred_username=admin` or an existing user's email and is handed that account. Nothing is looked up by name or address. |
| Signature verified against JWKS; `alg=none` and all HS* refused | **Algorithm confusion**: a token the client itself can mint with the shared secret, or an unsigned token claiming `alg=none`, is accepted as an identity assertion. |
| Single-use `state` bound to the PKCE verifier, the nonce and a flow cookie (`cookie_mismatch`) | **State CSRF / login CSRF**: an attacker plants their own callback on a victim's browser and logs the victim into the attacker's account (or completes a flow the victim never started). |
| PKCE `S256` + single-use handoff code with a 120-second TTL | **Code replay**: an intercepted authorization code or handoff code is redeemed a second time, or redeemed by someone who only observed the redirect. |
| `OIDC_EDITOR_GROUPS` is the only escalation; `OIDC_ADMIN_GROUPS` refused at boot; stored `users.role` never rewritten | **Admin escalation via claims**: a group named `admin` in a shared IdP tenant, or a rewritten role on re-login, silently grants admin over the library, users and audit log. |
| Redirect URI derived from `PUBLIC_URL`; no request field honoured | **Open redirect**: a crafted `/auth/oidc/start?redirect_uri=…` turns the trusted origin into a bounce to an attacker, carrying the code. |
| Two allow-lists compose with AND; both-empty refused at boot | **Allow-list fail-open**: an operator adds a domain list to a group list and expects it to narrow, while OR widens; or runs with no restriction and calls it configured. |
| Provisioning requires a pre-existing enabled admin, else `no_admin_bootstrap` | **First-provisioning lockout**: the very first account is an OIDC `viewer`, the users table is no longer empty, the break-glass admin is retired, and the deployment has no administrator left. |

## Consequences

The deployment can now delegate authentication to an OIDC provider without
delegating authorization: the provider says *who you are*, and the local `users`
row says *what you may do*. That split is the whole payoff, and it is what keeps
the audit log's actor column meaningful — the actor is a local account, and a
role change is still a `PATCH /users/{user_id}` a human made.

The route matrix grows by four, from 74 to **78 routes**: 8 public (the existing
`GET /health` plus the three `POST` auth routes, and the four `OIDC` routes, all
public because they run before a session exists), 25 read, 32 write and 13 admin
(`permissions.ROUTE_PERMISSIONS`, pinned by
`api/tests/test_permissions_matrix.py` and documented in
[`docs/PERMISSIONS.md`](../../../docs/PERMISSIONS.md)). `audit.ACTIONS` grows
from 30 to **32**, with `login.oidc.succeeded` and `login.oidc.failed`, and
`audit.ROUTE_ACTIONS` from 25 to **26** keys: `POST /auth/oidc/exchange` is
audited, while the three `GET` routes are out of the coverage guard's scope by
construction (it only inspects non-`GET` routes) and `GET /auth/oidc/callback`
writes its row with `audit.record`. `audit.EXEMPT_ROUTES` stays at 19 keys — the
exchange route is audited, not exempt — so the arithmetic on the 78-route matrix
is 33 `GET` routes and 45 mutating ones, split into 26 audited and 19 exempt
([`docs/AUDIT.md`](../../../docs/AUDIT.md)).

Costs paid deliberately:

- **A second identity store to reason about.** A user can be created by an
  admin, by SSO, or (while `users` is empty) by break-glass, and a reader now has
  to know that only the first two persist and that an SSO account has no
  password. `oidc_identities` is the join, and it is the only place an external
  subject is recorded.
- **A login path that can be down without the API being down.** If the IdP is
  unreachable, `/auth/oidc/start` and the callback fail while local login keeps
  working. That is the intended degradation, but it means "SSO is broken" and
  "the app is broken" are different reports and the error copy must say which.
- **An in-process flow store.** Every restart invalidates in-flight logins and
  the flow is single-worker by construction (decision 15). SSO is therefore
  correct only for a single uvicorn process; multiple workers need a shared
  store first, and that is a real piece of work rather than a flag.
- **One more thing an operator can misconfigure into a boot failure.** Six
  distinct half-configurations refuse to start. That is the point, but it moves
  the failure to deploy time rather than to first login.

Residual risks, stated plainly:

- **The IdP is trusted for group membership.** Nothing here validates that a
  `groups` claim is honest; that is the trust boundary the operator accepts by
  pointing `OIDC_ISSUER` at a provider. What this ticket bounds is the *result*:
  a hostile claim set can at most make somebody an `editor`, and only if the
  operator listed the group in `OIDC_EDITOR_GROUPS`, and only for a brand-new
  account.
- **A logged-in SSO session is an ordinary session.** After `/auth/oidc/exchange`
  the bearer token is the same 15-minute access token plus rotating refresh
  token as a password login, with the same `localStorage` exposure ADR 0004
  accepted (MV-SEC-008). SSO changes how the session starts, not what it can do
  or how it is stored.
- **The subject is the IdP's to change.** An IdP that reassigns `sub` for an
  existing person orphans their local account (a new `oidc_identities` row, a
  new `viewer`). That is deliberate: the alternative is falling back to email,
  which is the takeover path decision 3 refuses.
- **Per-IP limiting is defeated by a distributed flood.** Both stores are
  bounded (`oidc.STORE_CAP`, 1024 entries, swept on every read and write, and
  a full store refuses a new entry with `StoreFull` instead of evicting a
  live one), and `/auth/oidc/start` has its own per-IP fixed-window limiter
  (`oidc._StartLimiter`, separate from `login_throttle.limiter` so an SSO
  flood cannot lock a local account out). What that does **not** stop is a
  flood from many source addresses: enough of them can keep the store at
  capacity, and while the IdP is unreachable the start route never reaches
  `record()`, so the limiter's window is not advanced either. The impact is
  bounded to "SSO logins fail while someone is flooding", because a full
  store refuses rather than evicts and local password login is untouched.
- **`GET /auth/oidc/callback` is an unauthenticated audit-write surface.**
  Any internet GET with `?error=` or a junk `state` appends one
  `login.oidc.failed` row, and the callback carries no rate limiter (the
  start route does). The rows are admin-only and small, and the proxy in
  front is the intended control, but it is unbounded disk growth from an
  unauthenticated source. Bounding it — only auditing when a pending state
  existed, or routing the write through the start limiter — is a follow-up,
  not part of this decision.

Deliberately out of scope: no change to `AUTH_*` semantics, no change to the
break-glass rule, no change to the login throttle, no change to the file-grant
path, no MFA (`Mf-lg02`), no per-asset ownership (`Mf-arm6`), no session
management UI (`Mf-7op4`), no logout propagation to the IdP (signing out of
Curiarium revokes the local session and leaves the IdP session alone), and no
provider-specific code — every IdP is reached through discovery.

## Alternatives considered

- **SAML instead of OIDC.** Rejected: it is a second, larger protocol with its
  own XML signature surface, and every provider this product is likely to meet
  speaks OIDC. One flow, one verifier.
- **Trust the `email` claim and link to an existing local account.** Rejected:
  that is the account-takeover path decision 3 exists to close. A verified email
  proves control of a mailbox to the IdP, not that the IdP's owner is this
  deployment's administrator.
- **Map an IdP `admin` group to the `admin` role.** Rejected: an `admin` in a
  shared tenant (or a group named `admin` for a different product) would own the
  library, the user table and the audit log. `OIDC_ADMIN_GROUPS` is refused at
  boot so the configuration cannot even express it.
- **Rewrite `users.role` on every login from the current claims.** Rejected: the
  role would then be a function of an external system at login time, with no
  human and no audit row in the loop, and a group edit at the IdP would silently
  demote or promote anybody without leaving a `user.role_change` row.
- **A `?sso_code=` query parameter rather than a fragment.** Rejected: ADR 0005
  removed the last URL credential from query strings precisely because the query
  reaches history, `Referer`, access logs and the proxy. The fragment reaches
  none of them.
- **Set the refresh token as an HttpOnly cookie and skip the handoff.** Rejected
  for the reasons ADR 0004 gives: this API speaks bearer tokens, a cookie needs
  CSRF machinery, and the browser client would still have to read the access
  token to call the API.
- **Compose the allow-lists with OR ("either list admits").** Rejected as
  fail-open: an operator who adds a domain list to an existing group list is
  narrowing, and OR would widen. Restrictive composition is the only safe
  reading of "both configured".
- **Allow the first SSO user to become the first admin.** Rejected: it makes an
  external tenant the root of trust for the local deployment's administration,
  and it retires the break-glass path before any admin exists — the lockout
  decision 7 refuses.
- **Run the flow client-side (a public client with no secret).** Rejected: the
  token exchange must be able to present a client secret and to keep the PKCE
  verifier server-side; a browser-resident flow puts the verifier and the
  `id_token` in the page, back in the `localStorage` exposure ADR 0004 already
  has enough of.

## Rollback

Rollback is `OIDC_ENABLED=false`, which is the same state a deployment that never
opted in is in: the four routes stay in the matrix and answer 503, local login,
break-glass and the file-grant path are unchanged, and no flow can start. Because
the switch is a boot-validated environment key, this needs a restart and nothing
else.

That is enough for an incident, but it is not a code rollback. A full revert of
the `Mf-4c24` commit removes `api/oidc.py` and `api/routers/oidc.py`, drops the
four routes from `permissions.ROUTE_PERMISSIONS`, the two actions from
`audit.ACTIONS` and the one key from `audit.ROUTE_ACTIONS`, and reverts the
matrix to 74 routes / 30 actions. Migration 10 is **not** undone by that revert:
migrations are immutable and the runner never rolls one back, so `oidc_identities`
and any rows in it stay. Leaving the table is harmless — nothing reads it once
the module is gone — and dropping it is a separate, deliberate schema decision
with a tested restore path, per ADR 0002.

Accounts an SSO flow provisioned also stay. They have `password_hash = NULL`, so
after a revert they cannot log in at all: they are inert rows an admin can delete
or give a password to through the ordinary user routes. Say that out loud in the
rollback report, because "SSO is off" and "the account still exists" are both
true at once.

## Verification

API:

- `api/tests/test_oidc.py` — the flow end to end against a stubbed discovery /
  JWKS / token endpoint: `/start` mints and stores state, PKCE `S256` and the
  nonce; the callback refuses a bad `state`, a replayed `state`, a wrong `nonce`,
  a wrong `iss`, a wrong `aud`, an expired token, `alg=none`, an HS256 token, and
  a signature from the wrong key; the handoff code is single-use, expires after
  120 seconds and is refused when unknown; `/exchange` provisions a `viewer`,
  an `editor` only from `OIDC_EDITOR_GROUPS`, never an `admin`, and never
  rewrites an existing `users.role`; a claim naming an existing local account
  provisions a **new, suffixed** account and links nothing to the old one;
  a disabled SSO account is refused on re-login; identity binds on
  `(issuer, subject)` and not on username or email; a new account has
  `password_hash = NULL`; both allow-lists must pass (AND); provisioning
  without an enabled admin is refused with a 409 and creates no row, which
  the web client renders as the `no_admin_bootstrap` copy; the `sso_error`
  set is closed; a rejection writes exactly one `login.oidc.failed` row and no
  identity/session/user row; a successful exchange writes
  `login.oidc.succeeded` with the three-key detail; and no token, secret or
  claim set appears in a log record.

  **Amended (2026-10-30, Mf-sg2t):** the `viewer` in that list is now the
  configured `OIDC_DEFAULT_ROLE`, and every non-admin role is exercised
  parametrically rather than `viewer` alone; an `editor` still comes only from
  `OIDC_EDITOR_GROUPS`, never an `admin`, and an existing `users.role` is still
  never rewritten. The same file proves the bootstrap refusal from an empty users
  table: `POST /auth/oidc/exchange` answers 409 with
  `An administrator must sign in locally before SSO can create accounts`, writes
  no `users` row and no `oidc_identities` row, and succeeds once an admin exists.

- `api/tests/test_migration_010.py` — migration 10 creates `oidc_identities`
  with the unique `(issuer, subject)` constraint, is idempotent, and appends
  exactly one ledger row.
- `api/tests/test_permissions_matrix.py` — the 78-route matrix (8 public, 25
  read, 32 write, 13 admin), the four OIDC routes classified `public`, and the
  route count matching the matrix key count.
- `api/tests/test_auth_disabled.py` — the four OIDC routes answer 503 with auth
  disabled, and `OIDC_ENABLED` with `AUTH_ENABLED=false` refuses to boot.
- `api/tests/test_audit_log.py` — the two new actions are in `ACTIONS`,
  `POST /auth/oidc/exchange` is in `ROUTE_ACTIONS`, the exempt set is unchanged
  at 19, and the coverage guard passes.
- `api/tests/test_snapshots.py` — the docs pins that hold the audit figures:
  `ACTIONS` is 32, `ROUTE_ACTIONS` is 26, and `docs/AUDIT.md` states the
  78-route arithmetic.

Web:

- `web/src/lib/api.oidc.test.ts` — the client reads `status`, starts the flow,
  exchanges a handoff code once, carries the HTTP status on a failed exchange,
  and maps every `sso_error` code to its fixed copy without ever echoing the
  raw value.
- `web/src/ui/Login.test.tsx` — the SSO button appears only when `/auth/oidc/status`
  says SSO is enabled, local password login is still rendered and still works,
  and both failure paths show their own message.
- `web/src/ui/App.test.tsx` — a fresh load with `#sso_code=` exchanges it before
  rendering the signed-in app, clears the fragment (never the query), and does
  not exchange twice under `StrictMode`; a 409 exchange maps to the
  `no_admin_bootstrap` copy rather than the generic retry line.

## Superseding conditions

This ADR is superseded if the API moves to a cookie-based session or to a
provider-issued token as the session credential (both change what "logged in"
means, and the handoff exists because of bearer tokens); if multiple uvicorn
workers become the deployment norm, which requires the shared pending-state
store decision 15 names and a new decision about its failure modes; if a
provider requires a protocol OIDC cannot express (SAML, WS-Fed) and a second flow
is added; or if per-record ownership (`Mf-arm6`) or MFA (`Mf-lg02`) changes what
a provisioned account's role means.

A change to the claim-to-role policy — a new escalation, a different default, a
composition rule other than AND — belongs in a new ADR. This one is the record of
the policy, and the policy is the security boundary.
