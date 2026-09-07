import assert from "node:assert/strict";
import { chromium, firefox, webkit } from "playwright-core";

const origin = process.env.MAKERSVAULT_BENCHMARK_WEB_URL;
const engine = process.env.MAKERSVAULT_BENCHMARK_BROWSER;
const url = new URL(origin);
assert.equal(url.protocol, "https:");
assert.equal(url.hostname, "vault.example.test");
const launchOptions = { headless: true };
// Playwright's patched Firefox ignores distribution policies unless explicitly selected.
if (engine === "firefox") launchOptions.firefoxUserPrefs = {
  "browser.policies.alternatePath": "/opt/makersvault-fixture-policies.json",
};
const browser = await { chromium, firefox, webkit }[engine].launch(launchOptions);
try {
  const page = await browser.newPage();
  const response = await page.goto(`${origin}/api/health`);
  assert.equal(response.status(), 200);
  assert.equal((await response.json()).auth_required, true);
  assert.equal(await page.evaluate(() => window.isSecureContext), true);
  const wrongHost = `https://127.0.0.1:${url.port}/api/health`;
  await assert.rejects(page.goto(wrongHost), /CERT|SSL|certificate|TLS|Unacceptable/i);
  const nodeResponse = await fetch(`${origin}/api/health`);
  assert.equal(nodeResponse.status, 200);
  await assert.rejects(fetch(wrongHost));
  console.log(JSON.stringify({ engine, version: browser.version(), trustedFixture: true, hostnameMismatchRejected: true }));
} catch (error) {
  if (engine === "firefox") {
    // Read-only fixture diagnostics; no auth or certificate overrides.
    for (const page of browser.contexts().flatMap(context => context.pages())) {
      console.error("Firefox TLS error page:", await page.locator("body").innerText({ timeout: 2000 }).catch(() => "unavailable"));
    }
    const policyPage = await browser.newPage();
    await policyPage.goto("about:policies");
    console.error("Firefox fixture policies:", (await policyPage.locator("body").innerText()).slice(0, 4000));
  }
  throw error;
} finally {
  await browser.close();
}
