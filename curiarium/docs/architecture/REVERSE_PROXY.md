# Curiarium Reverse-Proxy Topology

## Recommended: one public hostname

Curiarium still runs two containers:

```text
Browser
  |
  | https://curiarium.example
  v
External reverse proxy
  |
  | all paths
  v
web:5173 (Nginx)
  +-- /, /assets/* -> static Curiarium UI
  `-- /api/*       -> api:8000 over the private Compose network
```

The external proxy needs one host rule only. Target the published web port or the
`web:5173` service when the proxy shares its Docker network.

Recommended environment:

```dotenv
PUBLIC_URL=https://curiarium.example
VITE_API_URL=
CORS_ORIGINS=https://curiarium.example
```

Leaving `VITE_API_URL` empty is intentional. The web container writes
`https://curiarium.example/api` into runtime configuration, and its Nginx
configuration removes `/api` before forwarding the request to FastAPI.

The external proxy should preserve `Host`, `X-Forwarded-For`, and
`X-Forwarded-Proto`. TLS terminates at the external proxy in this topology.

## Optional: separate UI and API hostnames

The following remains supported for direct access or an existing deployment:

```text
https://curiarium.example    -> web:5173
https://curiariumapi.example -> api:8000
```

It requires explicit browser-visible API and CORS configuration:

```dotenv
PUBLIC_URL=https://curiarium.example
VITE_API_URL=https://curiariumapi.example
CORS_ORIGINS=https://curiarium.example
```

This topology has two certificates/routes and a cross-origin browser boundary. It
is no longer the recommended default because the web container can provide the
same-origin gateway itself.

## Security headers

The bundled Nginx sends these headers on every response (UI, assets, runtime
configuration, and the proxied `/api/*` route):

| Header | Default |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000` (no `includeSubDomains`, no `preload`) |
| `Content-Security-Policy` | `default-src 'self'` policy with `frame-ancestors 'none'` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `X-Frame-Options` | `DENY` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |

The default CSP allows `connect-src 'self'` plus the origin of the configured
absolute API URL. In the recommended single-host topology that origin is the same
host, so nothing extra is needed; with a split-host `VITE_API_URL` (for example
`https://curiariumapi.example`) the API origin is added automatically. The
browser-side network override stored in local storage is not known to the
container, so pointing the UI at a different origin from the browser requires
overriding `SECURITY_HEADERS_CSP` with an explicit `connect-src`.

### Overriding or disabling

| Goal | Setting |
|---|---|
| Change one header value | `SECURITY_HEADERS_HSTS`, `SECURITY_HEADERS_CSP`, `SECURITY_HEADERS_REFERRER_POLICY`, `SECURITY_HEADERS_FRAME_OPTIONS`, `SECURITY_HEADERS_PERMISSIONS_POLICY`, `SECURITY_HEADERS_CONTENT_TYPE_OPTIONS` |
| Omit a single header | set that variable to the literal value `off` |
| Send no security headers at all | `SECURITY_HEADERS_ENABLED=false` |
| Keep a default | leave the variable empty (`VAR=`) |

Header values are written into Nginx configuration, so values containing a
double quote, `$`, a backslash, or control characters are rejected with a
`[security-headers]` warning in the container log and replaced by the default.

### Duplicate headers behind an external proxy

An external proxy may also emit HSTS, CSP, or the other headers. Browsers handle
that by AND-ing the two policies, which is usually stricter than either one:

- Duplicate `Strict-Transport-Security` is ignored beyond the first valid value;
browsers do not fail, but the result is unpredictable, so pick one owner.
- Duplicate `Content-Security-Policy` is enforced as the intersection of both
policies and can silently break the UI (for example if the proxy's policy omits
`wasm-unsafe-eval` or `blob:` workers).

If the external proxy already sets a stricter policy, set
`SECURITY_HEADERS_ENABLED=false` on the web service so only the proxy's headers
are sent, or set the individual `SECURITY_HEADERS_*` variables to `off` and let
the proxy own those headers. Keep `Cache-Control` behavior untouched: the runtime
configuration endpoint still responds with `no-store`.

## Troubleshooting

- If the UI loads but requests go to the old API hostname, clear the browser's
  Curiarium network override and leave `VITE_API_URL` empty.
- If `/api/health` returns the UI HTML, the external proxy is rewriting paths
  incorrectly. Forward all paths unchanged to the web container.
- If the external proxy shares the Compose network, attach it to the Curiarium
  network and target service `web` on port `5173`; otherwise target the host's
  published web port.
- Do not expose the current beta directly to the Internet. Gate 1 must complete
  secure first-run, dependency, request-limit, and handoff hardening first.
