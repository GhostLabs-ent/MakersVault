# ADR 0002: Ordered, application-owned SQLite migrations

**Status:** Accepted

**Accepted:** 2026-08-14

## Context

Curiarium previously called `SQLModel.metadata.create_all()` and several manual
`ensure_*` functions during startup. Those changes had no schema version, could
not prove which steps had run, and made larger future data-model changes unsafe.
Existing installations may be unversioned and may contain any of the historical
columns already.

## Decision

Use a small, ordered, application-owned migration runner for the current SQLite-
only architecture.

- Immutable integer versions and names are recorded in `schema_migration`.
- Each missing migration runs inside its own database transaction.
- Initial tables are expressed in migration SQL rather than inferred from the
  latest ORM model.
- Adoption migrations inspect existing unversioned tables and add only missing
  structures.
- Startup stops on a failed migration or a recorded version/name mismatch.
- Migration tests create sanitized legacy fixtures programmatically and never use
  a committed runtime database.
- Schema contraction waits for a later release and a tested restore path.

## Why not Alembic now

Alembic is capable and remains a future option, but Curiarium currently has one
SQLite backend, a very small schema history, and the immediate problem is safely
adopting unversioned databases with partially applied legacy changes. Explicit
idempotent adoption SQL is smaller and easier to audit for this transition than
an autogeneration-oriented framework.

This decision does not claim database portability. If another database backend or
substantially more complex migrations become supported, the migration system must
be reconsidered through a superseding ADR.

## Consequences

- Fresh and legacy databases converge on a declared version.
- Migration names and versions become compatibility commitments.
- Every future schema change must include forward, interruption, and restore
  evidence.
- The project owns the runner and therefore owns tests for ordering, concurrency,
  and failure semantics.

## Rollback

The v5.1 adoption migrations are additive. Release rollback restores the matched
pre-upgrade SQLite database and managed-storage snapshot. No lossy down migration
is promised.

## Superseding conditions

Revisit this decision before adding another database engine, destructive schema
contraction, or migration orchestration that cannot be expressed safely by the
current runner.
