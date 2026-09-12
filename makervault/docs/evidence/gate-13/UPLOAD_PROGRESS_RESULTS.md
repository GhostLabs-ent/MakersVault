# UP-1 — shared upload progress

**2026-09-12 · VERIFIED locally; awaiting owner acceptance.** CNC/CAM integration
is deferred. Make Plate and workstation preset import are authorized but **not
implemented**; see the [amended runbook](../../MAKE_PLATE_RUNBOOK.md).

## Implemented behavior

- Shared browser upload batches show file-size-weighted request transfer progress,
  saved/failed counts, the current path and a separate server-finalizing state.
  Unknown-length transfer is indeterminate. Success requires the API response;
  `100% transferred` alone does not mean saved, preview-ready or successful.
- Folder/button/drop and confirmed ZIP-selection batches share the implementation.
  Folder enumeration and ZIP-selection dialogs are not assigned a fabricated
  percentage. Remote URL imports and supporting-file/thumbnail uploads are unchanged.
- Failed files remain failures while later files can proceed. Session expiry or
  logout clears summaries, aborts active transfer and prevents queued file uploads.
  Already committed files/folders are not rolled back; a folder request already in
  flight may finish. Progress is not persistent or resumable across page reloads.
- Accessible native progress elements and status text accompany dismissible results.
  Three completed summaries are retained; this is a UI-history bound, **not** a file,
  folder, byte or upload-count limit. Existing sequential processing and limits remain.
- Multipart uploads explicitly use each file's basename; directory placement stays
  in folder metadata. No API/schema, dependency, bridge or deployment changes.

## Exact inputs and results

Application source: `b059dd70569e923230fed18b949db1bb27e3af53`, after initial
implementation `d42c96b` and basename correction. Final browser harness:
`558f59c4903f7a05eb38f7561470fcc588330706`; application sources are unchanged
between those revisions. These are local development builds, not a release candidate.

| Check | Actual result |
|---|---|
| Web Docker `test` target (`npm run verify`) | TypeScript, **84 tests in 19 files**, production build pass |
| Production web image build | Pass; version `development-upload-progress`, revision `b059dd7` |
| Chromium 151.0.7922.34 / Firefox 153.0 / WebKit 26.5 | All five workflow assertions pass in each engine |
| Browser folder fixtures | Two generated binary STLs, 134 and 50,084 bytes; nested folder, basenames and downloaded SHA-256 equality pass |
| Pending request | Zero saved and no complete state while native request is held; two saved and 100% after successful responses |
| Injected HTTP 413 | One failed, one saved; not complete; exactly two requests |
| Injected HTTP 401 | One request only, remaining queue stops, login appears and old progress stays cleared after sign-in |

Unit coverage includes byte weighting, coalescing, concurrent batches, empty/unknown
sizes, upload-complete versus response-complete, HTTP/network/abort errors, session
headers, explicit basename, nested folder/Project payloads and cancellation during
folder creation. Existing project checks remain passing. The browser sample is not
a large-library benchmark, physical tablet test, complete drag/drop/ZIP matrix or
screen-reader audit; finalizing-after-upload is deterministically covered in unit
tests, while the browser fixture holds a **request**, not an already-saved response.

Images:

- Web: `sha256:99ed7fc30013a9077609ba0bf430a270ac8520ec63678657b62404ad4a9c4274`.
- Unchanged API: `sha256:dba3d2a7305b494d4d9a894d35fdee9743adbbf51f13c51678e98a2fcaf50b96`
  (source `6306ccf`, schema 17).
- Browser harness: `sha256:1e23cb1539a3e04d9b5db3fb6da8cc89694a8d1358f8e5ac726157a32536caaa`.

Browser checks use a fresh disposable Compose project, volumes, generated credentials
and trusted HTTPS certificate on loopback. TLS probe verifies the trusted hostname
and rejects the mismatched IP hostname. Native XHR uses cookie credentials and the
existing CSRF header policy, without bearer authorization or a manually constructed
multipart boundary. WebKit does not expose Cookie reliably through interception;
its context has the secure HttpOnly cookie and the real protected API accepts the
native request. This observation does not waive server authentication checks.

## Durable evidence and retained failures

Private root: `/home/vinnyc/.local/state/makersvault/verification/`.
Each `security-hardening-run.cjs` capture contains exact commands, start/end source
identity, verification-source cleanliness, exit code and SHA-256-bound stdout/stderr.
The [small evidence index](upload-verification.json) pins the passing logs.

- `containment-upload-web-c`: final type/test/build, exit 0.
- `containment-upload-runtime-c`: final web image build, exit 0.
- `containment-upload-browser-run-d`: final driver, exit 0; full three-engine
  result also retained in `containment-upload-browser-d/summary.json`.
- Initial preflight, runtime and tests remain in `containment-upload-web-preflight`,
  `containment-upload-web-final` and `containment-upload-web-runtime`. The first
  TypeScript failure used `Array.at` outside the configured ES2020 library; the
  retained `first-typecheck-attempt.log` precedes the compatible test correction.
- Browser attempts `containment-upload-browser-run-a`, `-b`, `-c` and corresponding
  `containment-upload-browser-a`, `-b`, `-c` are **retained failures**, not passes.
  They exposed path-bearing multipart filenames and test-harness issues: Cookie
  invisibility in WebKit, empty file payloads when `route.fetch()` reserialized
  native directory requests, and a partial-count timeout with reused root fixture
  names. Attempt C's Firefox checks passed; Chromium and WebKit did not.
- Final harness uses native `route.continue()`, holds a pending request instead of
  re-forwarding multipart data, and namespaces root fixtures by engine. Exact-byte,
  saved/failed and authentication assertions remain intact. The earlier partial-count
  timeout did not capture its actual count, so its precise cause is not proven.

Reproduction (use fresh, nonexisting private output directories):

```sh
docker build --target test -t makersvault-web-upload-progress-test makervault/web
docker build -t makersvault-web-upload-progress \
  --build-arg MAKERSVAULT_VERSION=development-upload-progress \
  --build-arg MAKERSVAULT_REVISION=b059dd70569e923230fed18b949db1bb27e3af53 makervault/web
python3 makervault/docs/evidence/gate-13/upload-browser-check.py \
  --web-image makersvault-web-upload-progress \
  --revision b059dd70569e923230fed18b949db1bb27e3af53 --output /absolute/new/private/output
```

Use the named source revision for the image, not merely its label. Existing capture
records bind the actually executed source. Disposable fixture cleanup removed only
its generated test data; retained reports and local images remain available.

## Re-cock

UP-1 awaits owner acceptance; next is **MP-0**: bounded preset/recipe/import authority
contracts and the previously found bridge installer/macOS pairing repairs. Bambu
Windows qualification requires the owner's tablet later; no host handler or device
installation was performed. No slicer discovery/import, layout generation or 3MF
handoff is claimed by this slice.

No fresh full API/bridge/lifecycle suite or vulnerability scan was run. Prior
E4/R57/F26/H0 dispositions remain historical exact-image evidence under unchanged
C1–C7/deadline, not waivers for this new web image. Gate 13C/13D, security closeout,
real-device checks and release acceptance remain open. Gate 12 and further G13-01
performance tuning stay deferred. Nothing was pushed, published or deployed live.
