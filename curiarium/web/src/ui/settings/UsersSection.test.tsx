// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

// `UnauthorizedError` stays a real subclass: the section branches on `instanceof`.
vi.mock("../../lib/api", () => {
  class UnauthorizedError extends Error {
    constructor(message = "Unauthorized") {
      super(message);
      this.name = "UnauthorizedError";
    }
  }
  return {
    UnauthorizedError,
    listUsers: vi.fn(),
    createUser: vi.fn(),
    updateUser: vi.fn(),
    resetUserPassword: vi.fn(),
    // `SessionsSection` is imported for its label helpers, so its own calls
    // must exist on the mocked module too.
    listSessions: vi.fn(),
    revokeSession: vi.fn(),
    listUserSessions: vi.fn(),
    revokeUserSession: vi.fn(),
  };
});

import UsersSection, { formatCreatedAt } from "./UsersSection";
import {
  UnauthorizedError,
  createUser,
  listUserSessions,
  listUsers,
  resetUserPassword,
  revokeUserSession,
  updateUser,
  type User,
  type UserSession,
} from "../../lib/api";

const listUsersMock = vi.mocked(listUsers);
const createUserMock = vi.mocked(createUser);
const updateUserMock = vi.mocked(updateUser);
const resetUserPasswordMock = vi.mocked(resetUserPassword);
const listUserSessionsMock = vi.mocked(listUserSessions);
const revokeUserSessionMock = vi.mocked(revokeUserSession);

const CREATED_AT = "2024-01-02T03:04:05Z";

const ada: User = {
  id: "u-ada",
  username: "ada",
  email: "ada@example.com",
  role: "admin",
  disabled: false,
  auth_source: "local",
  oidc_issuer: null,
  oidc_subject: null,
  created_at: CREATED_AT,
  updated_at: CREATED_AT,
};

const bill: User = {
  id: "u-bill",
  username: "bill",
  email: null,
  role: "viewer",
  disabled: false,
  auth_source: "sso",
  oidc_issuer: "https://idp.example.com",
  oidc_subject: "sub-42",
  created_at: CREATED_AT,
  updated_at: CREATED_AT,
};

const cy: User = {
  id: "u-cy",
  username: "cy",
  email: null,
  role: "contributor",
  disabled: true,
  auth_source: "local",
  oidc_issuer: null,
  oidc_subject: null,
  created_at: CREATED_AT,
  updated_at: CREATED_AT,
};

const session: UserSession = {
  id: "sess-1",
  username: "ada",
  kind: "password",
  device: "Firefox on Linux",
  user_agent: null,
  client_ip: "10.0.0.5",
  created_at: 1735689600,
  last_used_at: 1735689600,
  current: false,
};

let directory: User[];

beforeEach(() => {
  directory = [ada, bill, cy];
  listUsersMock.mockReset();
  listUsersMock.mockImplementation(async () => directory);
  createUserMock.mockReset();
  createUserMock.mockResolvedValue(ada);
  updateUserMock.mockReset();
  updateUserMock.mockImplementation(async (id, patch) => {
    directory = directory.map(user => (user.id === id ? { ...user, ...patch } : user));
    return directory.find(user => user.id === id)!;
  });
  resetUserPasswordMock.mockReset();
  resetUserPasswordMock.mockResolvedValue(undefined);
  listUserSessionsMock.mockReset();
  listUserSessionsMock.mockResolvedValue([session]);
  revokeUserSessionMock.mockReset();
  revokeUserSessionMock.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
});

describe("UsersSection", () => {
  it("renders every account with its role, email, badges and created date", async () => {
    render(<UsersSection onBack={() => {}} username="ada" />);

    expect(await screen.findByText("ada")).toBeTruthy();
    expect(screen.getByText("bill")).toBeTruthy();
    expect(screen.getByText("cy")).toBeTruthy();
    expect(screen.getByText("ada@example.com")).toBeTruthy();
    expect(screen.getAllByText("no email").length).toBe(2);
    expect(screen.getAllByText("Disabled").length).toBe(1);
    const text = document.body.textContent || "";
    expect(text.split(`Created ${formatCreatedAt(CREATED_AT)}`).length - 1).toBe(3);
    expect(screen.getByText("You")).toBeTruthy();
    // A4: the local credential and the SSO binding are independent badges.
    expect(screen.getAllByText("Local password").length).toBe(2);
    expect(screen.getByText(/SSO · https:\/\/idp\.example\.com · sub-42/)).toBeTruthy();
    expect(listUsersMock).toHaveBeenCalledTimes(1);
  });

  it("offers admin in the create form's role select (A11)", async () => {
    render(<UsersSection onBack={() => {}} />);

    const select = (await screen.findByRole("combobox", {
      name: "Role",
    })) as HTMLSelectElement;
    const values = Array.from(select.querySelectorAll("option")).map(option => option.value);

    expect(values).toContain("admin");
    expect(select.value).toBe("viewer");
  });

  it("changes a role and shows the server's answer", async () => {
    render(<UsersSection onBack={() => {}} />);

    const select = (await screen.findByRole("combobox", {
      name: "Role for bill",
    })) as HTMLSelectElement;
    expect(select.value).toBe("viewer");

    fireEvent.change(select, { target: { value: "editor" } });

    await waitFor(() => expect(updateUserMock).toHaveBeenCalledWith("u-bill", { role: "editor" }));
    await waitFor(() =>
      expect(
        (screen.getByRole("combobox", { name: "Role for bill" }) as HTMLSelectElement).value,
      ).toBe("editor"),
    );
    expect(await screen.findByText("The role was updated.")).toBeTruthy();
  });

  it("disables an account and then marks it disabled", async () => {
    render(<UsersSection onBack={() => {}} />);

    fireEvent.click((await screen.findAllByRole("button", { name: "Disable" }))[0]);

    await waitFor(() => expect(updateUserMock).toHaveBeenCalledWith("u-ada", { disabled: true }));
    await waitFor(() => expect(screen.getAllByText("Disabled").length).toBe(2));
  });

  it("refuses an empty username without calling the API", async () => {
    render(<UsersSection onBack={() => {}} />);

    fireEvent.click(await screen.findByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Enter a username.")).toBeTruthy();
    expect(createUserMock).not.toHaveBeenCalled();
  });

  it("refuses a short password without calling the API", async () => {
    render(<UsersSection onBack={() => {}} />);

    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "newbie" },
    });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "abcd" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(
      await screen.findByText("The password must be at least 8 characters."),
    ).toBeTruthy();
    expect(createUserMock).not.toHaveBeenCalled();
  });

  it("creates an account with the values from the form", async () => {
    render(<UsersSection onBack={() => {}} />);

    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "newbie" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct-horse" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Role" }), {
      target: { value: "editor" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(createUserMock).toHaveBeenCalledWith({
        username: "newbie",
        password: "correct-horse",
        role: "editor",
      }),
    );
  });

  it("only sends allow_sso when the SSO checkbox is ticked", async () => {
    resetUserPasswordMock.mockRejectedValueOnce(
      new Error("this account signs in with SSO; give it a local password only if the identity provider is unavailable"),
    );
    render(<UsersSection onBack={() => {}} />);

    // bill is the SSO account and sits second in the list.
    fireEvent.click((await screen.findAllByRole("button", { name: "Reset password" }))[1]);
    fireEvent.change(screen.getByLabelText("New password for bill"), {
      target: { value: "correct-horse" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));

    await waitFor(() =>
      expect(resetUserPasswordMock).toHaveBeenCalledWith("u-bill", {
        password: "correct-horse",
      }),
    );

    fireEvent.click(
      screen.getByRole("checkbox", { name: /This account signs in with SSO/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Set password" }));

    await waitFor(() =>
      expect(resetUserPasswordMock).toHaveBeenLastCalledWith("u-bill", {
        password: "correct-horse",
        allow_sso: true,
      }),
    );
  });

  it("surfaces the server's last-admin sentence on a 409", async () => {
    updateUserMock.mockRejectedValueOnce(
      new Error("at least one enabled administrator is required"),
    );
    render(<UsersSection onBack={() => {}} />);

    fireEvent.change(await screen.findByRole("combobox", { name: "Role for ada" }), {
      target: { value: "viewer" },
    });

    expect(
      await screen.findByText("at least one enabled administrator is required"),
    ).toBeTruthy();
  });

  it("states the bootstrap rule on an empty directory", async () => {
    listUsersMock.mockResolvedValue([]);

    render(<UsersSection onBack={() => {}} />);

    expect(await screen.findByText("No accounts yet.")).toBeTruthy();
    const text = document.body.textContent || "";
    expect(text).toContain("no_admin_bootstrap");
    expect(text).toContain("must sign in locally once before SSO can create accounts");
    expect(text).toContain("break-glass");
  });

  it("expands the sessions panel, reusing the shared client calls", async () => {
    render(<UsersSection onBack={() => {}} />);

    fireEvent.click((await screen.findAllByRole("button", { name: "Sessions" }))[0]);

    expect(await screen.findByText("Firefox on Linux")).toBeTruthy();
    expect(listUserSessionsMock).toHaveBeenCalledWith("u-ada");

    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));

    await waitFor(() => expect(revokeUserSessionMock).toHaveBeenCalledWith("sess-1"));
    await waitFor(() => expect(listUserSessionsMock).toHaveBeenCalledTimes(2));
  });

  it("hands an UnauthorizedError from the list to the caller", async () => {
    const onUnauthorized = vi.fn();
    listUsersMock.mockRejectedValue(new UnauthorizedError());

    render(<UsersSection onBack={() => {}} onUnauthorized={onUnauthorized} />);

    await waitFor(() => expect(onUnauthorized).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Accounts are unavailable right now.")).toBeNull();
  });
});
