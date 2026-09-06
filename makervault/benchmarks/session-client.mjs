// Node-only fixture client. Session material is memory-only and never a report field.
export async function loginSession(apiUrl, origin, username, password, fetchImpl = fetch) {
  const base = new URL(apiUrl);
  const source = new URL(origin);
  if (![base, source].every(url => ["http:", "https:"].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash)) {
    throw new Error("Harness requires explicit HTTP(S) API and web origins");
  }
  const prefix = base.href.replace(/\/$/, "");
  const login = await fetchImpl(`${prefix}/login`, {
    method: "POST", redirect: "error",
    headers: { "Content-Type": "application/json", Origin: source.origin },
    body: JSON.stringify({ username, password }),
  });
  if (!login.ok) throw new Error(`Harness login failed: HTTP ${login.status}`);
  const result = await login.json();
  if (result.token || result.mfa_required || typeof result.csrf_token !== "string" || !result.csrf_token) {
    throw new Error("Harness requires a complete cookie session, not JWT or pending MFA");
  }
  const cookies = login.headers.getSetCookie().filter(value => /^(?:__Host-makersvault_session|makersvault_session_dev)=/.test(value));
  if (cookies.length !== 1) throw new Error("Harness login omitted a unique session cookie");
  const [cookie, ...attributes] = cookies[0].split(";").map(value => value.trim());
  const attrs = new Set(attributes.map(value => value.toLowerCase()));
  if (!attrs.has("httponly") || !attrs.has("path=/") || attributes.some(value => /^domain=/i.test(value)) || !cookie.split("=")[1]) {
    throw new Error("Invalid host-only session cookie");
  }
  if (cookie.startsWith("__Host-") && !attrs.has("secure")) throw new Error("Invalid Secure session cookie");
  if (attrs.has("secure") && base.protocol !== "https:") throw new Error("Secure session cookies require HTTPS");
  return Object.freeze({
    async fetch(path, init = {}) {
      if (typeof path !== "string" || !path.startsWith("/") || path.startsWith("//") || /[\\\r\n]/.test(path)) throw new Error("Invalid API path");
      const target = new URL(`${prefix}${path}`);
      if (target.origin !== base.origin || !target.href.startsWith(`${prefix}/`)) throw new Error("API path escaped configured base");
      const headers = new Headers(init.headers);
      for (const name of ["authorization", "cookie", "origin", "x-csrf-token"]) {
        if (headers.has(name)) throw new Error("Harness cannot override authentication headers");
      }
      if (init.redirect && init.redirect !== "error") throw new Error("Harness cannot follow redirects");
      headers.set("Cookie", cookie);
      if (!["GET", "HEAD", "OPTIONS"].includes((init.method || "GET").toUpperCase())) {
        headers.set("Origin", source.origin);
        headers.set("X-CSRF-Token", result.csrf_token);
      }
      return fetchImpl(target, { ...init, headers, redirect: "error" });
    },
  });
}
