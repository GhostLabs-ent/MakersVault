# Curiarium Git Ignore Audit

**Repository:** `GhostLabs-ent/MakersVault`
**Reviewed branch:** `main`
**Audit date:** 2026-08-13

## Summary

The existing Curiarium ignore file is currently located at:

```text
curiarium/.gitignore
```

and contains only:

```gitignore
# Local storage and uploads should not be committed
data/storage/
slicer-bridge/dist/
```

That is too narrow for the current project.

The repository contains Python, Node/Vite, Go, Docker, SQLite runtime data, a desktop bridge, and local application storage. A repository-wide root `.gitignore` should account for all of those environments.

The accompanying replacement `.gitignore` is intended to live at:

```text
Curiarium/.gitignore
```

at the **repository root**, rather than only inside the `curiarium/` application directory.

---

# Items Currently Tracked That Should Not Be

The repository audit found generated/runtime artifacts already committed to Git.

## Python bytecode

Currently tracked:

```text
curiarium/api/__pycache__/
curiarium/api/__pycache__/*.pyc
```

Examples include compiled Python 3.11 and Python 3.14 bytecode.

These files are:

- Machine/runtime generated.
- Python-version dependent.
- Recreated automatically.
- Noise in code review.
- Unnecessary in releases.

They should be removed from Git and ignored with:

```gitignore
__pycache__/
*.py[cod]
```

---

## Local SQLite database

Currently tracked:

```text
curiarium/api/curiarium.db
```

This should not be in source control.

A runtime database may contain:

- Local asset metadata.
- User information.
- Authentication-related state as v5.1 evolves.
- Local configuration.
- Test/development data.

The source repository should contain migration/schema code, not a live database.

Ignore:

```gitignore
*.db
*.db-journal
*.db-shm
*.db-wal
*.sqlite
*.sqlite3
```

---

## `node_modules`

The repository currently contains:

```text
curiarium/web/node_modules/
```

`node_modules` should not be committed.

The reproducible dependency source should be:

```text
package.json
package-lock.json
```

Developers and CI then run:

```bash
npm ci
```

Keeping `node_modules` out of Git:

- Dramatically reduces repository size.
- Makes code reviews cleaner.
- Prevents dependency trees from drifting from the lockfile.
- Makes dependency/security auditing more reliable.

---

## Built frontend output

The repository currently contains:

```text
curiarium/web/dist/
```

For the normal source-development model, this should be produced by the release/build pipeline:

```bash
npm run build
```

and not committed.

Ignore:

```gitignore
dist/
.vite/
```

If Curiarium later intentionally distributes a prebuilt static site directly from Git, this decision can be revisited. For Docker/GitHub Release based distribution, generated build output belongs in build artifacts rather than the source tree.

---

## Precompiled Slicer Bridge executable

The repository currently contains:

```text
curiarium/slicer-bridge/slicer-bridge.exe
```

The bridge source is already present in Go.

The executable should preferably be:

1. Built in CI.
2. Attached to a tagged GitHub Release.
3. Accompanied by a SHA-256 checksum.
4. Eventually signed.
5. Ideally accompanied by an SBOM.

This is especially relevant after the v5.1 security review because users are trusting the bridge to execute on their workstation.

Ignore:

```gitignore
curiarium/slicer-bridge/slicer-bridge
curiarium/slicer-bridge/slicer-bridge.exe
curiarium/slicer-bridge/dist/
curiarium/slicer-bridge/bin/
curiarium/slicer-bridge/build/
```

---

# Files That Should Remain Tracked

Do **not** ignore these.

## Dependency manifests and lockfiles

Keep:

```text
requirements.txt
package.json
package-lock.json
go.mod
go.sum
```

Lockfiles are important for reproducible and secure builds.

---

## Example environment files

Keep:

```text
.env.example
.env.sample
.env.template
```

Ignore the real local versions:

```text
.env
.env.production
.env.local
.env.development.local
```

The supplied `.gitignore` uses negation rules so examples remain trackable.

---

## Docker and deployment definitions

Keep:

```text
Dockerfile
docker-compose.yml
docker-compose.deploy.yml
docker-deploy.yml
docker-entrypoint.sh
.dockerignore
```

These are source/build definitions, not generated artifacts.

---

## Documentation

Keep:

```text
README.md
SECURITY.md
CHANGELOG.md
CONTRIBUTING.md
ROADMAP.md
docs/**/*.md
```

---

## Source assets

Do not globally ignore maker-file extensions such as:

```text
.stl
.3mf
.step
.stp
.svg
.lbrn
.lbrn2
```

Curiarium itself is a maker-file project and future tests, fixtures, examples, icons, or documentation may legitimately need those formats.

Runtime user libraries should instead be ignored by **directory**, such as:

```text
curiarium/data/
curiarium/api/storage/
```

rather than ignoring an entire file type.

---

# Recommended Root `.gitignore`

Use the accompanying file:

```text
Curiarium.root.gitignore
```

Rename it to:

```text
.gitignore
```

and place it at the repository root:

```text
Curiarium/
├── .gitignore
├── .gitattributes
├── LICENSE
├── README.md
└── curiarium/
```

Once a root `.gitignore` exists, the tiny nested:

```text
curiarium/.gitignore
```

can be removed to avoid maintaining two overlapping ignore policies.

A nested ignore file is not inherently wrong, but there is little benefit here because Curiarium is a single repository and the root policy can cover all components.

---

# Cleaning Already-Tracked Files

**Important:** `.gitignore` only stops new untracked files from being added.

It does **not** remove files that Git is already tracking.

After adding the new root `.gitignore`, first see everything that is both tracked and now ignored:

```bash
git ls-files -ci --exclude-standard
```

Review that output before removing anything.

For the artifacts identified in this audit:

```bash
git rm -r --cached curiarium/api/__pycache__
git rm --cached curiarium/api/curiarium.db
git rm -r --cached curiarium/web/node_modules
git rm -r --cached curiarium/web/dist
git rm --cached curiarium/slicer-bridge/slicer-bridge.exe
```

If some paths no longer exist locally, Git may report that the path did not match. That is harmless; remove only what is currently tracked.

Then verify again:

```bash
git ls-files -ci --exclude-standard
```

Ideally it should return no unintended tracked files.

---

# Verify Before Commit

Run:

```bash
git status
```

Expected changes should primarily show:

```text
new file:   .gitignore
deleted:    curiarium/api/__pycache__/...
deleted:    curiarium/api/curiarium.db
deleted:    curiarium/web/node_modules/...
deleted:    curiarium/web/dist/...
deleted:    curiarium/slicer-bridge/slicer-bridge.exe
```

If removing the nested ignore file:

```text
deleted:    curiarium/.gitignore
```

Then test the ignore policy directly:

```bash
git check-ignore -v curiarium/api/curiarium.db
git check-ignore -v curiarium/api/__pycache__/main.cpython-311.pyc
git check-ignore -v curiarium/web/node_modules/example
git check-ignore -v curiarium/web/dist/index.html
git check-ignore -v curiarium/slicer-bridge/slicer-bridge.exe
git check-ignore -v curiarium/api/.env
```

Each should print the matching ignore rule.

Now confirm important source files are **not** ignored:

```bash
git check-ignore curiarium/api/.env.example
git check-ignore curiarium/web/package-lock.json
git check-ignore curiarium/slicer-bridge/go.mod
```

Those commands should produce no matching ignore output.

---

# Security Benefits

This cleanup is more than repository cosmetics.

## Prevent accidental secret commits

Ignoring real `.env` files reduces the chance of committing:

```text
AUTH_PASSWORD
AUTH_SECRET
API tokens
session cookies
cloud credentials
```

The repository should still use secret scanning because `.gitignore` is not a security boundary.

---

## Prevent database leakage

Ignoring runtime databases helps prevent accidental publication of:

```text
users
sessions
asset metadata
local configuration
future MFA/session state
```

---

## Improve supply-chain review

Removing generated:

```text
node_modules/
dist/
*.exe
*.pyc
```

means reviewers can focus on source plus reproducible build definitions.

A release binary should be traceable back to:

```text
source
    ↓
CI build
    ↓
signed/tagged release artifact
```

rather than appearing as an unexplained binary inside the source tree.

---

# Recommended Additional Repository Controls

`.gitignore` should be paired with security automation.

## GitHub secret scanning

Enable:

```text
Secret scanning
Push protection
```

where available.

---

## Dependency automation

Use Dependabot for:

```text
pip
npm
GitHub Actions
Docker
Go modules
```

---

## Release artifacts

Move compiled bridge binaries to GitHub Releases.

Recommended release contents:

```text
curiarium-slicer-windows-amd64.exe
curiarium-slicer-linux-amd64
curiarium-slicer-linux-arm64
SHA256SUMS
SBOM
```

Longer term, sign those artifacts.

---

# Final Recommended Repository Shape

```text
Curiarium/
├── .gitignore
├── .gitattributes
├── LICENSE
├── README.md
├── SECURITY.md
├── CHANGELOG.md
├── docs/
│
└── curiarium/
    ├── api/
    │   ├── *.py
    │   ├── requirements.txt
    │   ├── .env.example
    │   └── Dockerfile
    │
    ├── web/
    │   ├── src/
    │   ├── public/
    │   ├── package.json
    │   ├── package-lock.json
    │   └── Dockerfile
    │
    ├── slicer-bridge/
    │   ├── cmd/
    │   ├── go.mod
    │   └── README.md
    │
    └── docker-compose.yml
```

Not in Git:

```text
__pycache__/
*.pyc
curiarium.db
node_modules/
dist/
runtime storage/
.env
logs/
temporary files/
compiled bridge binaries/
IDE state/
OS metadata/
```

That is the cleaner source-of-truth model Curiarium should use going into v5.1.
