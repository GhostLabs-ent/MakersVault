# Gate 13C — approved maintenance and revalidation

**Authority:** owner approved the scope in `4c38fcf` on 2026-09-06
(America/New_York; execution timestamps may be 2026-09-07 UTC).

**Status:** APPROVED MAINTENANCE VERIFIED; RESIDUAL ARCHIVE SCOPE DECISION REQUIRED.
Historical advisory snapshots are preserved, not edited into clean results.
Gate 13C remains open; no release, publication or residual-risk acceptance is implied.

## Execution contract

- Target the three reviewed web dependencies and bounded ZIP64 regression.
- Refresh digest-pinned runtime images without changing the Python release line;
  inspect inherited installer/vendor packages and unused runtime components.
- Re-scan exact rebuilt images, reconcile residuals with primary vendor evidence,
  run targeted tests and the complete gate, then resume current browser workflows.
- Keep production HTTPS, cookie policy, performance budgets, managed/external
  storage semantics and the frozen Gate 5 release contract unchanged.
- Keep all commits local and leave the unrelated desktop draft untouched.

Results, replacement image identities and remaining owner decisions follow actual
execution; nothing below is presumed complete from approval alone.

## Implemented maintenance

- `fflate` 0.8.2 → 0.8.3. Targeted compatible lock refresh resolves Browserslist
  4.28.9 and postcss-selector-parser 6.1.4 (later patch releases than the minimum
  fixes in the proposal), plus Browserslist's required browser-data dependencies.
  No application/framework-wide dependency update or forced audit fix.
- Python remains 3.11.16 on Debian trixie; the official refreshed multi-platform
  base index is `sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534`.
  [Official image metadata](https://github.com/docker-library/official-images/blob/master/library/python)
  and registry manifest resolve the source to `688a0b86bb44289df16a363e9f41d90514c1a5f9`.
- A separate hash-checked installer lock updates inherited pip to 26.2 and
  setuptools to 83.0.0 without changing application requirement locks. It is now
  included in the advisory helper's language scan; whole-image scans still cover
  vendored packages not represented by these top-level locks.
- Nginx unprivileged 1.30.4 Alpine slim, index
  `sha256:b1d850535f815f18e9dd12ca7e9f4d36de36a49e246ccd8ef64289b0d06bde49`, replaces
  1.27.5 Alpine. The checked [upstream slim Dockerfile](https://github.com/nginx/docker-nginx-unprivileged/blob/35a0ecd22ab5a1bcf1b8ada75506ab6947f37f75/stable/alpine-slim/Dockerfile)
  supplies the HTTP/static/TLS proxy features used by our configuration, without
  unused image-processing/mail modules. Runtime UID, headers, routing and TLS
  compatibility require the verification below, not inference from a successful build.

## Bounded ZIP regression

Five tests cover ordinary ZIP, valid ZIP64 and absent/unrelated/truncated ZIP64
extra fields. Parsing runs in a resource-limited worker terminated after two
seconds, and the test container has no network, 512 MiB memory and two CPUs.

The five cases pass with the patched dependency. As a negative control, the same
test file was mounted read-only into the old test image
`sha256:0c8306923bc7db1780448ac0c43ddf7bdc741367a9ca383414b4d9d9767cf3cf`:
both valid controls pass and all three malformed cases hit the deadline and fail,
with their workers terminated. This intentionally failing control proves the
regression distinguishes the old behavior; no fixture is written to a vault.
This is dependency regression proof, not a new browser upload-worker implementation
or a blanket archive resource-safety claim.

## Completed verification

Maintenance was committed locally at `39307f5`; verification-only loopback
bindings at `84b020d`. The complete `make verify` exited **0** at clean source
`84b020ddf18795b482040d8b669c081897fff31a`:

- **313 API tests**, **37 web tests**, web typecheck and production build.
- Go bridge tests/build, Compose/security validation and fresh development smoke.
- Chromium virtual-passkey registration, current-strength reauthentication,
  Administrator policy and password-plus-passkey login smoke.
- **12 Python harness tests**, **5 Node session-helper tests**, three browser-script
  syntax checks and the static release contract (not a release qualification).
- Joined production-HTTPS schema **4→17** upgrade, contract-6 raw restore with
  pre-start revocation, exact stopped schema-4 rollback, and portable **17→12→17**
  fresh-identity startup. All **18** portable members compare; corrupt archives
  and nonempty raw/portable targets are refused.

[Verification record](remediation-verification.json) preserves the actual lifecycle
output, source, counts and identity boundary. The lifecycle runner still labels
its development images `development-gate13b`; those IDs are not the separately
labelled `development-gate13c` images scanned below. The exact audited images
also passed `current-image-smoke.py`: production HTTPS, Secure host-only cookie/
CSRF, logout revocation, schema 17, non-root API/web and byte persistence over restart.

The first API test invocation hit the command wrapper's 120-second cap before a
final result; it is not counted as passing. The long-lived full-gate rerun above
is the completed evidence. Disposable stacks/scanners were cleaned up; unrelated
host workloads and the desktop draft were untouched.
The verification-only smoke and organization/passkey overlays now explicitly
replace published ports with loopback bindings, so their development-mode fixture
credentials are not exposed on the host's other network interfaces. Canonical
deployment manifests and their security defaults are unchanged.

## Refreshed advisory results

Scan started `2026-09-07T00:17:13.581512+00:00`, at the clean revision above.
[Audit snapshot](remediation-audit.json) retains lock/tool/database/image identities
and eleven raw-report hashes. [All reduced image matches](remediation-image-matches.json)
and [PSF vendor records](remediation-python-vendor.json) are separate evidence;
no ignore rule, severity threshold or waiver changes the observed counts.

| Layer | Entry scan | Refreshed scan |
|---|---|---|
| Complete / production web lock | 3 / 1 affected packages | 0 / 0 |
| Python runtime / development / installer locks | 0 / 0 / not separately audited | 0 / 0 / 0; 35 / 43 / 2 dependencies, none skipped |
| Go source / two browser-harness locks | No findings | No findings |
| API image | 283 package matches | 181 matches / 96 distinct IDs: 7 critical, 61 high, 51 medium, 9 low, 45 negligible, 8 unknown |
| Web image | 158 package matches | 3 medium matches / 1 distinct ID |

The API image has **164 Debian package matches** (45 `not-fixed`, 119 `wont-fix`)
and **17 Python interpreter CPE matches** (12 `fixed`, 5 unspecified). No Debian
match in this scan reports an available fix. No Python distribution/installer/vendor
package match remains, but that does not clear the interpreter. The web matches
are BusyBox CVE-2025-60876 on three packages, without a reported fix.

Grype **0.118.0** used a valid **v6.1.9** database built **2026-09-06T06:27:35Z**,
the same database build as the entry scan. Database archive SHA-256:
`3c93034d0475d25fc82addd47b2300f99564ea4f35fd9e0b957b701049a15020`.
Runtime probes report Python **3.11.16**, OpenSSL **3.5.7**, Expat **2.8.3**, pip
**26.2**, setuptools **83.0.0**; image inventories report Debian **13.6** and
Alpine **3.24.1**. These are observations, not an absence-of-vulnerabilities claim.

### Exact audited image identities

- API: `sha256:95c066523b6ed63925652654cde21bec72bad0efda6b2d0df1b5228ecf465f17`
- Web: `sha256:cf188cd2b841006321ade0f336714849c11cf888179136dc240af9d1a88d8907`

Both have revision `84b020ddf18795b482040d8b669c081897fff31a` and version
`development-gate13c`; neither replaces the frozen Gate 5 candidate.

## Next checkpoint

[Residual review and bounded proposal](REMEDIATION_RESIDUALS.md) distinguish seven
vendor-excluded interpreter matches, unresolved OS/library findings, and a
source-reachable ZIP decompression issue. **CVE-2026-15310 is not dismissed as a
CPE mismatch.** Its mitigation changes archive compatibility and requires an
owner scope decision before implementation. General upload-worker isolation,
Python release-line migration and residual-risk acceptance are not implied.

Current preview/organization/Trash/mounted-import browser execution remains
unfinished; no historical timings are reused. Resume it after the archive scope
decision and any approved guard regression. Physical-device/platform, release
scope/revision, final 13C and 13D decisions remain outstanding. Nothing was pushed.
