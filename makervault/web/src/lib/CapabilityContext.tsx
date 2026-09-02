import React from "react";

import {
  capabilitiesForRole,
  type VaultCapabilities,
  type VaultRole,
} from "./capabilities";


const CapabilityContext = React.createContext<VaultCapabilities>(
  capabilitiesForRole("viewer"),
);


export function CapabilityProvider({
  role,
  children,
}: {
  role: VaultRole;
  children: React.ReactNode;
}) {
  const capabilities = React.useMemo(() => capabilitiesForRole(role), [role]);
  return (
    <CapabilityContext.Provider value={capabilities}>
      {children}
    </CapabilityContext.Provider>
  );
}


export function useVaultCapabilities(): VaultCapabilities {
  return React.useContext(CapabilityContext);
}
