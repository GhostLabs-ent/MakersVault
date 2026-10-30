// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import ModeSwitch from "./ModeSwitch";

afterEach(cleanup);

describe("ModeSwitch", () => {
  it("renders a radiogroup with one checked, tabbable option", () => {
    render(<ModeSwitch mode="files" onChange={vi.fn()} />);

    const group = screen.getByRole("radiogroup", { name: "Library mode" });
    expect(group).toBeTruthy();

    const files = screen.getByRole("radio", { name: "Files" });
    const projects = screen.getByRole("radio", { name: "Projects" });
    expect(files.getAttribute("aria-checked")).toBe("true");
    expect(projects.getAttribute("aria-checked")).toBe("false");
    expect((files as HTMLButtonElement).tabIndex).toBe(0);
    expect((projects as HTMLButtonElement).tabIndex).toBe(-1);
  });

  it("selects the clicked option", () => {
    const onChange = vi.fn();
    render(<ModeSwitch mode="files" onChange={onChange} />);

    fireEvent.click(screen.getByRole("radio", { name: "Projects" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("projects");
  });

  it("moves selection with the arrow keys and follows focus", () => {
    const onChange = vi.fn();
    render(<ModeSwitch mode="files" onChange={onChange} />);

    const files = screen.getByRole("radio", { name: "Files" });
    const projects = screen.getByRole("radio", { name: "Projects" });
    const group = screen.getByRole("radiogroup", { name: "Library mode" });

    fireEvent.keyDown(files, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("projects");
    expect(document.activeElement).toBe(projects);

    fireEvent.keyDown(files, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("projects");

    // Wrapping happens in both directions off the endpoint.
    fireEvent.keyDown(group, { key: "ArrowUp" });
    expect(onChange).toHaveBeenLastCalledWith("projects");
  });

  it("wraps from projects back to files", () => {
    const onChange = vi.fn();
    render(<ModeSwitch mode="projects" onChange={onChange} />);

    fireEvent.keyDown(screen.getByRole("radio", { name: "Projects" }), { key: "ArrowRight" });

    expect(onChange).toHaveBeenLastCalledWith("files");
  });

  it("jumps to the first/last option with Home/End and updates the roving tab stop", () => {
    const onChange = vi.fn();
    const { rerender } = render(<ModeSwitch mode="projects" onChange={onChange} />);

    fireEvent.keyDown(screen.getByRole("radio", { name: "Projects" }), { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("files");

    rerender(<ModeSwitch mode="files" onChange={onChange} />);
    expect((screen.getByRole("radio", { name: "Files" }) as HTMLButtonElement).tabIndex).toBe(0);
    expect(
      (screen.getByRole("radio", { name: "Projects" }) as HTMLButtonElement).tabIndex,
    ).toBe(-1);

    fireEvent.keyDown(screen.getByRole("radio", { name: "Files" }), { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("projects");

    rerender(<ModeSwitch mode="projects" onChange={onChange} />);
    expect(
      (screen.getByRole("radio", { name: "Projects" }) as HTMLButtonElement).tabIndex,
    ).toBe(0);
  });
});
