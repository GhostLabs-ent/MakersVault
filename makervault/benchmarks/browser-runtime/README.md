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
new public certificate. No user library or existing Compose project is used.
Only the public certificate is mounted into the browser container, never its key.
Certificate trust is confined to disposable containers. A preflight verifies both
successful fixture HTTPS and rejection of a mismatched hostname, in the browser
and Node client. No certificate-error bypass or host trust-store change is used.

The pinned Playwright image supplies Linux headless Chromium, Firefox and WebKit.
Its small NSS tools addition uses the signed Ubuntu repository. Chromium's NSS
peer trust and Firefox's certificate-install policy follow their documented Linux
trust mechanisms; WebKit uses the container trust store. Playwright's patched
Firefox requires `browser.policies.alternatePath` to select the fixture policy;
it does not automatically load distribution policies (the first run failed TLS
preflight for this reason). The runner's Firefox launches explicitly select the
container-local policy; no certificate validation setting is disabled. See the
[upstream Playwright policy-provider patch](https://github.com/microsoft/playwright/blob/main/browser_patches/firefox/patches/bootstrap.diff).
This is not native Safari,
Windows/macOS, mobile or hardware-passkey coverage.

Browser limits are 4 GiB memory and 1 GiB shared memory, with no CPU cap. Benchmark
sources and corpus are read-only. Locked npm packages install into disposable
anonymous volumes; reports go to a new private directory. The runner cleans up
only its own containers, including after timeouts. Mounted-import cases also
check that every fixture source byte and the rejected symlink remain unchanged.

Organization runs all three engines and retains its existing assertions/budgets;
preview and mounted-import workflows use Chromium. Preview exit success means
functional probes and metric collection completed, **not** that every measured
budget passed. Review the stored metrics separately. Missing measurements are
null, never zero. Keep failed attempts; do not silently substitute a later pass.
Use `--workflows` and `--browsers` for a bounded diagnostic subset.

Historical shell wrappers are not the production-HTTPS evidence entry point.
No runner action pushes, publishes, tags or deploys a release.

Trust references: [Chromium NSS documentation](https://github.com/chromium/chromium/blob/main/docs/linux/cert_management.md),
[Firefox certificate policy](https://firefox-admin-docs.mozilla.org/reference/policies/certificates/).
