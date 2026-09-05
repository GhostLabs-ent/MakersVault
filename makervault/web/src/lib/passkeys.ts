export type PasskeyCredentialPayload = {
  id: string;
  rawId: string;
  type: "public-key";
  authenticatorAttachment?: string | null;
  clientExtensionResults: AuthenticationExtensionsClientOutputs;
  response: Record<string, string | string[] | null>;
};


function bytesFromBase64Url(value: unknown): Uint8Array {
  if (typeof value !== "string" || !value) {
    throw new Error("The server returned invalid passkey options.");
  }
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/")
    + "=".repeat((4 - value.length % 4) % 4);
  const decoded = atob(base64);
  return Uint8Array.from(decoded, character => character.charCodeAt(0));
}


function base64UrlFromBytes(value: ArrayBuffer | ArrayBufferView): string {
  const bytes = value instanceof ArrayBuffer
    ? new Uint8Array(value)
    : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}


export function decodeRegistrationOptions(
  options: Record<string, unknown>,
): PublicKeyCredentialCreationOptions {
  const user = options.user as Record<string, unknown> | undefined;
  if (!user) throw new Error("The server returned invalid passkey options.");
  const excluded = Array.isArray(options.excludeCredentials)
    ? options.excludeCredentials as Array<Record<string, unknown>>
    : [];
  return {
    ...options,
    challenge: bytesFromBase64Url(options.challenge),
    user: { ...user, id: bytesFromBase64Url(user.id) },
    excludeCredentials: excluded.map(item => ({
      ...item,
      id: bytesFromBase64Url(item.id),
    })),
  } as unknown as PublicKeyCredentialCreationOptions;
}


export function decodeAuthenticationOptions(
  options: Record<string, unknown>,
): PublicKeyCredentialRequestOptions {
  const allowed = Array.isArray(options.allowCredentials)
    ? options.allowCredentials as Array<Record<string, unknown>>
    : [];
  return {
    ...options,
    challenge: bytesFromBase64Url(options.challenge),
    allowCredentials: allowed.map(item => ({
      ...item,
      id: bytesFromBase64Url(item.id),
    })),
  } as unknown as PublicKeyCredentialRequestOptions;
}


function credentialBase(credential: PublicKeyCredential) {
  return {
    id: credential.id,
    rawId: base64UrlFromBytes(credential.rawId),
    type: "public-key" as const,
    authenticatorAttachment: credential.authenticatorAttachment,
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}


function credentialsContainer(): CredentialsContainer {
  if (typeof navigator === "undefined" || !navigator.credentials) {
    throw new Error("This browser does not support passkeys.");
  }
  return navigator.credentials;
}


export async function createPasskeyCredential(
  options: Record<string, unknown>,
): Promise<PasskeyCredentialPayload> {
  const credential = await credentialsContainer().create({
    publicKey: decodeRegistrationOptions(options),
  }) as PublicKeyCredential | null;
  if (!credential) throw new Error("Passkey registration was canceled.");
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    ...credentialBase(credential),
    response: {
      clientDataJSON: base64UrlFromBytes(response.clientDataJSON),
      attestationObject: base64UrlFromBytes(response.attestationObject),
      transports: typeof response.getTransports === "function"
        ? response.getTransports()
        : [],
    },
  };
}


export async function getPasskeyAssertion(
  options: Record<string, unknown>,
): Promise<PasskeyCredentialPayload> {
  const credential = await credentialsContainer().get({
    publicKey: decodeAuthenticationOptions(options),
  }) as PublicKeyCredential | null;
  if (!credential) throw new Error("Passkey verification was canceled.");
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    ...credentialBase(credential),
    response: {
      clientDataJSON: base64UrlFromBytes(response.clientDataJSON),
      authenticatorData: base64UrlFromBytes(response.authenticatorData),
      signature: base64UrlFromBytes(response.signature),
      userHandle: response.userHandle
        ? base64UrlFromBytes(response.userHandle)
        : null,
    },
  };
}
