# Gate 13C — approved maintenance and revalidation

**Authority:** owner approved the scope in `4c38fcf` on 2026-09-06
(America/New_York; execution timestamps may be 2026-09-07 UTC).

**Status:** IN PROGRESS. Historical advisory snapshots are preserved, not edited
into clean results. No release, publication or residual-risk acceptance is implied.

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

## Verification in progress

The web typecheck/production build and all 37 web tests pass; audit-helper and
release-contract checks pass. The first API test invocation hit the command
wrapper's 120-second cap before returning a final result; it is not counted as
passing. The full gate will run through a long-lived executor with normal cleanup
and named disposable smoke/passkey projects.
