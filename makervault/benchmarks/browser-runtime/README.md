# Disposable Gate 13 browser runtime

Build locally from this directory's Dockerfile; this is verification tooling, not
a shipped MakersVault image:

```sh
docker build -t makersvault-gate13-browser makervault/benchmarks/browser-runtime
python3 makervault/scripts/gate13-browser-workflows.py \
  --api-image <immutable-api-image-id> --web-image <immutable-web-image-id> \
  --version <matching-image-version> --revision <matching-image-revision> \
  --browser-image makersvault-gate13-browser --output <new-private-output-directory>
```

The runner requires committed verification sources, validates image labels and
records application and harness revisions separately. Every case gets a uniquely
named production-HTTPS stack, isolated database/storage, fixture credentials and
new fixture CA and separate CA:FALSE server-authentication leaf certificate. No
user library or existing Compose project is used. Only the public CA certificate
is mounted into the browser container, never either private key. The TLS proxy
receives only its leaf, leaf key and configuration, not the fixture signing key.
Certificate trust is confined to disposable containers. A preflight verifies both
successful fixture HTTPS and rejection of a mismatched hostname, in the browser
and Node client. No certificate-error bypass or host trust-store change is used.

The pinned Playwright image supplies Linux headless Chromium, Firefox and WebKit.
Its small NSS tools addition uses the signed Ubuntu repository. Chromium's NSS
CA trust and Firefox's certificate-install policy follow their documented Linux
trust mechanisms; WebKit uses the container trust store. Playwright's patched
Firefox selects the container-local policy through
`PLAYWRIGHT_FIREFOX_POLICIES_JSON` before startup. Setting the alternate policy
path through `firefoxUserPrefs` was too late, and serving the old CA certificate
as a leaf was independently invalid for Firefox. The old failed attempts remain
in the evidence history. No certificate validation setting is disabled. See the
[Playwright launch environment documentation](https://github.com/microsoft/playwright/blob/main/docs/src/api/params.md).
This is not native Safari,
Windows/macOS, mobile or hardware-passkey coverage.

Browser limits are 4 GiB memory and 1 GiB shared memory, with no CPU cap. Benchmark
sources and corpus are read-only. Locked npm packages install into disposable
anonymous volumes; reports go to a new private directory. The runner cleans up
only its own containers, including after timeouts. Mounted-import cases also
check that every fixture source byte and the rejected symlink remain unchanged.

Organization runs all three engines and retains its existing assertions/budgets;
request-order regressions, preview and mounted-import workflows use Chromium.
The `folder-picker` workflow runs all selected engines with real keyboard/dialog,
cancel, move/conflict, missing-target and Viewer checks. Its explicitly injected
background refresh/navigation races check request ownership, not timing or normal
modal interaction. Fixture-only accounts and files are discarded with the stack.
The ordering fixture delays assets, tags and pagination across searches and view
changes, including stale versus current authorization errors. It also checks that
unsubmitted search text cannot change pagination's applied query.

Organization report schema 4 retains schema 3's first-card visibility inside the browser at
an animation frame, independently of Playwright locator retry timing. It is a
visible-layout measurement, not physical display presentation. Navigation and
automated sign-in remain included; the existing Chromium <1000 ms budget is
unchanged. `firstCardsWaitReturnMs` retains the old driver-observed duration for
comparison. Missing visibility is null and fails, never an invented zero.
Long tasks now use their start timestamps, with legacy observer-delivery attribution
retained separately. The interaction guard takes the maximum across the legacy,
start-time and cross-phase classifications; this cannot weaken an earlier failure.
Locators are scoped to the intended card/toolbar/sidebar, and search/folder-open
completion checks the actual returned IDs/current folder instead of an old card or
an eagerly mounted select. Navigation and automated login remain inside startup.
Post-action DOM snapshots require zero per-card folder destination options when
the shared dialog is closed. No performance limit changed.

Use `--folder-stress --workflows organization --browsers chromium` for a separately
labelled 600-Artifact/1,040-folder probe. The default fixture remains 600/104 and
both retain the same thresholds; stress results do not substitute for baseline runs.

Preview exit success means
functional probes and metric collection completed, **not** that every measured
budget passed. Review the stored metrics separately. Missing measurements are
null, never zero. Keep failed attempts; do not silently substitute a later pass.
Use `--workflows` and `--browsers` for a bounded diagnostic subset.

Historical shell wrappers are not the production-HTTPS evidence entry point.
No runner action pushes, publishes, tags or deploys a release.

For opt-in diagnostic profiling, add `--workflows organization --browsers chromium
--profile-chromium`. This retains all workflow assertions and thresholds, but
instrumented timings are not qualification timings. It records private Chrome
timeline/CPU profiles, script execution-context identities, phase marks, resource
timings and available long-animation-frame attribution. Trace loss/missing data
fails explicitly. Raw traces can contain sensitive fixture context: do not publish
them; review reduced summaries and hashes instead. Run unprofiled controls on the
same images separately. Production source, browser flags and host trust are unchanged.

`--workflows preview --browsers chromium --profile-chromium` instead profiles the
warm browser-information collection through detail open/ready/close on one page.
It records context-creation durations and distinct metric/reset/click/ready markers
to distinguish measurement work from viewer startup. The opt-in canvas wrapper
forwards native behavior and is restored at completion; this adds diagnostic
overhead, not a renderer fix. Cold/warm/LightBurn behavior remains in the report,
but only warm metrics/detail has a trace. Run without the flag for controls.
Keep private context/trace files uncommitted and reject incomplete captures.

Protocol references: [Chrome tracing](https://chromedevtools.github.io/devtools-protocol/tot/Tracing/)
and [CPU profiler](https://chromedevtools.github.io/devtools-protocol/tot/Profiler/).

Trust references: [Chromium NSS documentation](https://github.com/chromium/chromium/blob/main/docs/linux/cert_management.md),
[Firefox certificate policy](https://firefox-admin-docs.mozilla.org/reference/policies/certificates/).
