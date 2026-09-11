# Secure Deployment and v5.1 Authentication Upgrade

This guide describes the current local build through Gate 13C hardening. The frozen Gate 5
candidate remains at `f6ff55b`; release qualification and deployment approval for
later work are separate.

The current MakersVault build is a self-hosted shared-vault application with persistent local
accounts, fixed Administrator/Member/Viewer roles, revocable browser sessions, and
optional password-plus-passkey MFA. It does not include public registration,
passwordless login, TOTP, recovery codes, API keys, OIDC/SSO, or hosted identity.

## Container privilege boundary

The current local Compose manifests enable `no-new-privileges` and drop Docker's
default capability set. The API allowlist is limited to `CHOWN`, `DAC_OVERRIDE`,
`FOWNER`, `SETGID`, `SETUID` and `SETPCAP` for account/volume initialization and
trusted offline recovery. After initialization, the entrypoint uses `setpriv` to
clear inheritable, ambient and bounding capabilities and enable no-new-privileges
before executing the application. Under the non-root configuration, effective and
permitted sets are also empty. Web runs as UID 101 with no capabilities.

Keep a nonzero API `PUID`/`PGID` (defaults 1000/1000) and retain the shipped
entrypoint. Fresh/existing volume setup and the opt-in recursive ownership mode
remain available; no new memory, CPU, PID, upload or library limit is introduced.
The root filesystem remains writable for startup account/runtime configuration.
The historical `docker-deploy.yml` alias inherits the canonical policy.

These are deployment defaults, not Administrator UI settings. Custom Compose
overrides or non-Compose launches must preserve equivalent controls; an entrypoint
override or `docker exec` is a separate operator process, not proof of the API's
post-initialization capability state. Offline restore deliberately retains the
small operator capability set. Do not grant `privileged`, extra capabilities or
Docker-socket access to work around an error. Stop and diagnose ownership or
runtime compatibility instead.

This reduces privilege exposure; it does not patch native image findings, sandbox
malicious raw snapshots, or protect all vault bytes from a compromised application.
Trusted-backup, HTTPS and separate release-qualification requirements still apply.

## New production installation

From the `makervault` directory:

```bash
./scripts/setup-env.sh
# Configure the final HTTPS origin and external TLS proxy before browser access.
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

`setup-env.sh` creates credentials, not a certificate or reverse proxy. Before
starting a new current production instance, configure `PUBLIC_URL` and
`CORS_ORIGINS` to its final HTTPS origin and leave `VITE_API_URL` empty for the
recommended same-origin `/api` gateway. Arrange a trusted TLS certificate/proxy
as described in [Reverse Proxy](architecture/REVERSE_PROXY.md). For a host-local
proxy, bind published API/web ports to loopback (for example `API_PORT=127.0.0.1:8000`
and `WEB_PORT=127.0.0.1:5173`); choose private network routing when the proxy itself
runs in a container. Do not expose unprotected upstream ports publicly.

Production Compose stops before creating containers when `AUTH_PASSWORD` or
`AUTH_SECRET` is empty. The API also refuses to start when production values are
missing, published placeholders, too short, or identical. This second check also
protects non-Compose deployments.

The validated environment username and password are used once to create the
persistent administrator when the identity table is empty.
After that succeeds, login uses the Argon2id hash in SQLite. Changing
`AUTH_USERNAME` or `AUTH_PASSWORD` in `.env` does not rename the administrator,
rotate its password, or provide a recovery bypass. Preserve the original credential
and a matched raw backup. Administrators manage local accounts in **Settings →
Accounts & Access**; emergency recovery uses the documented stopped-instance
procedure. `AUTH_SECRET` keys stored session and ceremony digests plus the separate
bridge handoff signing key, so changing it invalidates existing browser sessions,
pending authentication ceremonies, and outstanding short-lived handoff grants.

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

After changing `AUTH_SECRET`, existing browser sessions and pending authentication
ceremonies become invalid. Sign in again with a persistent account credential.
The authentication migrations do not transform stored model files.

Production sessions use `__Host-` cookies with `Secure`, `HttpOnly` for the session
secret, `SameSite=Lax`, `Path=/`, and no `Domain`. Production browser access
therefore requires HTTPS. Only explicit `development` and `test` environments use
separately named non-Secure cookies for local HTTP. Unsafe requests require both an
exact configured browser `Origin` and the session-bound `X-CSRF-Token` header.
The idle timeout defaults to 12 hours, the absolute lifetime to seven days, and one
administrator may retain at most 20 active sessions; all values fail closed when
invalid.

If startup fails, inspect the API container log. The validation error lists each
missing or unsafe setting. Correct `.env` and restart; never restore published
fallback credentials or switch production into development mode to regain access.
Use the backup-first stopped-instance recovery procedure for account recovery.

## Passkey origin configuration and policy

Passkeys require one stable HTTPS browser origin:

```dotenv
WEBAUTHN_RP_ID=vault.example.com
WEBAUTHN_ORIGIN=https://vault.example.com
WEBAUTHN_RP_NAME=MakersVault
```

The RP ID is a lowercase DNS name, not a URL. The origin is one exact origin without
a path and must use the RP ID host or its subdomain. Arbitrary IP/mDNS HTTP is not a
supported passkey origin. The passkey origin validator permits `http://localhost`
only in development or test; this does not create a production HTTP exception.
Both required settings must be present together. Once an account or policy requires
MFA, removing or invalidating this configuration stops the API instead of bypassing
the factor. The same browser origin must also be allowed by `PUBLIC_URL` or
`CORS_ORIGINS` so the ceremony endpoints accept its unsafe requests.

Establish the final hostname before anyone enrolls. Passkeys are scoped to the RP ID
and origin; changing them does not migrate credentials. If a hostname must change,
reset or replace affected credentials while the old origin is still available, or
use the stopped-instance Administrator recovery procedure if no Administrator can
sign in.

Passkey policy is **Optional** by default. Each user opts in by adding a passkey in
**Settings → Accounts & Access**; the first successful enrollment enables MFA for
that account, so future sign-ins require both password and passkey. Keeping two
passkeys is recommended. An Administrator can select **Require Administrators** or
**Require everyone** only after every enabled targeted account has enrolled. The
setting is an Administrator choice, not a mandatory default.

Required policy is fail-closed. It prevents a targeted account's last passkey from
being removed or reset and prevents creating, enabling, or promoting an unenrolled
target. To add an Administrator while **Require Administrators** is active, create a
non-Administrator, let that user replace the temporary password and enroll, then
promote the account. **Require everyone** must be temporarily lowered to Optional
while a new enabled account is created, completes its password change, and enrolls;
restore the required policy afterward.

An Administrator may explicitly reset passkey MFA for another account only after
current-strength confirmation. Reset deletes that account's passkeys and pending
ceremonies, revokes its browser sessions, and leaves its password unchanged. First
lower or otherwise make the account non-targeted by a required policy. An
Administrator cannot use the live reset on their own account. If all Administrators
lose their factors, follow [Backup and Recovery](BACKUP_AND_RECOVERY.md): the
backup-first stopped-instance procedure resets one existing account and returns the
global policy to Optional. There is no weaker TOTP, email, or recovery-code bypass.

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
to the checked numeric peer while HTTPS verifies the canonical destination hostname.
HTTPS-to-HTTP redirects and URL-embedded credentials are rejected, and source
cookies or authorization are not forwarded to a different origin.

Outbound DNS names use strict IDNA2008 validation. ASCII names are case-insensitive;
valid Unicode names and their ASCII punycode forms use the same name for DNS,
HTTP Host, TLS SNI and redirect-origin comparison. A single trailing root dot is
accepted. Unicode case/compatibility mapping, non-NFC text, malformed punycode,
empty labels, escaped hostnames and IPv6 zone identifiers are rejected before DNS.
For a rejected internationalized hostname, use its verified canonical lowercase/NFC
spelling or ASCII punycode form. This never rewrites stored URLs or model files.
Public IPv4/IPv6 literals retain numeric-address validation. This outbound policy
does not change the installation's configured Host, browser Origin or passkey rules.

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
address you intended to use. Use the production HTTPS origin; any supported local
HTTP bridge path is a development/transport capability, not permission to deploy
the production browser UI without HTTPS. Confirmed origins are stored
in the bridge's local `trusted_origins` config.

Every handoff is limited to one file and slicing or engraving for 90 seconds.
The administrator token is not shared with the bridge. The bridge does not follow
redirects or invoke the OS default file opener, and it removes partial downloads
that exceed its default 512 MiB ceiling. Select an installed built-in application
or define a trusted custom command in the local bridge config.

## Login and browser sessions

Failed logins and passkey completions receive a short progressive cooldown beginning
after the third failure and capped at 60 seconds. The control is bounded,
process-local, and matches the supported single API process; restarting the API
clears its attempt history. Audit events include the immediate client address and
outcome but never the supplied password, issued session secret, credential ID,
public key, challenge, assertion, or authenticator response.

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
policy. MakersVault does not emit HSTS itself because TLS terminates outside the
container and the operator owns that permanence decision. Internal upstream HTTP
and explicit development HTTP do not make production browser HTTP supported.

## Supported network posture

- Current production browser access requires HTTPS, including on LANs and VPNs.
  A VPN does not satisfy the browser's Secure-cookie requirement by itself.
- Plain HTTP is for explicit development/test origins and private proxy-to-service
  upstream traffic, not production browser sign-in.
- One HTTPS hostname routed to the web container is recommended. The web
  container forwards same-origin `/api/*` requests internally.
- Two-hostname UI/API deployments must use same-site HTTPS hostnames (for example
  `vault.example.com` and `api.example.com`) and explicit `VITE_API_URL`,
  `CORS_ORIGINS` and `TRUSTED_HOSTS`. Unrelated sites cannot rely on the current
  `SameSite=Lax` cookie for cross-site fetches. Do not change cookie policy to make
  an unsupported topology work; use the same-origin gateway.
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
