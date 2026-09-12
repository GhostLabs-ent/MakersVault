# Gate 13C — two additional exclusions approved

**Date:** September 12, 2026, America/New_York.
**Owner:** VincentCinque, repository maintainer.
**Status: E4 / R52 / F26 / H5; SECURITY CLOSEOUT REMAINS OPEN.**

**Subsequent investigation:** the [five-hold package](SECURITY_REMAINING_DECISION.md)
now proposes temporary local risk exceptions. That proposal accepts none of H5
and does not change this two-exclusion event or its conditions.

The owner's **“approved”** answers the explicit request to accept only
**CVE-2026-39113** and **CVE-2026-85091** under the existing conditions and unchanged
October 12-or-earlier deadline. The [append-only decision event](security-hold-owner-acceptance-2026-09-12.json)
binds the [source review](SECURITY_HOLD_REVIEW.md), its machine evidence and the
earlier approval/proposal to commit `00f707d8b3adddae9c33b7a659dd04d6737ddc1d`
using four artifact hashes. The recording observation is **20:27:22 UTC**, not an
invented message-click time. Earlier JSON proposals and approval events are unchanged.

| Approved transition | Exact API package | Evidence boundary |
|---|---|---|
| CVE-2026-39113: H → E | libsqlite3-0 `3.46.1-7+deb13u2` | Reviewed source lacks the later SQLar size-conversion change; no active patch introduces it |
| CVE-2026-85091: H → E | zlib1g `1:1.3.dfsg+really1.3.1-1+b1` | Reviewed source lacks the later nonblocking-write implementation; no active patch introduces it |

These are exact-image source-precondition exclusions, **not installed fixes** or
whole-library safety claims. The September 12 review records Debian marking both
sources affected; that disagreement and both raw matches remain visible. No new
vendor lookup or source/runtime probe was made to record this approval.

The scope remains application `6306ccff289d475530a6cacf4cb2e28db456ce08`, existing
**linux/amd64 development** images only:

- API: `sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96`
- Web: `sha256:0fcaf5a3e77873767b1359f468568eee514e6341267a17a32db339f3cc281c67`

All [C1–C7 conditions and the earlier E2/R52 decision](SECURITY_CURRENT_OWNER_ACCEPTANCE.md)
remain unchanged, including the BusyBox evidence caveat and local-qualification-only
authority. The deadline remains **October 12, 2026 at 00:00 America/New_York**, or
30 days after actual acceptance, candidate freeze/13D, or a C6 reopening trigger,
whichever is earlier. There is no renewal, extension or transfer to rebuilt images,
another architecture, desktop or a public candidate.

## Current register and remaining work

The combined 87-native-CVE register now has **four accepted exclusions, 52 accepted
temporary local-qualification risks, 26 verified fixes and five unaccepted holds**.
The holds are **CVE-2026-19499, CVE-2026-19542, CVE-2026-50812, CVE-2026-77117 and
CVE-2026-80489**. Their source/advisory gaps and exit criteria remain in the source
review; unknown applicability is not an exclusion. This approval accepts none of
those five and authorizes no additional package change or distribution migration.

Next work is authoritative resolution of those five, or a separately proposed,
informed owner disposition. Do not retry the previously unavailable public pages
without a changed access condition. Platform/operator/release readiness also
remains unfinished. S04/G13-04 and Gate 13C/13D are **not closed**; performance tuning
and Gate 12 retain their existing deferrals.

## Verification

Run the [read-only decision checker](security-hold-approval-check.cjs):

```text
node makervault/docs/evidence/gate-13/security-hold-approval-check.cjs --self-test
```

It revalidates 205 retained private evidence hashes, the four committed proposal
artifacts, exact two-ID scope, unchanged images/conditions/deadline, the complete
87-ID partition and local documentation links. Six in-memory negative controls
reject an extra approval, changed image, extended deadline, weakened condition,
changed artifact hash and omitted hold. No file is modified by the checker.

The decision check and all six negative controls pass, including **263 local
documentation links**. Node syntax and the static v5.1.0 release-contract check
also pass. These validate the recorded decision and retained evidence, not
automatic continued exception validity after a deadline or reopening trigger.

No new full application suite or scanner run is claimed. The retained inventory
stays **189 API / 3 web raw matches**, with interpreter dispositions unchanged.
No application, dependency, image, schema, frozen release pin or model byte changed.
The owner's unrelated roadmap additions and desktop document are preserved outside
this local security commit. Nothing pushed, tagged, published or deployed.
