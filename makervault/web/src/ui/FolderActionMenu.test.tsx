import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import FolderActionMenu from "./FolderActionMenu";

describe("closed folder action menus", () => {
  it("keeps an accessible native disclosure without constructing hidden actions", () => {
    const actions = vi.fn(() => <button>Delete</button>);
    const html = renderToStaticMarkup(<FolderActionMenu name="Brackets">{actions}</FolderActionMenu>);
    expect(html).toContain('<details>');
    expect(html).toContain('aria-label="Actions for Brackets"');
    expect(html).not.toContain('sidebar-folder-menu');
    expect(html).not.toContain('<button');
    expect(actions).not.toHaveBeenCalled();
  });

  it("does not create menu contents for an initially expanded 400-row tree", () => {
    const actions = vi.fn(() => <button>Download ZIP</button>);
    const html = renderToStaticMarkup(<>{Array.from({ length: 400 }, (_, id) =>
      <FolderActionMenu key={id} name={`Folder ${id}`}>{actions}</FolderActionMenu>)}</>);
    expect(html.match(/<details>/g)).toHaveLength(400);
    expect(html).not.toContain('sidebar-folder-menu');
    expect(actions).not.toHaveBeenCalled();
  });
});
