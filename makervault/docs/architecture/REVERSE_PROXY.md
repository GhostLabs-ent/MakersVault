# MakersVault Reverse-Proxy Topology

## Recommended: one public hostname

MakersVault still runs two containers:

```text
Browser
  |
  | https://makersvault.example
  v
External reverse proxy
  |
  | all paths
  v
web:5173 (Nginx)
  +-- /, /assets/* -> static MakersVault UI
  `-- /api/*       -> api:8000 over the private Compose network
```

The external proxy needs one host rule only. Target the published web port or the
`web:5173` service when the proxy shares its Docker network.

Recommended environment:

```dotenv
PUBLIC_URL=https://makersvault.example
VITE_API_URL=
CORS_ORIGINS=https://makersvault.example
```

Leaving `VITE_API_URL` empty is intentional. The web container writes
`https://makersvault.example/api` into runtime configuration, and its Nginx
configuration removes `/api` before forwarding the request to FastAPI.

The external proxy should preserve `Host`, `X-Forwarded-For`, and
`X-Forwarded-Proto`. TLS terminates at the external proxy in this topology.

## Optional: separate same-site HTTPS UI and API hostnames

The following remains supported for direct access or an existing deployment:

```text
https://vault.example.com -> web:5173
https://api.example.com   -> api:8000
```

It requires explicit browser-visible API and CORS configuration:

```dotenv
PUBLIC_URL=https://vault.example.com
VITE_API_URL=https://api.example.com
CORS_ORIGINS=https://vault.example.com
TRUSTED_HOSTS=api.example.com
```

This topology has two certificates/routes and a cross-origin browser boundary. It
is no longer the recommended default because the web container can provide the
same-origin gateway itself.

Both hosts must be same-site HTTPS: cross-origin is not the same as cross-site.
The current `SameSite=Lax` session cookie is not sent with ordinary cross-site
fetches, even when CORS permits the origin. Unrelated registrable domains are not
a supported authenticated UI/API split. Prefer the one-host topology instead of
relaxing cookie security. This follows the browser's
[SameSite cookie rules](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie#samesitesamesite-value).

## Troubleshooting

- If the UI loads but requests go to the old API hostname, clear the browser's
  MakersVault network override and leave `VITE_API_URL` empty.
- If `/api/health` returns the UI HTML, the external proxy is rewriting paths
  incorrectly. Forward all paths unchanged to the web container.
- If the external proxy shares the Compose network, attach it to the MakersVault
  network and target service `web` on port `5173`; otherwise target the host's
  published web port.
- Current production browser access requires HTTPS at the reverse proxy, including
  over a private network/VPN. A VPN does not change Secure-cookie requirements.
  Direct public exposure of unprotected MakersVault ports is unsupported.
- Preserve the browser-visible `Host` header. `PUBLIC_URL` enables the matching
  API host policy automatically in the recommended one-host topology; configure
  `TRUSTED_HOSTS` for a separate API hostname.
- Add HSTS at the external proxy only after confirming the hostname will remain
  HTTPS-only. The gateway's private upstream HTTP and development mode are not
  production browser HTTP exceptions.
