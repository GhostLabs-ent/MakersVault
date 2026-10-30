# ADR 0001: Canonical Compose manifests

**Status:** Accepted

**Accepted:** 2026-08-14

## Context

The repository had three Compose files with overlapping service definitions,
different image tags, different mounted-import settings, and no declared source
of truth. The root README also embedded another production definition. This made
the deployed architecture depend on which copy an operator happened to choose.

## Decision

- `curiarium/docker-compose.yml` is the canonical local source-build manifest.
- `curiarium/docker-compose.deploy.yml` is the canonical production image
  manifest.
- `curiarium/docker-deploy.yml` remains temporarily as a compatibility alias that
  includes the canonical production manifest. It contains no service definition
  of its own.
- Optional mounted imports use `/imports` in the container and `./imports` as the
  safe default host directory. Scanning remains disabled until
  `IMPORT_MOUNT_PATH=/imports` is explicitly configured.
- Development SQLite data moves from the source-mounted `/app/curiarium.db` to
  `/app/data/curiarium.db`, backed by `./data/db`.
- Curiarium remains a two-container application: `web` and `api`. The production
  web container is also the internal same-origin gateway: it serves the static UI
  and forwards `/api/*` to `api:8000` over the private Compose network.
- The recommended external reverse-proxy topology uses one public hostname and
  sends all paths to `web:5173`. A second public API hostname remains an optional
  direct/diagnostic topology, not a requirement.
- The README must reference the manifest files rather than duplicate their full
  contents.

## Consequences

- Production behavior has one editable source.
- Existing commands using `docker-deploy.yml` continue to work with a Compose
  implementation that supports `include`.
- Very old Compose implementations that do not support `include` must use the
  canonical filename directly.
- Local source builds no longer write the runtime database into `api/`. This is a
  storage-path change inside the API container; it does not combine the API and
  web containers.
- A deployment can use `https://curiarium.example` alone: the external proxy
  targets the web container, and the web container relays
  `https://curiarium.example/api/*` internally to the API container.
- Existing two-host deployments such as `curiarium.example` plus
  `curiariumapi.example` remain possible by setting `VITE_API_URL` and CORS
  deliberately, but they introduce extra certificate, CORS, and configuration
  surface.
- Gate 1 still owns removal of published credential and signing-secret fallbacks.

## Alternatives considered

- Keep two production copies synchronized manually: rejected because drift is the
  problem being removed.
- Delete the historical filename immediately: rejected to retain a compatibility
  path during v5.1.
- Make the production image manifest the development manifest too: rejected
  because local source verification must build the exact working tree.

## Rollback

No stored content is transformed. Reverting the manifest choice restores prior
commands. Development data that has already moved to `data/db` must be copied
back deliberately; it must never be deleted as part of rollback.

## Verification

The Gate 0 container smoke test reaches the API both through its direct diagnostic
port and through `web:5173/api/health`. This proves the one-host routing path
inside the Compose network without requiring a second external proxy.

## Superseding conditions

Supersede this ADR if Curiarium adopts a different supported deployment system
or removes the compatibility alias in a documented major upgrade.
