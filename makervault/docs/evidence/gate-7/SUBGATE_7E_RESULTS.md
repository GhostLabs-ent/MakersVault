# Gate 7E Project Recovery and Compatibility Results

**Gate:** 7E — Project recovery, compatibility, and Gate 7 closeout

**Status:** Accepted by the owner

**Date:** 2026-08-26

**Entry commit:** `b66b83f`

**Contract commit:** `4c0f8f3`

**Implementation commit:** `2e71369`

**Accepted:** 2026-08-26

**Schema:** 10 unchanged

**Backup format:** `makersvault-backup` format 1 unchanged; new recovery contract
3

**Publication state:** Local only. Nothing was pushed, tagged, or published.

## Delivered behavior

- New matched backups retain the outer format-1 archive and advance only the
  recovery-contract marker from 2 to 3. Their database summaries count Project,
  ProjectMembership, and ProjectRelationship rows when those tables exist.
- The standard-library consistency audit reports active/trashed Project counts,
  membership and relationship counts, and sorted deterministic identifiers for
  missing required Project tables and broken Project graph ownership.
- Memberships must reference existing Projects and artifacts. Relationships must
  reference an existing Project and source/target artifacts, use same-Project
  member endpoints, have distinct endpoints, use a canonical kind, and have a
  unique canonical `(project, source, target, kind)` identity.
- Every Project-domain defect is critical. Live audit reports it as inconsistent;
  backup creation refuses the snapshot; verification independently recomputes the
  report and refuses inconsistent content without repairing or deleting anything.
- Valid metadata Trash is preserved: active and trashed Projects, active and
  trashed shared artifacts, memberships, canonical relationships, revisions,
  attachments, prepared content, and external no-copy truth survive matched
  create, verify, extract, and restored-component verification.
- Existing archives remain readable. Original format-1 manifests without a
  recovery marker and contract-2 schema-8 archives retain their prior shape.
  Contract-2 schema-10 archives created during Gates 7A–7D may omit the new Project
  report keys but are accepted only after their actual contents independently pass
  the current Project-aware audit. Unsupported future markers fail closed.
- Schema 10, storage paths, artifact/revision identities, managed bytes, archive
  members, and operational matched-pair restore procedure are unchanged. No
  Project-export import, repair, schema contraction, ACL, push, tag, or publication
  was added.

## Regression-first evidence

The new recovery suite was first run against accepted Gate 7D recovery code. It
reported `11 failed, 11 passed`: new backups still emitted recovery contract 2,
all injected Project graph corruptions incorrectly returned `status: ok`, and a
future recovery-contract marker was accepted.

After the initial implementation, the recovery suite reached `21 passed, 1 failed`;
the remaining failure was the deliberately stale schema-8 assertion expecting a
new archive to use contract 2. Updating that assertion to the approved contract 3
made the suite green.

Final review then identified a compatibility case not covered by the first pass:
schema-9/10 backups could already have been created with recovery contract 2 during
Gates 7A–7D. The added pre-Gate-7E schema-10 contract-2 regression failed against
strict report equality with:

```text
RecoveryError: Backup database summary does not match its manifest
```

The verifier now treats no-marker and contract-2 reports as historical subsets,
while independently requiring the recomputed current audit to be `ok`. Contract 3
remains strict. The final focused recovery result is:

```text
25 passed in 3.79s
```

The combined recovery, schema migration, Gate-5 fixture, Project lifecycle/export,
relationship, Project, artifact Trash, and revision gate passed:

```text
73 passed in 16.20s
```

These tests supply corrupt SQLite inputs to the real audit rather than replacing
the function under test. They cover orphan membership Project/artifact references;
missing relationship Project/source/target references; non-member endpoints;
self-links; unsupported kinds; duplicate canonical tuples; and a missing required
schema-10 relationship table.

## Full verification

The untouched entry baseline at `b66b83f` passed `make verify` before changes:

- API: `132 passed`
- Web: `20 passed`; TypeScript and production build passed
- Bridge tests/build, Compose/security checks, schema-10 container smoke, and the
  immutable v5.1 release contract passed

After the final compatibility change, `make verify` passed on 2026-08-26 while
sleep was inhibited:

- API: `147 passed in 20.26s`
- Web: `20 passed`; TypeScript and production build passed in an explicit uncached
  invocation after the full gate reused its verified Docker layer
- Bridge: Go tests and build passed
- Canonical, deploy, compatibility, smoke, benchmark, and mount-scan Compose checks
  passed; production Compose still rejects missing authentication secrets
- Container smoke passed for direct and same-origin API access, security headers,
  the 512 MiB file policy, non-root API/web processes, and unchanged schema 10
- The immutable v5.1 release contract passed unchanged
- `git diff --check`, explicit staged-file review, and secret/debug marker checks
  passed; only the two intended API files entered the implementation commit

The existing frontend dependency-age and bundle-size warnings remain unchanged in
class and non-blocking. One initial focused command invoked the `pytest` executable
directly and produced eight collection errors because that bypassed the image's
normal `python -m pytest` module path. No product test ran in that attempt; the
corrected command produced the `73 passed` result above.

## Rollback and closeout boundary

Gate 7E has no database or filesystem migration. Code rollback leaves schema-10
Project, membership, relationship, artifact, revision, file, and byte state
unchanged. Newly created recovery-contract-3 manifests require a contract-3-aware
verifier; operational rollback remains restoration of a previously verified
matched SQLite/storage pair with services stopped.

The unrelated untracked desktop architecture note remained untouched. The owner
accepted this evidence and closed Gate 7 on 2026-08-26. Gate 8, push, tag, release,
publication, schema contraction, and Project-export import remain unauthorized
until separately opened or approved.
