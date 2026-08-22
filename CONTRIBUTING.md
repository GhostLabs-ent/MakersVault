# Contributing to MakersVault

Thank you for helping improve MakersVault. Bug fixes, tests, documentation, design
feedback, accessibility work, and focused features are welcome.

## Before a large change

Open an issue or discussion before introducing a new data model, migration, storage
layout, trust boundary, public API, desktop adapter, or major UI workflow. Describe
the user problem, migration/rollback impact, security boundary, and how completion
can be verified. The [architecture runbook](makervault/docs/ARCHITECTURE_RUNBOOK.md)
and [roadmap](makervault/docs/ROADMAP.md) record accepted sequencing and deferrals.

Security reports must follow [SECURITY.md](SECURITY.md), not a public issue.

## Development setup

The canonical local source-build manifest is `makervault/docker-compose.yml`:

```bash
cd makervault
docker compose -f docker-compose.yml up --build
```

Development credentials are explicitly non-production. Never copy them into a
reachable deployment. See [Development](makervault/docs/DEVELOPMENT.md).

## Verification

Run the complete source-owned harness from the repository root:

```bash
make verify
```

Focused targets are `verify-api`, `verify-web`, `verify-bridge`, `verify-compose`,
and `verify-smoke`. Changes to schemas require ordered migration and representative
upgrade/idempotency tests. Changes to storage, deletion, import, or recovery require
failure and rollback evidence. UI work should include deterministic interaction or
browser proof proportional to its risk.

## Pull requests

- Keep changes scoped and explain the user-visible result first.
- Add or update tests and documentation with the implementation.
- Preserve existing user data and include migration/rollback notes when relevant.
- Do not commit `.env`, databases, user content, generated previews, benchmark
  artifacts, release outputs, credentials, tokens, or private paths.
- Do not add moving production image tags or unpinned release-workflow actions.
- Call out known limitations and follow-up work rather than hiding partial behavior.

By contributing, you agree that your contribution is licensed under the repository's
existing license.
