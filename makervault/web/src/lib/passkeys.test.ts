import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createPasskeyCredential,
  decodeAuthenticationOptions,
  decodeRegistrationOptions,
  getPasskeyAssertion,
} from "./passkeys";


const originalNavigator = globalThis.navigator;


afterEach(() => {
  vi.restoreAllMocks();
  if (originalNavigator === undefined) Reflect.deleteProperty(globalThis, "navigator");
  else Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: originalNavigator,
  });
});


function buffer(...bytes: number[]): ArrayBuffer {
  return Uint8Array.from(bytes).buffer;
}


function values(source: BufferSource): number[] {
  const bytes = source instanceof ArrayBuffer
    ? new Uint8Array(source)
    : new Uint8Array(source.buffer, source.byteOffset, source.byteLength);
  return Array.from(bytes);
}


describe("browser passkey ceremonies", () => {
  it("fails clearly when the browser has no credential API", async () => {
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: {},
    });
    await expect(getPasskeyAssertion({ challenge: "AQI" })).rejects.toThrow(
      "This browser does not support passkeys.",
    );
  });

  it("decodes server registration options and serializes the browser response", async () => {
    const decoded = decodeRegistrationOptions({
      challenge: "-_8",
      rp: { id: "vault.example", name: "MakersVault" },
      user: { id: "AQI", name: "owner", displayName: "Owner" },
      pubKeyCredParams: [{ type: "public-key", alg: -7 }],
      excludeCredentials: [{ type: "public-key", id: "AwQ" }],
    });
    expect(values(decoded.challenge)).toEqual([251, 255]);
    expect(values(decoded.user.id)).toEqual([1, 2]);
    expect(values(decoded.excludeCredentials![0].id)).toEqual([3, 4]);

    const create = vi.fn().mockResolvedValue({
      id: "credential-id",
      rawId: buffer(3, 4),
      type: "public-key",
      authenticatorAttachment: "platform",
      getClientExtensionResults: () => ({}),
      response: {
        clientDataJSON: buffer(5),
        attestationObject: buffer(6),
        getTransports: () => ["internal"],
      },
    });
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: { credentials: { create } },
    });
    const payload = await createPasskeyCredential({
      challenge: "-_8",
      rp: { id: "vault.example", name: "MakersVault" },
      user: { id: "AQI", name: "owner", displayName: "Owner" },
      pubKeyCredParams: [{ type: "public-key", alg: -7 }],
    });
    expect(create).toHaveBeenCalledOnce();
    expect(payload).toMatchObject({
      id: "credential-id",
      rawId: "AwQ",
      type: "public-key",
      response: {
        clientDataJSON: "BQ",
        attestationObject: "Bg",
        transports: ["internal"],
      },
    });
  });

  it("decodes assertion allowlists and never stores the browser response", async () => {
    const decoded = decodeAuthenticationOptions({
      challenge: "AQI",
      rpId: "vault.example",
      allowCredentials: [{ type: "public-key", id: "AwQ" }],
      userVerification: "required",
    });
    expect(values(decoded.challenge)).toEqual([1, 2]);
    expect(values(decoded.allowCredentials![0].id)).toEqual([3, 4]);

    const get = vi.fn().mockResolvedValue({
      id: "credential-id",
      rawId: buffer(3, 4),
      type: "public-key",
      authenticatorAttachment: null,
      getClientExtensionResults: () => ({ appid: false }),
      response: {
        clientDataJSON: buffer(5),
        authenticatorData: buffer(6),
        signature: buffer(7),
        userHandle: null,
      },
    });
    Object.defineProperty(globalThis, "navigator", {
      configurable: true,
      value: { credentials: { get } },
    });
    const payload = await getPasskeyAssertion({
      challenge: "AQI",
      rpId: "vault.example",
      allowCredentials: [{ type: "public-key", id: "AwQ" }],
      userVerification: "required",
    });
    expect(get).toHaveBeenCalledOnce();
    expect(payload.response).toEqual({
      clientDataJSON: "BQ",
      authenticatorData: "Bg",
      signature: "Bw",
      userHandle: null,
    });
  });
});
