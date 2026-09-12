# Gate 13C — current-image approval recorded

**Date:** September 12, 2026, America/New_York.
**Owner:** VincentCinque, repository maintainer.
**Status: E2/R52 APPROVED FOR LOCAL QUALIFICATION; H7 AND SECURITY CLOSEOUT OPEN.**

The owner's **“yes approved”** answers the explicit approval request for the
[current-image package](SECURITY_CURRENT_IMAGE_DECISION.md), including its BusyBox
evidence caveat. The new [immutable event](security-current-owner-acceptance-2026-09-12.json)
binds that decision to proposal commit `4af19f77b8acffd6db4361eb68834e3657d82045`
and proposal SHA-256
`00ddf6501acb6d863d0b8debc5ca4bd278369415a4879a14f331ecee84678335`.
The recording observation is **20:04:44 UTC**, not an invented message-click time.

| Decision | CVEs / package matches | Effect |
|---|---:|---|
| E2 | 2 / 3 | Accept exact-image required-component exclusions for CVE-2026-9538 and CVE-2026-89092 |
| R52 | 52 / 133 | Accept enumerated temporary local-qualification risks under C1–C7, including the BusyBox evidence limitation |
| F26 | 26 / 28 | Retain verified fix evidence; these are not risk waivers |
| H7 | 7 / 11 | Remain unaccepted; the approval permits bounded investigation, not additional exceptions |

This approval names only the existing **linux/amd64 development** images built
from application `6306ccff289d475530a6cacf4cb2e28db456ce08`:

- API: `sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96`
- Web: `sha256:0fcaf5a3e77873767b1359f468568eee514e6341267a17a32db339f3cc281c67`

All seven conditions in the proposal/event remain binding: canonical privilege
policy, production-style HTTPS and application guards, trusted operator recovery,
explicit writable-vault/native-corruption/data-loss/denial-of-service residuals,
and no automatic transfer to a rebuild, architecture, desktop or public candidate.
Approval does not make GNU tar or SQLite a hostile-input sandbox.

**Deadline:** no later than **October 12, 2026 at 00:00 America/New_York**, or
30 days after actual acceptance, candidate freeze/13D, or a C6 reopening trigger,
whichever comes first. Relevant fixes, changed advisories/callers/inputs/images,
missing evidence or weaker controls reopen the affected decisions immediately.
No renewal or extension of the earlier deadline is granted.

The owner explicitly acknowledges that current Alpine backport/fix status for
**CVE-2025-60876** could not be confirmed. Acceptance covers that documented
evidence gap for local qualification only; it is not a claim that no fix exists.
The R set's 44 High, 39 Medium, six Low and 44 Negligible package matches remain
explicit, as do all **189 API / 3 web raw scanner matches**. No suppression or new
image scan accompanies this event. The 17 interpreter CVEs remain separate.

The old E11/R59 event and all pending-proposal JSON stay unchanged. This is a new
explicit approval for the current exact images, not a silent transfer of old
waivers. The [approval checker](security-current-approval-check.cjs) validates all
54 selected IDs, seven excluded holds, 26 technical resolutions, immutable
proposal bytes and the preceding **197 private evidence hashes**. Run:

```text
node makervault/docs/evidence/gate-13/security-current-approval-check.cjs
```

The follow-up [bounded H review](SECURITY_HOLD_REVIEW.md) is technical investigation
only. Any additional exclusion, exception, package change or security closeout
needs its own evidence and informed decision. This approval does not close
S04/G13-04 or Gate 13C/13D, authorize publication/deployment, or restart deferred
performance tuning. Gate 12 remains deferred to desktop; frozen Gate 5 release
pins and model bytes remain unchanged. Nothing pushed, tagged or published.
