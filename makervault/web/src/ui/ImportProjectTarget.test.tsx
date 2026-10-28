// @vitest-environment jsdom
import { useCallback, useState, type ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

// Only the network layer is mocked: the control's own state machine (lazy
// list, fallback to a new project) runs for real.
vi.mock("../lib/api", () => ({
  UnauthorizedError: class UnauthorizedError extends Error {
    constructor(message = "Unauthorized") {
      super(message);
      this.name = "UnauthorizedError";
    }
  },
  listProjects: vi.fn(),
}));

import { listProjects, type Project } from "../lib/api";
import type { ImportProjectTarget as Target } from "../lib/importProject";
import ImportProjectTarget from "./ImportProjectTarget";

const listProjectsMock = vi.mocked(listProjects);

function project(id: string, name: string): Project {
  return {
    id,
    name,
    description: null,
    creator: null,
    source_url: null,
    licence: null,
    licence_url: null,
    origin: "local",
    cover_asset_id: null,
    cover_thumb_url: null,
    asset_count: 0,
    metadata_json: {},
    total_size: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
  };
}

/** The control is fully controlled, so the harness owns the target state. */
function renderTarget(): { changes: Target[] } {
  const changes: Target[] = [];
  function Harness(): ReactElement {
    const [value, setValue] = useState<Target>({ kind: "none" });
    const onChange = useCallback((next: Target) => {
      changes.push(next);
      setValue(next);
    }, []);
    return <ImportProjectTarget value={value} onChange={onChange} />;
  }
  render(<Harness />);
  return { changes };
}

function selectExisting() {
  fireEvent.click(screen.getByRole("radio", { name: "Existing project" }));
}

describe("ImportProjectTarget", () => {
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.resetAllMocks();
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    cleanup();
    consoleError.mockRestore();
  });

  it("offers the three targets as a labelled radio group", () => {
    renderTarget();

    const group = screen.getByRole("radiogroup", { name: "Import into" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map(radio => (radio as HTMLInputElement).labels?.[0]?.textContent)).toEqual([
      "No project",
      "New project from the page",
      "Existing project",
    ]);
    expect((radios[0] as HTMLInputElement).checked).toBe(true);
  });

  it("loads the project list once and reports the project the user picks", async () => {
    listProjectsMock.mockResolvedValue([project("p1", "Hydra"), project("p2", "Kraken")]);
    const { changes } = renderTarget();

    selectExisting();

    await waitFor(() =>
      expect(changes).toContainEqual({ kind: "existing", projectId: "p1", projectName: "Hydra" }),
    );
    expect(listProjectsMock).toHaveBeenCalledTimes(1);

    const select = screen.getByRole("combobox", { name: "Project" });
    fireEvent.change(select, { target: { value: "p2" } });

    expect(changes[changes.length - 1]).toEqual({
      kind: "existing",
      projectId: "p2",
      projectName: "Kraken",
    });
    // Picking a project from the already-loaded list never refetches it.
    expect(listProjectsMock).toHaveBeenCalledTimes(1);
  });

  it("falls back to a new project when there are no projects to join", async () => {
    listProjectsMock.mockResolvedValue([]);
    const { changes } = renderTarget();

    selectExisting();

    await screen.findByText(/No projects yet/);
    expect(changes[changes.length - 1]).toEqual({ kind: "new" });
    expect(screen.queryByRole("combobox", { name: "Project" })).toBeNull();
    // The radio group says where the import will land.
    expect((screen.getByRole("radio", { name: "New project from the page" }) as HTMLInputElement).checked).toBe(true);

    // Asking again shows the same note from the loaded (empty) list.
    selectExisting();
    await screen.findByText(/No projects yet/);
    expect(listProjectsMock).toHaveBeenCalledTimes(1);
  });

  it("falls back to a new project when the project list cannot be loaded", async () => {
    listProjectsMock.mockRejectedValue(new Error("boom"));
    const { changes } = renderTarget();

    selectExisting();

    await screen.findByText(/Could not load the project list/);
    expect(changes[changes.length - 1]).toEqual({ kind: "new" });
    expect(consoleError).toHaveBeenCalled();
  });
});
