import {
  beginPasskeyReauthentication,
  completePasskeyReauthentication,
  reauthenticateSession,
} from "./api";
import { getPasskeyAssertion } from "./passkeys";


export async function confirmCurrentAuthentication(password: string): Promise<void> {
  const result = await reauthenticateSession(password);
  if (!result.mfa_required) return;
  const options = await beginPasskeyReauthentication();
  const credential = await getPasskeyAssertion(options);
  await completePasskeyReauthentication(credential);
}
