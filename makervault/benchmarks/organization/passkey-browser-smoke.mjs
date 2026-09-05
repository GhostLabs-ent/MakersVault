import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

import { chromium } from "playwright-core";


const webUrl = process.env.MAKERSVAULT_PASSKEY_WEB_URL || "http://localhost:15178";
const outputPath = resolve(
  process.env.MAKERSVAULT_PASSKEY_OUTPUT || ".artifacts/passkey-browser.json",
);
let browser;


try {
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  const { authenticatorId } = await cdp.send("WebAuthn.addVirtualAuthenticator", {
    options: {
      protocol: "ctap2",
      transport: "internal",
      hasResidentKey: true,
      hasUserVerification: true,
      isUserVerified: true,
      automaticPresenceSimulation: true,
    },
  });

  await page.goto(webUrl, { waitUntil: "networkidle" });
  await page.locator('input[autocomplete="username"]').fill("admin");
  await page.locator('input[autocomplete="current-password"]').fill(
    "local-development-only",
  );
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Settings" }).click();
  await page.getByRole("button", { name: "Accounts & Access" }).click();
  await page.getByPlaceholder("Passkey label, for example Laptop").fill(
    "Browser drill passkey",
  );
  await page.getByRole("button", { name: "Add passkey" }).click();
  await page.getByText("MFA enabled", { exact: true }).waitFor();

  await page.getByPlaceholder("Current password").first().fill(
    "local-development-only",
  );
  await page.getByRole("button", { name: "Confirm", exact: true }).click();
  await page.getByText(/Identity confirmed/).waitFor();
  await page.getByLabel("Passkey requirement").selectOption("require_administrators");
  await page.getByText("Passkey requirement updated.").waitFor();

  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Log out" }).click();
  await page.locator('input[autocomplete="username"]').fill("admin");
  await page.locator('input[autocomplete="current-password"]').fill(
    "local-development-only",
  );
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Settings" }).waitFor();

  const credentials = await cdp.send("WebAuthn.getCredentials", { authenticatorId });
  if (credentials.credentials.length !== 1) {
    throw new Error(`Expected one browser credential, received ${credentials.credentials.length}`);
  }
  const result = {
    status: "passed",
    browser: await page.evaluate(() => navigator.userAgent),
    credentialCount: credentials.credentials.length,
    registration: "passed",
    currentStrengthReauthentication: "passed",
    administratorPolicy: "require_administrators",
    passwordPlusPasskeyLogin: "passed",
  };
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(result)}\n`);
} finally {
  await browser?.close();
}
