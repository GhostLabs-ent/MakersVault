# ADR 0003: Retire the legacy Asset.collection metadata field

**Status:** Accepted

**Accepted:** 2026-10-28

## Context

`asset.collection` is a free-text column introduced with the v5.1 metadata work
(migration 003), when a configurable storage template could group files by
collection. Since Mf-aoyv the template is applied only when an asset row is
created, and a metadata edit never relocates a managed file, so collection no
longer shapes where anything is stored.

The field also overlaps conceptually with Projects (Mf-d8hl): both are
user-facing groupings of assets, and the web client already calls a project a
"collection of files from any folder". A second, unrelated Collection field is
therefore active confusion rather than harmless legacy.

Verified facts at the time of this decision (main @ 106e326; code anchors
re-pinned during the Mf-p0g8 integration gate):

- Exactly one production write site exists: the metadata endpoint
  (`api/routers/assets.py:267-268`). An absent or null field leaves the column
  untouched; an empty or whitespace value clears it to NULL.
- No creation path sets it. `create_asset_record` (`api/asset_service.py:586`)
  and `library_scan.build_asset` (`api/library_scan.py:457`) are the only two
  `Asset(...)` constructions outside tests, and neither assigns collection.
  Upload, URL import, zip import, import-into-project, library scan and mount
  import all reach one of those two; no bulk endpoint, project endpoint or
  background job writes it.
- Because no creation path sets it, `{collection}` always renders the
  Uncollected fallback for new files (`api/asset_service.py:120`), and setting
  the field afterwards never moves bytes
  (`api/tests/test_asset_metadata_no_relocate.py`).
- The column and `idx_asset_collection` come from migration 003
  (`api/migrations.py:76,135`), and migrations 1-7 are immutable.
- ADR 0002 defers schema contraction to a later release with a tested restore
  path.
- Projects are a many-to-many membership (`project_asset`, migration 007)
  behind a case-insensitive unique project name. There is no tag table and no
  tag namespace: tags are substring-matched JSON arrays in `asset.tags_json`.

## Decision

Retire `Asset.collection` as a user-facing metadata field and keep it as a
deprecated compatibility field.

- The UI stops offering it: the asset details form no longer collects a
  collection, the settings token picker no longer offers `{collection}`, and the
  storage settings copy no longer advertises collections. A stored value is
  still shown read-only and labelled legacy so existing data stays discoverable.
- The API keeps accepting and returning it. `AssetMetaUpdate.collection` and
  `AssetOut.collection` remain accepted fields, marked deprecated in the
  OpenAPI schema, so an old client that posts a collection neither fails nor
  loses data.
- `collection` remains a valid storage-template token, so a stored template
  containing `{collection}` keeps validating and rendering. It leaves the
  advertised list only: it stays in `STORAGE_TEMPLATE_TOKENS`, is named in
  `DEPRECATED_STORAGE_TEMPLATE_TOKENS`, and is filtered out of `allowed_tokens`
  in `storage_settings_out()`.
- Free-text search keeps matching collection, so stored legacy values stay
  findable.
- No schema or data migration is performed: the column, its index and its data
  stay in place. Migrations 1-7 are immutable, and
  `MIGRATIONS[-1].version == 7` is unchanged.
- The column is not reused for Projects. Project membership is the
  `project_asset` join table; collection is never repurposed as a project id,
  tag or membership shortcut.

## Consequences

- No install loses data or breaks on upgrade, and no database migration is
  needed.
- Hand-typed collection values remain visible, searchable and writable only
  through the API. Grouping assets is Projects' job.
- The UI's "collection" again means one thing: a project.
- Because the field stays writable through the API, this is a deprecation, not a
  removal. Contracting the column is a separate, later decision.
- The valid-token list and the advertised-token list now differ by exactly one
  entry, and that divergence must stay deliberate.

## Alternatives considered

- Migrate distinct collection values into Projects. Rejected: the verified write
  surface means almost no install has values to migrate, and where it does they
  are a few hand-typed strings. An idempotent one-shot with a review-before-
  commit step, real project creation and case-insensitive name-collision
  handling against `idx_project_name_unique` is a sizeable feature spent on
  nearly empty data, and it does not end the problem because old clients can
  keep writing collections afterwards. Manual re-grouping into Projects is the
  migration path for the rare install that cares.
- Represent collection as a project tag. Rejected: there is no tag namespace to
  put it in. Tags are plain JSON arrays matched by substring, so a collection
  tag would appear as an ordinary user tag and pollute `GET /tags`, or need new
  schema for namespaced tags — disproportionate for inert metadata.
- Map collection values to project memberships at read time. Rejected: it
  invents groupings the user never confirmed and silently changes what Projects
  contain.
- Remove the field from the API and the database. Rejected: it fails old clients
  and requires the schema contraction ADR 0002 defers behind a tested restore
  path.

## Rollback

Nothing is transformed, so rollback is a code revert: restore the collection
input, the token chip, the settings copy and the API deprecation markers. Stored
values were never modified, so no data restore is needed.

## Verification

- `api/tests/test_storage_settings.py` asserts the advertised token list omits
  collection while a stored `{collection}` template still saves and reads back
  with 200.
- `api/tests/test_asset_metadata_no_relocate.py` pins the compatibility
  semantics: a posted collection persists, an absent key leaves the column
  alone, a blank value clears it, and no bytes move in any case.
- A test pins the deprecated markers in the OpenAPI document.
- A test pins that free-text search still matches a collection value.
- `makervault/web` tests pin that the details form no longer offers a collection
  and that the saved payload carries no collection key.
- `api/tests/test_adr_collection.py` binds this ADR to the runbook queue item
  and the truth ledger so the decision cannot silently rot.

## Superseding conditions

Revisit this ADR when schema contraction becomes available under ADR 0002's
tested restore path, when an install produces evidence that hand-curated
collection data should be converted into Projects, or when a namespaced tag
model exists that could absorb the field. Reusing the collection column for
Projects requires a superseding ADR; this decision forbids it.
