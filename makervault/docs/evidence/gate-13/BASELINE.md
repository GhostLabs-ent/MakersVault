# Gate 13 — end-state audit and re-cock

**Opened:** 2026-09-05, by owner direction

**Status:** IN PROGRESS; 13A accepted, 13B ready for owner evidence review

**Audit entry:** `236c0fd14faf6cddb7e46a78657e6000cdb4d79f`

**Latest application implementation:** `1a209aa8711b1717aa4400d25cd269953eb1357a`

**Current verification implementation:** `2c68d70dcf36e9e912a6caf23fa33026c7a665bb`;
complete verification passed. See [13B results](SUBGATE_13B_RESULTS.md).

## Objective and authority

Reconcile the strategy promises with current behavior, repeatable evidence, and
explicitly owned remaining work. Do not equate accepted implementation gates with
a newly qualified release. This opening slice inventories the end state and runs
the existing safe verification before changing any application or test harness.

The owner accepted Gate 11E-1 and deferred Gate 12 to desktop on 2026-09-05, then
authorized Gate 13. This permits local audit and verification. It does not approve
a replacement release candidate, a new feature/trust boundary, external services,
deployment, push, tag, or publication. The unrelated untracked
`docs/MakersVault_Desktop_Architecture.md` is excluded and remains untouched; the
desktop deferral is recorded here without treating that draft as accepted design.

## Verified entry conditions

| Boundary | Entry truth |
|---|---|
| Source | Clean tracked tree at `236c0fd`; only the unrelated desktop draft is untracked |
| Accepted delivery | Gates 0–11 including 11E-1a–1d have owner acceptance in the runbook/evidence history |
| Frozen candidate | Gate 5 source `f6ff55b33fd64c7a5037e8eb642bed048c3e0e4f`, schema 5, remains the qualified unpublished v5.1 candidate |
| Current application | Later local schema 17; raw backup outer format 1 / recovery contract 6 |
| Portability | `.mvault` v1 exports supported schema 12–17 content and reconstructs schema 12; it does not transfer authentication or deployment state |
| Hosting | One shared vault, one API process, local content store, fixed roles; no object tenancy or provider connection |
| Gate 12 | Owner-deferred to desktop; free-core and non-lock-in commitments continue now |

## Sequential execution

These are audit slices of Gate 13, not new feature gates. Pause for owner review at
each slice and whenever the runbook's authority checkpoints apply.

| Slice | Work | Exit evidence / owner checkpoint |
|---|---|---|
| **13A — baseline and truth inventory** | Re-run the existing repository gate; trace product/invariant/security commitments; identify stale harnesses and incomplete proof | Named baseline, [traceability](TRACEABILITY.md), [security ledger](../../security/GATE_13_REVALIDATION.md), and [results](SUBGATE_13A_RESULTS.md). Owner reviews findings before 13B |
| **13B — current-build lifecycle and harness qualification** | Refresh legacy JWT/schema-5 verification for cookie/CSRF/schema-17 behavior without weakening production policy; exercise upgrade, raw restore, rollback, and portable clean-import/startup in disposable projects | Supported-origin fixtures and named local images; complete bytes/graph preservation; restored sessions/challenges invalidated before exposure; new-instance bootstrap after portable import; failure/interruption proofs; old candidate evidence preserved |
| **13C — user workflows and release-readiness evidence** | Repeat preview, organization, mounted-import, and browser workflows on the audited current build; review operator commands/TLS posture and fresh dependency advisories; collect real-device/platform evidence or explicit owner dispositions | No historical timing reused as a current result; exact browser/build/fixture records; security residuals assigned. Owner chooses release revision/scope before candidate assembly or any publication work |
| **13D — end-state acceptance and next roadmap** | Reconcile all ledgers/docs, explain every unmet commitment, freeze evidence, and propose the next Gate-0-style cycle | Owner accepts the achieved end state and the re-baselined roadmap; Gate 12 remains a desktop carry-forward, not delivered work |

## Assumptions to test, not acceptance evidence

- Older end-to-end scripts can qualify schema 17 unchanged: **disproved by source
  audit at 13A entry**. 13B repairs the authentication/schema contracts. Current
  browser matrix and release qualification remain 13C. See findings G13-01–03.
- Passing focused tests plus a fresh install proves a full current production
  upgrade/restore: **not established by that evidence alone**; 13B's joined
  production-HTTPS operator sequence now passes on named local development images.
- A portable content round trip proves restored schema-17 login: **not
  established by that evidence alone**; v1 reconstruction intentionally stops at
  schema 12. 13B separately proves schema-17 startup with new identity only.
- The current feature set belongs in the frozen v5.1 release: **not decided**.

## Data, security, migration, and rollback

13A changes documentation only. Verification uses generated fixtures, disposable
test containers, and the existing project-scoped smoke/passkey volumes; cleanup
removes only those test resources. No user vault, live installation, external
account, or desktop bridge configuration is modified. Schema and stored bytes do
not change. Documentation can be reverted by an ordinary local revert.

13B must retain stop/backup/verify/restore as a matched SQLite/storage workflow.
It must not bypass cookie security, add JWT compatibility, use a populated target,
or rewrite the historical Gate 5 qualification to make a new test pass.

## Acceptance state

Gate 13's required clean install, representative upgrade, disaster restore,
portable export/import, trust-boundary review, and complete traceability remain
individually tracked in [13A results](SUBGATE_13A_RESULTS.md) and supplemented by
[13B lifecycle results](SUBGATE_13B_RESULTS.md). Partial evidence is
labelled by layer. No unresolved goal is accepted by omission, and an owned
carry-forward is not a claim that its implementation or tests exist.

**Accepted by/date:** Pending. Opening Gate 13 is not acceptance of its end state.

**Current owner direction:** 13A was accepted at `c2e9f94` and 13B's bounded
verification repairs and lifecycle drills were authorized on 2026-09-05. Keep
Gate 12 on the desktop track and publication behind its separate explicit decision.
13B is ready for review; wait for owner acceptance/direction before starting 13C.
