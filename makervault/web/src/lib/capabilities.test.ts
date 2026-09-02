import { describe, expect, it } from "vitest";

import { capabilitiesForRole } from "./capabilities";


describe("shared-vault role capabilities", () => {
  it("keeps viewers read-only while preserving downloads, exports, and handoff", () => {
    const capabilities = capabilitiesForRole("viewer");
    expect(capabilities.readVault).toBe(true);
    expect(capabilities.downloadContent).toBe(true);
    expect(capabilities.exportContent).toBe(true);
    expect(capabilities.createHandoff).toBe(true);
    expect(capabilities.manageContent).toBe(false);
    expect(capabilities.openTrash).toBe(false);
    expect(capabilities.manageServerSettings).toBe(false);
  });

  it("lets members manage recoverable shared content but not permanent deletion", () => {
    const capabilities = capabilitiesForRole("member");
    expect(capabilities.manageContent).toBe(true);
    expect(capabilities.openTrash).toBe(true);
    expect(capabilities.restoreTrash).toBe(true);
    expect(capabilities.deletePermanently).toBe(false);
    expect(capabilities.manageServerSettings).toBe(false);
  });

  it("reserves privileged operations for administrators", () => {
    const capabilities = capabilitiesForRole("administrator");
    expect(capabilities.manageContent).toBe(true);
    expect(capabilities.manageServerSettings).toBe(true);
    expect(capabilities.manageDurableJobs).toBe(true);
    expect(capabilities.deletePermanently).toBe(true);
    expect(capabilities.emptyTrash).toBe(true);
  });
});
