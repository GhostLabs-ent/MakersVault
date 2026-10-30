// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { Role } from "../lib/auth";
import SidebarFooter from "./SidebarFooter";

afterEach(() => {
  cleanup();
});

describe("SidebarFooter role gating", () => {
  it.each<[Role, boolean]>([
    ["viewer", false],
    ["editor", false],
    ["admin", true],
  ])("renders Settings always and Audit log only for an admin (%s)", (role, canAudit) => {
    render(<SidebarFooter role={role} />);

    expect(screen.getByRole("button", { name: "Settings" })).toBeTruthy();
    expect(!!screen.queryByRole("button", { name: "Audit log" })).toBe(canAudit);
  });

  it("leaves the audit entry out while the role is unknown", () => {
    render(<SidebarFooter />);

    expect(screen.getByRole("button", { name: "Settings" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Audit log" })).toBeNull();
  });

  it("still routes both clicks for an admin", () => {
    const onOpenSettings = vi.fn();
    const onOpenAudit = vi.fn();
    render(<SidebarFooter role="admin" onOpenSettings={onOpenSettings} onOpenAudit={onOpenAudit} />);

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Audit log" }));

    expect(onOpenSettings).toHaveBeenCalledTimes(1);
    expect(onOpenAudit).toHaveBeenCalledTimes(1);
  });
});
