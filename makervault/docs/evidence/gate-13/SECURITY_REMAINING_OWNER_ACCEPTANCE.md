# Gate 13C — remaining-five approval recorded

**Date:** September 12, 2026, America/New_York.
**Owner:** VincentCinque, repository maintainer.
**Status: LOCAL NATIVE DISPOSITIONS COMPLETE — E4/R57/F26/H0; RELEASE GATES OPEN.**

The owner's **“Yes approved”** accepts the five temporary local-risk exceptions
in the [decision package](SECURITY_REMAINING_DECISION.md), under unchanged C1–C7
conditions and the October 12-or-earlier deadline. The
[append-only event](security-remaining-owner-acceptance-2026-09-12.json) binds the
proposal and prior decisions to commit `acaa4f6a46fedaebb48187c04366e53ee795c2ec`
through four artifact hashes. Its **22:32:12 UTC** recording observation is the
first clock read for this approval turn, not an invented message-click timestamp.

Only **CVE-2026-19499, CVE-2026-19542, CVE-2026-50812, CVE-2026-77117 and
CVE-2026-80489** move from H to R. These findings are **accepted risks, not fixes
or exclusions**. Native memory corruption, potential code execution, data loss,
information disclosure, denial of service, incomplete native-call applicability
and the SHIFT/EUC converter-mapping disagreement remain explicit. Existing
BusyBox and other earlier caveats are unchanged.

## Exact scope and current register

Scope remains application `6306ccff289d475530a6cacf4cb2e28db456ce08`, existing
**linux/amd64 development** images only:

- API: `sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96`
- Web: `sha256:0fcaf5a3e77873767b1359f468568eee514e6341267a17a32db339f3cc281c67`

| Native disposition | CVEs | Meaning |
|---|---:|---|
| E | 4 | Previously accepted exact-image exclusions; unchanged |
| R | 57 | 52 earlier exceptions plus these five temporary local-risk exceptions |
| F | 26 | Verified fixes; unchanged and not risk waivers |
| H | 0 | No pending owner dispositions in this dated local native register |

All 87 native IDs reconcile. H0 does not mean zero vulnerabilities: the retained
**189 API / 3 web raw scanner matches** and separate interpreter dispositions stay
unchanged. The three current-image approval events account for 61 unique decisions;
the 26 fixes are separate technical resolutions. Earlier proposal/approval JSON
and dated vendor/runtime observations remain immutable.

All C1–C7 controls remain binding: canonical runtime privileges, HTTPS and
application guards, trusted operator recovery, explicit writable-vault/native
residuals, and local-qualification-only authority. Deadline: **October 12, 2026 at
00:00 America/New_York**, or 30 days after actual acceptance, candidate freeze/13D
or a C6 reopening trigger, whichever comes first. Relevant fixes, changed
advisories/callers/inputs/images/platforms, missing evidence or weakened controls
reopen the affected decisions. No extension, automatic renewal or transfer to a
rebuild, another architecture, desktop or public candidate.

## Next checkpoint

Proceed next to the remaining **local platform/operator qualification** in
[13C](SUBGATE_13C_RESULTS.md) and its [traceability register](TRACEABILITY.md).
Identify which checks can run locally and which require a real workstation or
owner input; unavailable platform evidence stays open, not assumed passed.

This approval does not select a replacement release candidate or close
S04/G13-04, Gate 13C or Gate 13D. Candidate freeze/rebuild requires renewed
exact-image security qualification and explicit release decisions. The frozen
Gate 5 candidate stays unchanged; push, tag, publication and deployment remain
separately gated. Performance tuning stays deferred, and Gate 12 stays deferred
to desktop. No new feature work or package migration is authorized by this event.

## Verification

Run the [read-only approval checker](security-remaining-approval-check.cjs):

```text
node makervault/docs/evidence/gate-13/security-remaining-approval-check.cjs --self-test
```

It revalidates 222 private evidence hashes, four committed artifact hashes, the
exact five-ID approval, unchanged conditions/images/deadline, all three approval
events and the 87-ID partition. Six in-memory negative controls reject a wrong
ID, fabricated fix, changed image, extended deadline, release-authority expansion
and altered proposal hash. Links and the contiguous runbook truth table are checked.
This validates recorded decisions and retained evidence, not automatic continuing
exception validity after a deadline or reopening event.

The approval check and six negative controls pass, including **285 local links**.
Node syntax and the static v5.1.0 release-contract check also pass; neither is a
full application regression or release-qualification run.

No new advisory fetch, runtime probe, full application suite or image scan is
claimed in this approval turn. No application, dependency, image, schema, frozen
release pin or model byte changed. The owner's unrelated roadmap additions and
desktop document remain untouched outside the local security commit. Nothing
pushed, tagged, published or deployed.
