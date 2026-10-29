// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import NotPermitted from "./NotPermitted";

afterEach(() => {
  cleanup();
});

describe("NotPermitted", () => {
  it("renders the admin notice rather than a raw 403", () => {
    render(<NotPermitted />);

    expect(screen.getByText("Administrator access required.")).toBeTruthy();
    expect(screen.getByText("Not permitted")).toBeTruthy();
  });
});
