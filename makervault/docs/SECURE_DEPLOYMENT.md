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
- Generates a 256-bit random JWT signing secret.
- Writes `.env` with filesystem mode `600`.
- Prints the generated password once. Store it in a password manager.

The administrator username defaults to `admin` and may be changed in `.env`.
Changing the username is optional; the password and signing secret are required.

Production Compose stops before creating containers when `AUTH_PASSWORD` or
`AUTH_SECRET` is empty. The API also refuses to start when production values are
missing, published placeholders, too short, or identical. This second check also
protects non-Compose deployments.

## Upgrading an existing installation

Back up the database and storage volumes before any release upgrade. Then inspect
the existing `.env` file in the `makervault` directory.

Set all of these values before starting v5.1:

```dotenv
AUTH_USERNAME=admin
AUTH_PASSWORD=<unique password with at least 12 characters>
AUTH_SECRET=<at least 32 random bytes>
AUTH_TOKEN_TTL=43200
```

Generate a signing secret without placing it in shell history:

```bash
openssl rand -hex 32
```

Do not reuse the administrator password as `AUTH_SECRET`. Published values such
as `super-secret`, `password`, `changeme-secret`, and
`replace-with-random-secret` are rejected in production.

After changing `AUTH_SECRET`, existing browser sessions become invalid. Sign in
again with the configured administrator credentials. No database or stored-file
migration is performed by this authentication change.

If startup fails, inspect the API container log. The validation error lists each
missing or unsafe setting. Correct `.env` and restart; do not restore published
fallback credentials except temporarily on an isolated recovery network.

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
