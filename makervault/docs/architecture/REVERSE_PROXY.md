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

## Optional: separate UI and API hostnames

The following remains supported for direct access or an existing deployment:

```text
https://makersvault.example    -> web:5173
https://makersvaultapi.example -> api:8000
```

It requires explicit browser-visible API and CORS configuration:

```dotenv
PUBLIC_URL=https://makersvault.example
VITE_API_URL=https://makersvaultapi.example
CORS_ORIGINS=https://makersvault.example
TRUSTED_HOSTS=makersvaultapi.example
```

This topology has two certificates/routes and a cross-origin browser boundary. It
is no longer the recommended default because the web container can provide the
same-origin gateway itself.

## Troubleshooting

- If the UI loads but requests go to the old API hostname, clear the browser's
  MakersVault network override and leave `VITE_API_URL` empty.
- If `/api/health` returns the UI HTML, the external proxy is rewriting paths
  incorrectly. Forward all paths unchanged to the web container.
- If the external proxy shares the Compose network, attach it to the MakersVault
  network and target service `web` on port `5173`; otherwise target the host's
  published web port.
- Remote access requires HTTPS at the reverse proxy or equivalent protection from
  a private network/VPN. Direct public exposure of MakersVault ports is
  unsupported for v5.1.
- Preserve the browser-visible `Host` header. `PUBLIC_URL` enables the matching
  API host policy automatically in the recommended one-host topology; configure
  `TRUSTED_HOSTS` for a separate API hostname.
- Add HSTS at the external proxy only after confirming the hostname will remain
  HTTPS-only. The bundled gateway intentionally also supports trusted-LAN HTTP.
