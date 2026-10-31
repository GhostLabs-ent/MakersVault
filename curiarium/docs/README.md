# Documentation index

What is authoritative, what is historical, and what to read when.

## Authoritative — describes the product as it is now

| Document | Read it for |
|---|---|
| [ARCHITECTURE_RUNBOOK.md](ARCHITECTURE_RUNBOOK.md) | How the system fits together, failure modes, recovery and upgrade procedures |
| [architecture/CONFIGURATION.md](architecture/CONFIGURATION.md) | Every environment variable: default, owner, effect |
| [architecture/REVERSE_PROXY.md](architecture/REVERSE_PROXY.md) | Exposing one hostname, header and body-size requirements |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Local toolchains, the gates, migration rules |
| [adr/](adr/) | Decisions with their rationale — read these before changing a design |
| [../docs/PERMISSIONS.md](../docs/PERMISSIONS.md) | The role matrix, per route |
| [../docs/AUDIT.md](../docs/AUDIT.md) | Which actions are audited and why some are exempt |
| [../docs/TICKET_WORKFLOW.md](../docs/TICKET_WORKFLOW.md) | How work is gated and landed |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | For a new contributor: where documents and figures go, ADR rules, the gates — start here |
| [../AGENTS.md](../AGENTS.md) | Repo map, commands, guardrails |
| [../README.md](../README.md) | What the product is, quick start, configuration highlights |

### Architecture decision records

| ADR | Decision |
|---|---|
| [0001](adr/0001-canonical-compose-manifests.md) | Canonical compose manifests; the historic filename is an alias |
| [0002](adr/0002-versioned-sqlite-migrations.md) | An append-only, versioned SQLite migration ledger |
| [0003](adr/0003-retire-asset-collection.md) | `Asset.collection` is retired, not migrated, and never reused for projects |
| [0004](adr/0004-token-and-cookie-threat-model.md) | Token and cookie threat model |
| [0005](adr/0005-file-grant-urls.md) | File URLs carry short-lived, file-scoped grants |
| [0006](adr/0006-oidc-sso-flow-and-role-policy.md) | OIDC flow and the rule that claims can never mint an admin |
| [0007](adr/0007-session-lifecycle-and-refresh-replay.md) | Session lifecycle, refresh grace window, replay as compromise |
| [0008](adr/0008-mfa-totp-enrolment.md) | TOTP enrolment, recovery codes, the admin MFA policy |

## Historical — kept for provenance, describes an earlier project

These were written for upstream's v5.1 gate process, before this fork diverged. They are
useful as archaeology and for the reasoning they preserve; they are **not** a description
of the current system, and their counts, schemas and roadmap are stale.

| Document | What it was |
|---|---|
| [archive/V5.1_SCOPE.md](archive/V5.1_SCOPE.md) | Upstream's v5.1 release contract |
| [archive/ROADMAP.md](archive/ROADMAP.md) | The v5.x roadmap as planned at the fork point |
| [archive/PRODUCT_STRATEGY.md](archive/PRODUCT_STRATEGY.md) | Product strategy for a multi-user service — superseded by the household scope |
| [archive/SUSTAINABILITY.md](archive/SUSTAINABILITY.md) | Sustainability and funding notes |
| [archive/Curiarium_v5.1_Competitive_Strategy(1).md](archive/Curiarium_v5.1_Competitive_Strategy(1).md) | Competitor survey |
| [archive/Curiarium_v5.1_Security_Analysis.md](archive/Curiarium_v5.1_Security_Analysis.md) | The long-form security analysis that seeded the hardening work |
| [archive/security/GATE_0_REVALIDATION.md](archive/security/GATE_0_REVALIDATION.md) | Security findings ledger from Gate 0 |
| [archive/evidence/gate-0/](archive/evidence/gate-0/) | Gate 0 baseline and results records |
| [archive/Curiarium_GitIgnore_Audit.md](archive/Curiarium_GitIgnore_Audit.md) | The repository-ownership audit that removed 8,311 generated paths from git |

## Other

| Path | Contents |
|---|---|
| [../docs/images/](../docs/images/README.md) | Documentation figures, by topic — naming, sizes and the redaction rules a public repository requires |
| [../docs/brand/](file://../docs/brand/) | Brand sources: the AI reference, the originally supplied SVG, generated SVGs, and `build.py` which regenerates every asset |
| [../curiarium/api/tests/fixtures/prepared/](file://../curiarium/api/tests/fixtures/prepared/) | Fixtures for the prepared-print parser tests |
| [../curiarium/slicer-bridge/README.md](../curiarium/slicer-bridge/README.md) | Bridge installation and protocol |

## Keeping this honest

Docs in this repo have drifted in predictable ways: version numbers, schema versions,
route counts, and image names. When you change behaviour, grep for the number you just
changed before you close the ticket. `make verify-version` guards the product version;
nothing guards the rest, so it is a review responsibility.
