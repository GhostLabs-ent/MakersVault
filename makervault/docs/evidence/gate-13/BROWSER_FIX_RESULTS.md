# Gate 13C — approved browser corrections

**Status:** implementation and qualification in progress; not Gate 13C acceptance.
Owner authorized the diagnosed corrections with “Okay please go ahead.” All work
remains local. Frozen Gate 5 release pins and the deferred Gate 12 scope are unchanged.

## Bounded changes

- Grid requests now belong to a specific active view and applied query. A newer
  refresh invalidates older asset/tag and pagination results, errors and loading
  updates. View cleanup invalidates departed requests. Pagination uses the applied
  filter, not unsubmitted search text; current authorization failures still work.
- Disposable HTTPS uses a unique CA plus a separate server-authentication leaf.
  Firefox installs the public CA through its startup environment policy. Browser
  and Node preflight require valid-host success and wrong-host certificate failure;
  no certificate bypass, host trust change or production-authentication change.
- First-card timing records browser-side visible layout at an animation frame,
  retaining the old locator-wait duration separately. Navigation and automated
  login are still included and the Chromium <1000 ms budget is unchanged. This is
  not a claim about physical screen presentation or hardware acceleration.

The prior diagnosis reproduced the stale grid with a delayed asset response and,
independently, with only delayed tags. The restored record remained present in
the API. Firefox required **both** a valid leaf and policy selection before startup.
Locator retry time inflated the first-card measurement in controlled samples;
that does not explain every earlier millisecond or erase historical failures.

Historical [attempts A–D](BROWSER_WORKFLOW_RESULTS.md) remain intact. Private local
diagnostics are at `/tmp/makersvault-browser-diagnosis-20260907-a/DIAGNOSIS.md`;
the surrounding private fixture directory is not a publishable evidence bundle.

## Verification plan / current truth

Focused web and harness checks pass. New coverage includes six request-ownership
unit tests, five browser visibility-probe unit tests and three certificate tests.
The deterministic real-browser fixture exercises seven request-order cases,
including stale and current authorization handling. These browser assertions are
implemented but are **not yet claimed as executed** at this checkpoint.

Next: commit the implementation locally, run the complete repository gate, then
run the browser matrix against the exact immutable lifecycle images. Retain every
failed attempt and inspect preview budgets separately from harness exit success.
Record source/image identities, actual totals, measurements and any remaining
blockers here before requesting owner acceptance. G13-04 residual image findings
and the remaining release/platform decisions are not waived by these corrections.
