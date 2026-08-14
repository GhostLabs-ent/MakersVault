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
