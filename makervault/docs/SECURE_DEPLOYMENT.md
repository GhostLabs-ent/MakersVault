# Secure Deployment and v5.1 Authentication Upgrade

MakersVault v5.1 remains a single-administrator, self-hosted application. It does
not include user accounts, roles, MFA, SSO, or hosted identity.

## New production installation

From the `makervault` directory:

```bash
./scripts/setup-env.sh
docker compose -f docker-compose.deploy.yml up -d
```

The setup helper:

- Refuses to overwrite an existing `.env` file.
- Generates a random 40-character administrator password.
- Generates a 256-bit random session-digest and handoff signing secret.
- Writes `.env` with filesystem mode `600`.
- Prints the generated password once. Store it in a password manager.

The administrator username defaults to `admin` and may be changed in `.env`.
Changing the username is optional; the password and signing secret are required.

Production Compose stops before creating containers when `AUTH_PASSWORD` or
`AUTH_SECRET` is empty. The API also refuses to start when production values are
missing, published placeholders, too short, or identical. This second check also
protects non-Compose deployments.

In the local Gate 11A build, the validated environment username and password are
used once to create the persistent administrator when the identity table is empty.
After that succeeds, login uses the Argon2id hash in SQLite. Changing
`AUTH_USERNAME` or `AUTH_PASSWORD` in `.env` does not rename the administrator,
rotate its password, or provide a recovery bypass. Preserve the original credential
and a matched raw backup; account-management and stopped-instance recovery remain
later gated work. `AUTH_SECRET` keys stored session digests and the separate bridge
handoff signing key, so changing it invalidates existing browser sessions and
outstanding short-lived handoff grants.

## Upgrading an existing installation

Follow the tested [v5.1 upgrade procedure](UPGRADE_V5.1.md) and create a verified
matched database/storage archive with the
[backup and recovery tooling](BACKUP_AND_RECOVERY.md) before changing images.
Then inspect the existing `.env` file in the `makervault` directory.

Set all of these values before starting v5.1:

```dotenv
AUTH_USERNAME=admin
AUTH_PASSWORD=<unique password with at least 12 characters>
AUTH_SECRET=<at least 32 random bytes>
SESSION_IDLE_TTL=43200
SESSION_ABSOLUTE_TTL=604800
SESSION_TOUCH_INTERVAL=300
SESSION_MAX_ACTIVE=20
```

Generate a signing secret without placing it in shell history:

```bash
openssl rand -hex 32
```

Do not reuse the administrator password as `AUTH_SECRET`. Published values such
as `super-secret`, `password`, `changeme-secret`, and
`replace-with-random-secret` are rejected in production.

After changing `AUTH_SECRET`, existing browser sessions become invalid. Sign in
again with the persistent administrator credential. Schema 14 adds revocable
browser sessions but does not transform stored model files.

Production sessions use `__Host-` cookies with `Secure`, `HttpOnly` for the session
secret, `SameSite=Lax`, `Path=/`, and no `Domain`. Production browser access
therefore requires HTTPS. Only explicit `development` and `test` environments use
separately named non-Secure cookies for local HTTP. Unsafe requests require both an
exact configured browser `Origin` and the session-bound `X-CSRF-Token` header.
The idle timeout defaults to 12 hours, the absolute lifetime to seven days, and one
administrator may retain at most 20 active sessions; all values fail closed when
invalid.

If startup fails, inspect the API container log. The validation error lists each
missing or unsafe setting. Correct `.env` and restart; do not restore published
fallback credentials except temporarily on an isolated recovery network.

## Passkey origin configuration (Gate 11E integration)

The local Gate 11E-1b build contains origin-bound registration and account
self-management APIs, but it is not independently releaseable: password-first login
does not enforce the enrolled factor until 11E-1c and browser UI follows in 11E-1d.
Do not deploy or enable this intermediate slice on a live instance.

The eventual passkey deployment contract requires one stable HTTPS browser origin:

```dotenv
WEBAUTHN_RP_ID=vault.example.com
WEBAUTHN_ORIGIN=https://vault.example.com
WEBAUTHN_RP_NAME=MakersVault
```

The RP ID is a lowercase DNS name, not a URL. The origin is one exact origin without
a path and must use the RP ID host or its subdomain. Arbitrary IP/mDNS HTTP remains a
password-only posture; only `http://localhost` is permitted in development or test.
Both required settings must be present together. Once an account or policy requires
MFA, removing or invalidating this configuration stops the API instead of bypassing
the factor. The same browser origin must also be allowed by `PUBLIC_URL` or
`CORS_ORIGINS` so the ceremony endpoints accept its unsafe requests.

## File and archive limits

The default maximum is 512 MiB for each stored or imported file. This is a
per-file safety boundary, not a quota on the library or an ordinary multi-file
upload: users may continue importing large file sets as individual files. ZIP
extraction separately limits the number selected and their total declared
expanded size because a small archive can otherwise create unbounded work.

MakersVault also keeps a 512 MiB free-space reserve by default. A write that
would cross it fails with HTTP 507 and its partial file and provisional database
record are removed. Byte/archive violations fail with HTTP 413. Existing files
larger than a newly configured ceiling remain readable.

Operators can tune the `FILE_MAX_MB`, `STORAGE_RESERVE_MB`, `ARCHIVE_*`,
`IMAGE_MAX_PIXELS`, and `GENERATED_THUMBNAIL_MAX_MB` values documented in
[CONFIGURATION.md](architecture/CONFIGURATION.md). If `FILE_MAX_MB` is raised,
raise the request-body limit at an external reverse proxy as well. The bundled
web proxy derives its limit from the same setting. Invalid budget values stop
startup rather than silently removing a safety control.

## Remote-import network boundary

Remote import accepts public HTTP and HTTPS targets only. Each DNS answer and
redirect is checked before MakersVault connects; private, loopback, link-local,
special-use, or mixed public/private results are rejected. Connections are pinned
to the checked numeric peer while HTTPS still verifies the original hostname.
HTTPS-to-HTTP redirects and URL-embedded credentials are rejected, and source
cookies or authorization are not forwarded to a different origin.

The default redirect ceiling is five and can be changed with
`IMPORT_MAX_REDIRECTS`; `0` disables redirects. MakersVault intentionally ignores
implicit `HTTP_PROXY`/`HTTPS_PROXY` environment settings for imports because they
replace the validated destination with a proxy connection. Outbound proxy support
is not part of the v5.1 trust contract. Private-network URL imports remain
unsupported; use the read-only mounted-import workflow for local files.

## Slicer and engraver bridge trust

v5.1 requires the v5.1 bridge. Older bridge binaries accept the retired
administrator-token/arbitrary-URL protocol and are not compatible with the v5.1
web handoff.

On first use, the bridge opens a confirmation page served only from a random
loopback address and displays the exact MakersVault API origin. Confirm only the
address you intended to use. HTTPS is expected for remote deployments; an HTTP
origin should be trusted only on a LAN you control. Confirmed origins are stored
in the bridge's local `trusted_origins` config.

Every handoff is limited to one file and slicing or engraving for 90 seconds.
The administrator token is not shared with the bridge. The bridge does not follow
redirects or invoke the OS default file opener, and it removes partial downloads
that exceed its default 512 MiB ceiling. Select an installed built-in application
or define a trusted custom command in the local bridge config.

## Login and browser sessions

Failed logins receive a short progressive cooldown beginning after the third
failure and capped at 60 seconds. The control is bounded, process-local, and
matches the supported single API process; restarting the API clears its attempt
history. Audit events include the immediate client address and outcome but never
the supplied password or issued session secret.

Audit capture is mandatory and cannot be disabled or narrowed in Settings. It
covers every mutation plus account/session administration, exports, handoff
redemption, and audit reads. Records use classified route templates and never copy
request/response bodies or query strings. Only Administrator may read the newest-
first, cursor-paginated Security Audit view; no application endpoint edits or
deletes audit history.

The current local build stores an opaque session secret only in an HttpOnly cookie;
JavaScript cannot read it, and no authentication bearer is placed in local or
session storage. On first load the web client deletes any legacy stored bearer
instead of migrating or refreshing it. Protected file and preview URLs use the same
cookie and contain no authentication query parameter.

Logout revokes the current server-side session. Authenticated session listing,
single-session revocation, and revoke-all are also available; expired and revoked
rows are cleaned in bounded batches. The separately signed 90-second exact-file
bridge handoff remains unchanged and cannot authenticate an ordinary API route.

## Browser headers and host policy

The bundled web gateway sets CSP, `nosniff`, no-referrer, permissions, and frame
denial headers. Its CSP derives the separately configured API origin and declared
HTTP(S) `CORS_ORIGINS` when present, retaining the blob/WASM/worker capabilities
required by model previews. CORS does not authorize a mutation:
cookie-authenticated unsafe requests independently require an exact configured
Origin and bound CSRF header. Direct API responses carry the matching non-CSP
baseline.

When `PUBLIC_URL` is configured, the API accepts that hostname plus loopback
health checks. Set `TRUSTED_HOSTS` explicitly as a comma-separated list when the
public API uses a different hostname. If neither value is configured, host
filtering stays permissive for direct IP or mDNS access on a trusted LAN; that
mode must not be exposed to the public Internet.

If one installation is intentionally reached through both `PUBLIC_URL` and a LAN
IP/name, list both API hosts in `TRUSTED_HOSTS` and both browser origins in
`CORS_ORIGINS`. An explicit trusted-host list replaces automatic derivation.

The external HTTPS reverse proxy should preserve `Host` and, only after the
operator confirms the hostname will remain HTTPS-only, add an appropriate HSTS
policy. MakersVault does not emit HSTS itself because the same container supports
intentional HTTP on trusted LANs and cannot make that permanence decision.

## Supported network posture

- Localhost and a genuinely trusted LAN may use direct access. Plain HTTP does
  not protect credentials or tokens from other network observers.
- Remote access requires an operator-managed HTTPS reverse proxy or a private
  network/VPN providing equivalent transport protection.
- One HTTPS hostname routed to the web container is recommended. The web
  container forwards same-origin `/api/*` requests internally.
- Existing two-hostname UI/API deployments remain supported when
  `VITE_API_URL` and `CORS_ORIGINS` are configured explicitly.
- Direct exposure of the API or web ports to the public Internet is unsupported
  for v5.1.

MakersVault does not obtain or renew TLS certificates. See
[REVERSE_PROXY.md](architecture/REVERSE_PROXY.md) for routing examples and proxy
expectations.

## Development mode

`docker-compose.yml` is the source-development manifest. It explicitly selects
development mode and supplies development-only fixture credentials. These values
must never be copied into `docker-compose.deploy.yml` or a production `.env`.

When running the API directly for development, provide explicit credentials and
set `MAKERSVAULT_ENV=development`. Omitting the environment selects production
validation by default.
