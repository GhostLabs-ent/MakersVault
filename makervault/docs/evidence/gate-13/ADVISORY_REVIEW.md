# Gate 13C — dated advisory checkpoint

**Date:** 2026-09-06 (scan timestamps are UTC).

**Status:** findings open; not release clearance or authorization to update pins.

## What was actually checked

The application locks are unchanged from the accepted 13B build. The scan source
HEAD is `fa273b6cc07fea1539c35e4f78d46eb8cf2b828d`, which only opens 13C; runtime
behavior remains `1a209aa` and the entry images were built at `2c68d70`.
The audit helper and operator-documentation changes were uncommitted during this
capture; they do not change the scanned locks or application images.
The [machine-readable snapshot](advisory-audit.json) preserves lock hashes, tool/
database identities and raw-report hashes. [Reduced image matches](advisory-image-matches.json)
preserve all 441 observations, including package locations, matcher types and
reported fix states; they are not an accepted residual-risk list.

| Layer | Tool / database | Result |
|---|---|---|
| Web production lock | `npm audit --omit=dev`, npm registry advisories | One moderate affected package: `fflate` |
| Complete web lock | `npm audit`, npm registry advisories | Three affected packages: one high, one moderate, one low; four advisories in total |
| Organization / preview harness locks | `npm audit`, separately for each lock | No advisories reported for either lock |
| Python runtime lock | `pip-audit 2.9.0`, PyPI advisory service; complete pinned lock, no dependency resolution | 35 dependencies, zero advisories, zero skipped |
| Python development lock | Same tool and service, separate complete lock | 43 dependencies, zero advisories, zero skipped |
| Go bridge source | `govulncheck v1.7.0`, Go 1.26.6, symbol-level source scan | Zero finding records; database last modified `2026-09-02T19:12:04Z` |
| API runtime image | Grype 0.118.0, immutable local Docker archive | 283 package matches / 122 distinct advisory IDs; 13 critical, 84 high, 78 medium, 10 low, 54 negligible, 44 unknown |
| Web runtime image | Same scanner/database, separate immutable archive | 158 package matches / 128 distinct advisory IDs; 13 critical, 59 high, 74 medium, 12 low |

Zero findings mean only that these tools/databases reported none for their stated
scope and date. They do not prove absence of vulnerabilities. Go JSON includes
historical advisory inventory even with no matching findings; the helper counts
actual `finding` records. Image findings are package matches, not demonstrated
exploitability. No severity threshold, ignore list or automatic fix hides results.

## Application and build-tool findings

| Locked package | Advisory / fix | Current applicability and proposed disposition |
|---|---|---|
| `fflate 0.8.2` — direct production dependency | [GHSA-px8p-9vwx-vf98](https://github.com/advisories/GHSA-px8p-9vwx-vf98), CVE-2026-45820; patched in 0.8.3 | Malformed ZIP64 can loop inside `unzipSync`. Approve the direct patch and a bounded malformed-archive regression before browser qualification |
| `browserslist 4.26.3` — development/build chain | [GHSA-c83g-rgw3-j3cx](https://github.com/advisories/GHSA-c83g-rgw3-j3cx) and [GHSA-73wf-gq98-2v4g](https://github.com/advisories/GHSA-73wf-gq98-2v4g); patched in 4.28.7 | Memory growth and unsafe custom-stat handling. Not a production server package in the static web image. Approve a targeted compatible lock refresh; no runtime remote exploit is established |
| `postcss-selector-parser 6.1.2` — development/build chain | [GHSA-w9m9-85wc-3x92](https://github.com/advisories/GHSA-w9m9-85wc-3x92), CVE-2026-9358; patched in 6.1.3 | Recursive AST denial of service; approve a targeted compatible lock refresh. No untrusted production build-input path is established |

The `fflate` applicability is a source-review inference, not a live exploit test:
`web/src/lib/zipUtils.ts::readZipEntries` calls `unzipSync` on the browser main
thread. `UploadBar`, `Sidebar` and `AssetGrid` call it when opening ZIP uploads.
Preview-worker termination does not protect that separate upload path. Background
3MF previews also use the dependency, with a worker timeout; LightBurn's worker
has additional ZIP64 prechecks. Server-side archive limits do not interrupt work
already executing in the browser. The patch does not by itself establish general
ZIP upload CPU/memory bounds; a broader upload-worker redesign remains a separate
scope decision. No malformed looping archive was executed on the host or UI.

## Runtime-image triage checkpoint

Both image scans used a valid Grype database, schema `v6.1.9`, built
`2026-09-06T06:27:35Z`. The API image reports Debian 13.6 and the web image Alpine
3.21.3. These are current local entry images, **not** a scan of the frozen Gate 5
release or a claim about the deployed public image tags.

| Image | Scanner-reported fix state across package matches | Required work |
|---|---|---|
| API | 114 fixed, 45 not-fixed, 119 wont-fix, 5 unspecified | Refresh compatible pinned base/runtime packages; inspect inherited Python installer/vendor packages; review remaining matches against upstream and distro evidence |
| Web | 104 fixed, 42 unknown, 12 unspecified | Refresh the pinned unprivileged Nginx/Alpine runtime; revalidate proxy behavior, non-root execution and supported distro/package fixes |

The totals count advisory/package matches, not independent exploitable flaws;
one OpenSSL advisory can match multiple binary packages. `fixed` means the scanner
knows a fixed version, not that the scanned image is fixed. `wont-fix` or `unknown`
does not mean MakersVault has accepted a risk. NVD/CPE-only matches and Python
interpreter version ranges need vendor review before deciding they apply or
choosing an upgrade. No Python major-version migration is authorized implicitly.

Representative distro-backed fixes were checked independently:

- API OpenSSL `3.5.6-1~deb13u2`: Debian lists `3.5.7-1~deb13u2` as fixed for
  [CVE-2026-63073](https://security-tracker.debian.org/tracker/CVE-2026-63073) and
  [CVE-2026-75803](https://security-tracker.debian.org/tracker/CVE-2026-75803).
  These affect particular CMP / cipher API operations; their presence is not proof
  MakersVault reaches those operations.
- Web OpenSSL `3.3.3-r0` and libxml2 `2.13.4-r6`: Alpine's trackers describe
  [CVE-2025-15467](https://security.alpinelinux.org/vuln/CVE-2025-15467) and
  [CVE-2025-49796](https://security.alpinelinux.org/vuln/CVE-2025-49796).
  The scan reports fixed versions `3.3.6-r0` and `2.13.9-r0` respectively.
  Refreshing only these versions is not a disposition of the other matches.

The API image also contains `pip 24.0`, `setuptools 79.0.1` and setuptools-vendored
`jaraco.context 5.3.0` / `wheel 0.45.1` outside the application requirement locks.
The image scan reports advisories for them. This is why the zero-finding Python
lock results are **not** a clean Python-runtime/image claim. Review updated base
tooling or removal of unnecessary installers through a tested runtime build,
without removing application dependencies or silently suppressing vendor matches.

## Reproduction and evidence boundaries

Run from the repository root, using a new private output directory for each run:

```bash
python3 makervault/scripts/gate13-advisory-audit.py --phase all \
  --output /tmp/makersvault-gate13c-audit-NEW \
  --api-image sha256:9b8b729644b3938584b293e90713bc40971afd612539dfca4daa94854c018a85 \
  --web-image sha256:80f1dcdf8f853d2af8b924c046fbf266b3f4db3e755638b4e5c7cb0bf28036f8
```

Docker and network access to the named advisory/package services are required.
The helper uses read-only source mounts and saved image archives, not a Docker
socket inside the scanner. It neither installs into the application nor modifies
locks, starts the application, publishes results or fixes findings. Scanner
containers have unique names and are cleaned up. Private raw reports retain
stdout/stderr; failed scans do not produce a completed summary. Exit success means
the audit completed, **not** that findings are absent or release is approved.
Use `--phase languages` / `--phase images` for separately bounded invocations.

The command wrapper's 120-second cap interrupted the first combined scan before
image evidence was returned. Its orphaned disposable scanner finished and was
removed; its generated archive/cache directory was cleaned up. A subsequent image
attempt failed because the scanner's `/tmp` was not writable by the host UID.
The helper now provides private writable scratch space and runs long image scans
outside that wrapper cap. Neither failed attempt counts as a clean image scan.

Scanners and data sources: [pip-audit](https://github.com/pypa/pip-audit),
[Go vulnerability checking](https://go.dev/doc/tutorial/govulncheck),
[Grype 0.118.0](https://github.com/anchore/grype/releases/tag/v0.118.0).

## Owner decision and resumption

Approve only the reviewed dependency/base-image remediation scope, then rerun the
fresh audits, targeted archive regressions and full repository verification. Name
the resulting application/image identities before continuing the browser corpus,
organization/Trash, mounted-import and other current workflow evidence. Preserve
performance budgets and production HTTPS/cookie policy. Physical-device/native-app
evidence and release scope remain separate owner checkpoints. No publication or
replacement of the frozen Gate 5 candidate is authorized here.
