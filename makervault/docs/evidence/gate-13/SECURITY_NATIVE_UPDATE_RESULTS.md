# Gate 13C — approved six-package native update

**Date:** September 12, 2026, America/New_York.
**Implementation:** local commit `6306ccff289d475530a6cacf4cb2e28db456ce08`.
**Status: IMPLEMENTATION VERIFIED; SCANNER/VENDOR DISAGREEMENT AND NEW ADVISORIES OPEN.**

**Historical checkpoint:** the subsequent [vendor/byte reconciliation](SECURITY_RECONCILIATION_RESULTS.md)
verifies all 20 targeted and six newly seen PCRE2 CVEs as fixed in these same
installed packages. Its current dispositions supersede the pending conflict/PCRE2
recommendations below; this record and its raw scan remain unchanged evidence.

The owner's “approved” authorizes the bounded implementation proposed at
`1b83d43` in [the preceding checkpoint](SECURITY_OWNER_ACCEPTANCE.md). It does not
authorize transfer of old-image risk approvals, a distribution migration, additional
waivers, publication or Gate 13C/13D acceptance.

## What changed

The shared API test/runtime base now consumes
[`api/native-packages.lock`](../../../api/native-packages.lock). Signed configured
Debian repositories supplied exactly these six existing binary packages:

| Package | Previous installed version | New installed version |
|---|---|---|
| gzip | `1.13-1` | `1.13-1+deb13u1` |
| libc-bin | `2.41-12+deb13u3` | `2.41-12+deb13u4` |
| libc6 | `2.41-12+deb13u3` | `2.41-12+deb13u4` |
| libpcre2-8-0 | `10.46-1~deb13u1` | `10.46-1~deb13u2` |
| libsqlite3-0 | `3.46.1-7+deb13u1` | `3.46.1-7+deb13u2` |
| perl-base | `5.40.1-6` | `5.40.1-6+deb13u1` |

The signed-index/simulation probe ran in a disposable old-image container at
**16:39:08–16:39:22 UTC**, before implementation. APT proposed **6 upgraded,
0 newly installed, 0 removed**, leaving six unrelated available updates untouched.
The build pins exact versions, disallows unauthenticated packages/removals, uses
`--only-upgrade --no-install-recommends`, and rejects index errors. No repository,
signing key or global package exemption changed. Missing pinned versions fail the
build; this is not an automatic broad operating-system upgrade.

Complete installed inventories agree between the new test and exact runtime
images. Comparison with the old API finds **only those six version changes**, no
added or removed package. The old-image negative control fails all six new pins,
while both updated-image probes pass. Two new static contract tests protect the
bounded lock and shared-stage/install restrictions.

Python 3.11.16, its pinned base digest, seven language locks, schema 17, web source,
Compose/entrypoint privilege policy, recovery implementation, ownership/volume
behavior and model bytes remain unchanged. No end-user configuration or thumbnail
work is introduced. The frozen Gate 5 source/release pins remain untouched.

## Verification and exact identities

| Check | Result |
|---|---|
| Focused native contracts | 2 passed; old-image installed-pin probe fails as expected |
| Complete API suite | 424 passed / 144.30 seconds |
| Web re-execution | 58 passed; type check and production build also pass |
| Full `make verify` | Exit 0 / 275.480 seconds, clean implementation source |
| Harnesses / bridge | 25 Python and 28 Node harness tests; Go tests/build pass |
| Exact-image containment matrix | 8 startup/ownership cases and 6 capability-removal negative controls pass |
| HTTPS lifecycle | Schema 4 → 17 upgrade; raw recovery contract 6; portable 17 → 12 → 17; exact stopped schema-4 rollback; fresh install and refusal paths pass |

The successful full run is **16:48:29–16:53:04 UTC**. Recovery includes pre-start
session/challenge revocation, startup audit, 18 compared portable members,
nonempty/corrupt archive refusal, external-source preservation and generated-preview
persistence across restart. Actual API and Nginx processes have nonzero UIDs,
five empty capability sets and no-new-privileges. This remains trusted operator
recovery, not a hostile SQLite/GNU tar sandbox; writable vault and denial-of-service
risks remain explicit. Virtual passkeys are not physical-device qualification.

These **linux/amd64 development** images are labelled `development-gate13b` /
`6306ccf`, not a public candidate:

- API: `sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96`
- Web: `sha256:0fcaf5a3e77873767b1359f468568eee514e6341267a17a32db339f3cc281c67`

All builds finished before starting the exact-image audit. Runtime, CLI/symbol and
installed-package probes name the successful lifecycle API ID. The observed
Python/Perl modules, 64-bit architecture, SQLite FTS5/SESSION capabilities, absent
zipdetails, SQLite apply/apply_v2 presence and apply_v3 absence equal the prior
observations. A package backport need not change SQLite's upstream `3.46.1` string.
None of those bounded observations excludes all native library code.

The first full-run attempt is **incomplete**, not a pass: the lean-ctx outer wrapper
hit its 120-second limit and no capture completion record survived. Partial logs
are retained. After confirming no verification process remained, only that attempt's
orphaned smoke-test container and disposable project volumes were removed. The
complete sequential rerun used the existing private capture helper directly to
avoid the wrapper timeout; no allowlist or security setting was weakened.

## Fresh audits and per-CVE disposition

Language audits completed **16:44:54–16:45:35 UTC**: npm full/production/organization/
preview **0/0/0/0**, Python runtime/development/build **0/0/0** across **35/43/2**
dependencies with none skipped, and Go symbol-level **0** findings. All seven
language locks are unchanged. The old image arguments recorded in this phase are
unused placeholders, not scans of those images.

The exact-image phase completed **16:53:59–16:57:58 UTC**. Grype 0.118.0 used valid
schema-6.1.9 data built **September 12 at 06:27:25 UTC**, with the Debian feed
captured at 00:30:55 UTC. This is newer than the September 10 baseline database.

| Inventory | Prior | Current |
|---|---:|---:|
| API package matches / unique CVEs | 181 / 96 | **189 / 103** |
| Web package matches / unique CVEs | 3 / 1 | **3 / 1** |
| Total matches / unique CVEs | 184 / 97 | **192 / 104** |

API severity labels remain **7 critical**, with **62 high, 55 medium, 12 low,
45 negligible and 8 unknown**; web has three medium matches. Nothing is suppressed
or subtracted. All earlier advisory/package pairs remain. Sixty-three reduced API
records change only installed package versions or package-evidence paths; eight
added matches represent seven newly seen CVEs. Web's reduced records and the
17 separate S02/S03 interpreter matches are unchanged. There was no old-image
rescan with the new database, so newly seen is **not** proof of patch-induced exposure.

For all **20 targeted CVEs**, retained September 12 Debian fixed-version rows equal
the signed installed binary pins, but Grype still reports matches with no fixed
version and an unknown version constraint. A fresh browser read of
[CVE-2026-5450](https://security-tracker.debian.org/tracker/CVE-2026-5450) reconfirms
Debian's `2.41-12+deb13u4` fixed row while this scanner reports both installed libc
packages. The timing is consistent with feed lag, but does **not** prove its cause
or justify an automatic false-positive classification. Installed Debian changelogs
are absent in this slim image; the follow-up probe does not supply source/backport
confirmation from them. Preserve the conflict and obtain an explicit reviewed
disposition; do not claim 20 scanner CVEs removed or seven critical matches cleared.

The [joined per-CVE record](security-native-verification.json) separately records:

- **20 original IDs:** vendor-fixed versions installed, scanner disagreement held
  (ten former E, seven reopened R and three former H entries).
- **52 original R and one original E:** unchanged bounded rationale/preconditions
  revalidated, but a new exact-image owner decision is pending under C1/C6.
- **Seven original H:** 19499, 19542, 77117, 80489, 39113, 50812 and 85091 remain
  unresolved/unaccepted; prior evidence limits are unchanged.
- **Seven newly seen native IDs:** reviewed below; no inherited acceptance.

All abbreviated IDs in this report are CVE-2026. Fresh exact-image probes still
confirm all eleven former E preconditions, including the ten also in the vendor-fix
conflict group. That is applicability evidence, not a transfer of their old-image
approval. Original events and deadline **October 12 00:00 America/New_York**, or
earlier freeze/13D/C6 trigger, remain immutable; no renewal or extension is granted.

### Newly seen native advisories

| CVE | Bounded review | Current recommendation |
|---|---|---|
| [89092](https://security-tracker.debian.org/tracker/CVE-2026-89092) | Vendor requires nscd; exact API has no nscd package-manifest match or named executable. Two libc matches retained | Narrow component-precondition exclusion proposed, not accepted |
| [89156](https://github.com/PCRE2Project/pcre2/security/advisories/GHSA-2p8c-ff85-vh9x) | Present 8-bit PCRE2; invalid UTF plus specific JIT fallback conditions | Hold native caller/backport review; no direct application caller found, not an indirect-call exclusion |
| [89157](https://github.com/PCRE2Project/pcre2/security/advisories/GHSA-q8g2-wprr-34m9) | Upstream 32-bit size_t conversion issue; observed size_t is 8 bytes. Vendor describes 64-bit as believed unaffected | Qualified exact-architecture exclusion proposed, not accepted |
| [89158](https://github.com/PCRE2Project/pcre2/security/advisories/GHSA-fmgr-6ggq-9859) | Upstream compile_32 overflow on 32-bit systems; inspected process is 64-bit and only PCRE2's 8-bit library is found | Narrow architecture/component exclusion proposed, not accepted |
| [89160](https://github.com/PCRE2Project/pcre2/security/advisories/GHSA-9qww-pwc4-77qq) | Invalid-UTF matching path; installed native library remains present | Hold native caller/backport review |
| [89161](https://github.com/PCRE2Project/pcre2/pull/937) | Fast-path JIT invalid free involving previously copied subject | Hold native caller/backport review |
| [89162](https://github.com/PCRE2Project/pcre2/security/advisories/GHSA-q7rw-r7qq-2hx6) | Serialization can disclose uninitialized bytes | Hold native caller/backport review |

Primary upstream pages identify fixes in
[PCRE2 10.48](https://github.com/PCRE2Project/pcre2/releases/tag/pcre2-10.48).
This does not establish a supported Trixie backport or authorize installing that
upstream release. PCRE2 code-unit width is not process width. API/scripts/bridge
text searches found no direct `pcre2_` or `nscd` reference; they do not examine every
native dependency/operator call. No exploit, vulnerable native function or hostile
input was executed. The new read-only probe ran **17:00:53–17:00:54 UTC**.

The six new PCRE2 Debian page reads were unavailable through the browser and were
not retried via another route. Successful primary upstream page reads are dated
browser evidence, not separately archived bodies. CVE-to-GHSA mappings are retained
scanner related-vulnerability links; some upstream pages still say no known CVE.
These limitations are explicit in every new machine record.

## Evidence boundary

Raw commands, identities, inventories, scanner reports and logs are private under
`~/.local/state/makersvault/verification/containment-native-*`; sanitized joined
evidence is committed separately. Probe-only read-only/network/capability flags
are not newly shipped resource limits. Historical private evidence and immutable
owner events are preserved; unavailable older temporary artifacts are not recovered.

Run `node makervault/docs/evidence/gate-13/security-native-analysis.cjs` from the
repository root. It joins **15 completed captures plus the interrupted attempt**,
checks **167 private hashes**, exact identities/platform, six-package inventory
delta, historical immutable inputs, language locks, full lifecycle/containment,
all 80 original native IDs and the seven-ID scan delta. Its “passed” means evidence
consistency, **not** scanner cleanliness, new owner acceptance or release clearance.
Historical containment/approval checkers bind the old Dockerfile and intentionally
do not qualify changed source. Use this new checkpoint without rewriting old JSON.
Final Node syntax, **209 local documentation links**, static release contract and
`git diff --check` also pass.

**Next bounded checkpoint:** accept the verified six-package implementation,
then reconcile the 20 scanner/vendor disagreements and the new PCRE2 backport/caller
questions before proposing additional packages or renewed exact-image dispositions.
Do not silently carry the old waivers, upgrade to unstable, strip native libraries
or repeatedly rebuild merely to seek a clean count. The seven original H entries
and four newly held PCRE2 entries remain unaccepted alongside these review tasks.

Performance G13-01 and desktop Gate 12 remain deferred. Remaining security decisions,
real-platform/operator/release readiness and Gate 13D remain separate checkpoints.
Nothing was pushed, tagged, published or deployed.
