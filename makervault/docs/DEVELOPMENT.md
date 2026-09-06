# MakersVault Development Verification

## Prerequisites

- Docker with Docker Compose.
- GNU Make.
- `curl` for the container health check.
- Python 3.11+ and OpenSSL for the host-side verification/recovery orchestration.
- Linux Docker host networking for the lifecycle drill's Node HTTPS probe.

Application dependencies, Node, and Go run in versioned container toolchains.
The host-side lifecycle harness uses only Python's standard library. Its private
test certificate is trusted only by fixture clients; no host trust store or DNS
configuration is changed. Release image digests are recorded at the candidate gate.

Python direct dependencies are declared in `requirements.txt` and
`requirements-dev.txt`. The successful Python 3.11/Linux environments are frozen
in `requirements.lock` and `requirements-dev.lock`; Docker and CI install the lock
files.

## Complete verification

From the repository root:

```bash
make verify
```

This performs:

1. API migration tests under Python 3.11.
2. Web TypeScript checking, Vitest tests, and the production Vite build under
   Node 20.
3. Bridge tests and compilation under Go 1.26.6.
4. Validation of the local, canonical production, historical alias, and smoke
   Compose configurations.
5. A clean container smoke test with temporary named volumes, HTTP health checks,
   non-root runtime assertions, and schema-version verification.
6. A Chromium virtual-authenticator passkey workflow in its own disposable project.
7. The static release identity/publication contract check.
8. Cookie/CSRF fixture-client safety and recovery-comparison unit tests.
9. A generated schema-4 → schema-17 production-HTTPS lifecycle: raw backup/restore,
   exact stopped rollback, staged portable clean import/startup, and fresh install.

`make verify` is not the complete release qualification. Gate 13B replaces obsolete
JWT/schema-5 assumptions in current harnesses with cookie/CSRF/schema-17 checks;
historical results still belong to their original baselines. The complete current
browser/corpus/mounted-import matrix, physical devices, platform integration and
owner-selected matched release artifacts remain separate 13C work. See the
[Gate 13 baseline](evidence/gate-13/BASELINE.md). Never re-enable obsolete auth to
make a harness pass.

The smoke test uses host ports `18000` and `15173` by default. Override them only
when necessary:

```bash
MAKERSVAULT_SMOKE_API_PORT=28000 \
MAKERSVAULT_SMOKE_WEB_PORT=25173 \
make verify-smoke
make verify-passkeys
```

The smoke project is removed with its named volumes on success, failure, or
interruption. It does not use `makervault/data` and does not open `api/app.db`.

## Focused verification

```bash
make verify-api
make verify-web
make verify-bridge
make verify-compose
make verify-smoke
make verify-passkeys
make verify-release
make verify-harness
make verify-lifecycle
```

CI invokes these same targets. A local workaround that CI does not execute is not
release evidence.

`verify-lifecycle` allows dirty development sources but explicitly reports them as
such. For immutable evidence, commit the scoped implementation locally and run
`python3 makervault/scripts/gate13-lifecycle-drill.py` without `--allow-dirty`.
It builds development-labelled API/web images, validates their OCI identities,
and starts their immutable image IDs in unique disposable production-Compose
projects with loopback-only ephemeral ports. It removes only its generated
projects/volumes and private fixtures; built local development images remain.
This does not assemble, tag, push, or qualify a replacement release candidate.

`scripts/gate5-recovery-drill.sh` is now a compatibility command for that current
lifecycle drill. `scripts/release-candidate-smoke.sh` checks supplied image identities
with production HTTPS, cookie/CSRF, restart persistence, logout and schema 17.
Gate 5's original scripts/evidence remain reproducible from `f6ff55b`; do not use
the current commands to retroactively change its qualification.

The passkey drill installs locked Playwright dependencies inside a disposable
container and drives Chromium with a virtual authenticator through registration,
identity confirmation, required-Administrator policy, logout, and password-plus-
passkey login. It runs against an isolated local Compose project on ports `18005`
and `15178`, removes its own volumes afterward, and writes a secret-free result to
`benchmarks/organization/.artifacts/passkey-browser.json`. This validates the browser
and server integration; physical device and operating-system credential prompts
still need release qualification on the supported platforms.

## Schema migration rules

- Add the next immutable `Migration` entry in `api/migrations.py`.
- Never rename or reuse an applied version.
- Add fresh, prior-version, repeated-run, failure, and restore-oriented tests as
  applicable.
- Do not test against or commit a user's runtime database.
- A release that changes schema must document its supported source versions and
  matched database/storage restore procedure.
