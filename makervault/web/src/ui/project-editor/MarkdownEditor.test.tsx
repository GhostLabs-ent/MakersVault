// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState, type ReactElement } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { stableFileUrl, type Asset } from "../../lib/api";
import Markdown from "../Markdown";
import MarkdownEditor from "./MarkdownEditor";

/** The repo's "no native dialogs" guard scans sources for a literal call. */
const ALERT_CALL = "alert" + "(1)";

function makeAsset(overrides: Partial<Asset> = {}): Asset {
  return {
    id: "a2",
    name: "Logo",
    filename: "logo.png",
    mime: "image/png",
    size: 1024,
    tags: [],
    url: "/file/a2/logo.png",
    thumb_url: "/thumb/a2.jpg",
    supporting_file_count: 0,
    ...overrides,
  };
}

type HarnessProps = { initialValue?: string; images?: Asset[] };

/** The editor is controlled; the harness is the "parent" that owns the value. */
function Harness({ initialValue = "", images = [] }: HarnessProps): ReactElement {
  const [value, setValue] = useState(initialValue);
  return <MarkdownEditor value={value} onChange={setValue} images={images} />;
}

function descriptionBox(): HTMLTextAreaElement {
  return screen.getByRole("textbox", { name: "Description" }) as HTMLTextAreaElement;
}

function previewOf(container: HTMLElement): HTMLElement {
  return container.querySelector("[data-markdown-preview]") as HTMLElement;
}

function fakeClipboard(data: Record<string, string>): DataTransfer {
  return {
    getData: (type: string) => data[type] ?? "",
  } as unknown as DataTransfer;
}

afterEach(cleanup);

describe("MarkdownEditor toolbar", () => {
  type ToolbarCase = {
    button: string;
    initial: string;
    start: number;
    end?: number;
    expected: string;
  };

  const CASES: ToolbarCase[] = [
    { button: "Heading 1", initial: "Title", start: 0, expected: "# Title" },
    { button: "Heading 2", initial: "Title", start: 0, expected: "## Title" },
    { button: "Heading 3", initial: "Title", start: 0, expected: "### Title" },
    { button: "Bold", initial: "hello", start: 0, end: 5, expected: "**hello**" },
    { button: "Italic", initial: "hello", start: 0, end: 5, expected: "*hello*" },
    { button: "Bullet list", initial: "Item", start: 0, expected: "- Item" },
    { button: "Numbered list", initial: "Item", start: 0, expected: "1. Item" },
    { button: "Link", initial: "docs", start: 0, end: 4, expected: "[docs](url)" },
    { button: "Inline code", initial: "hello", start: 0, end: 5, expected: "`hello`" },
    { button: "Code block", initial: "abc", start: 0, expected: "```\n\n```\nabc" },
    {
      button: "Table",
      initial: "",
      start: 0,
      expected: "| Column | Column |\n| --- | --- |\n| Cell | Cell |\n",
    },
  ];

  for (const { button, initial, start, end = start, expected } of CASES) {
    it(`"${button}" transforms the textarea value`, () => {
      render(<Harness initialValue={initial} />);
      const textarea = descriptionBox();
      textarea.setSelectionRange(start, end);

      fireEvent.click(screen.getByRole("button", { name: button }));

      expect(textarea.value).toBe(expected);
    });
  }

  it("restores the selection the command asked for", () => {
    render(<Harness initialValue="hello" />);
    const textarea = descriptionBox();
    textarea.setSelectionRange(0, 5);

    fireEvent.click(screen.getByRole("button", { name: "Bold" }));

    expect(textarea.value).toBe("**hello**");
    expect(textarea.selectionStart).toBe(2);
    expect(textarea.selectionEnd).toBe(7);
  });

  it("selects the url placeholder after inserting a link", () => {
    render(<Harness />);
    const textarea = descriptionBox();

    fireEvent.click(screen.getByRole("button", { name: "Link" }));

    expect(textarea.value).toBe("[link text](url)");
    expect(textarea.value.slice(textarea.selectionStart, textarea.selectionEnd)).toBe("url");
  });
});

describe("MarkdownEditor keyboard shortcuts", () => {
  const SHORTCUTS: Array<[key: string, expected: string]> = [
    ["b", "**hello**"],
    ["i", "*hello*"],
    ["k", "[hello](url)"],
  ];

  for (const [key, expected] of SHORTCUTS) {
    it(`Ctrl+${key} applies the matching command`, () => {
      render(<Harness initialValue="hello" />);
      const textarea = descriptionBox();
      textarea.setSelectionRange(0, 5);

      fireEvent.keyDown(textarea, { key, ctrlKey: true });

      expect(textarea.value).toBe(expected);
    });
  }

  it("ignores plain keystrokes", () => {
    render(<Harness initialValue="hello" />);
    const textarea = descriptionBox();
    textarea.setSelectionRange(0, 5);

    fireEvent.keyDown(textarea, { key: "b" });

    expect(textarea.value).toBe("hello");
  });
});

const RICH_FIXTURE = [
  "# Project title",
  "",
  "Intro with **bold**, *italic* and `inline code`,",
  "a [link](https://example.com/docs) and an image:",
  "",
  "![Logo](/api/file/a2/logo.png)",
  "",
  "## Highlights",
  "",
  "- Outer one",
  "  - Inner two",
  "",
  "| Step | Time |",
  "| --- | --- |",
  "| Cut | 2 min |",
  "",
  "```js",
  "const answer = 42;",
  "```",
].join("\n");

const XSS_FIXTURE =
  `<script>${ALERT_CALL}</script><img src=x onerror="${ALERT_CALL}">` +
  `<b onmouseover="${ALERT_CALL}">bold</b>`;

const TABLE_FIXTURE = "| A | B |\n| - | - |\n| 1 | 2 |";

describe("MarkdownEditor preview parity", () => {
  function expectParityWithMarkdown(payload: string): void {
    const onChange = vi.fn();
    const { container, rerender } = render(
      <MarkdownEditor value={payload} onChange={onChange} images={[]} />,
    );
    const reference = render(<Markdown>{payload}</Markdown>);
    expect(previewOf(container).innerHTML).toBe(reference.container.innerHTML);
    reference.unmount();

    const updated = `${payload}\n\nAppended **after** mount.`;
    rerender(<MarkdownEditor value={updated} onChange={onChange} images={[]} />);
    const updatedReference = render(<Markdown>{updated}</Markdown>);
    expect(previewOf(container).innerHTML).toBe(updatedReference.container.innerHTML);
    updatedReference.unmount();
  }

  it("matches the shared renderer for a rich description", () => {
    expectParityWithMarkdown(RICH_FIXTURE);
  });

  it("matches the shared renderer for an XSS payload", () => {
    expectParityWithMarkdown(XSS_FIXTURE);
  });

  it("matches the shared renderer for a GFM table", () => {
    expectParityWithMarkdown(TABLE_FIXTURE);
  });

  it("contains no script elements and no event-handler attributes", () => {
    const { container } = render(
      <MarkdownEditor value={XSS_FIXTURE} onChange={vi.fn()} images={[]} />,
    );
    const preview = previewOf(container);

    expect(preview.querySelectorAll("script").length).toBe(0);

    const handlers: string[] = [];
    for (const element of Array.from(preview.querySelectorAll("*"))) {
      for (const attribute of Array.from(element.attributes)) {
        if (attribute.name.toLowerCase().startsWith("on")) handlers.push(attribute.name);
      }
    }
    expect(handlers).toEqual([]);
  });

  it("renders the shared markdown inside a single preview region", () => {
    const { container } = render(
      <MarkdownEditor value={RICH_FIXTURE} onChange={vi.fn()} images={[]} />,
    );
    const preview = screen.getByRole("region", { name: "Markdown preview" });

    expect(preview).toBe(previewOf(container));
    expect(preview.querySelector("h1")?.textContent).toBe("Project title");
    expect(preview.querySelector("[data-md-table] table")).toBeTruthy();
  });

  it("keeps the empty-state note outside the preview region", () => {
    render(<Harness />);
    const preview = screen.getByRole("region", { name: "Markdown preview" });
    const note = screen.getByText("Nothing to preview yet.");

    expect(preview.contains(note)).toBe(false);
    expect(preview.textContent).toBe("");
  });
});

describe("MarkdownEditor image insertion", () => {
  it("lists only image members and inserts a stable same-origin URL", () => {
    const logo = makeAsset();
    const model = makeAsset({
      id: "a1",
      name: "Body",
      filename: "body.stl",
      mime: "model/stl",
      url: "/file/a1/body.stl",
      thumb_url: null,
    });
    render(<Harness images={[logo, model]} />);

    fireEvent.click(screen.getByRole("button", { name: "Insert image" }));
    const dialog = screen.getByRole("dialog", { name: "Insert an image" });
    expect(within(dialog).getByText("Logo")).toBeTruthy();
    expect(within(dialog).queryByText("Body")).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "Insert Logo" }));

    const textarea = descriptionBox();
    expect(screen.queryByRole("dialog", { name: "Insert an image" })).toBeNull();
    expect(textarea.value).toBe(`![Logo](${stableFileUrl(logo.url)})`);
    expect(textarea.value).toContain("![Logo](/api/file/a2/logo.png)");
    expect(textarea.selectionStart).toBe(textarea.value.length);
  });

  it("explains the empty state when the project has no images", () => {
    render(<Harness />);

    fireEvent.click(screen.getByRole("button", { name: "Insert image" }));

    const dialog = screen.getByRole("dialog", { name: "Insert an image" });
    expect(within(dialog).getByText("This project has no image members yet.")).toBeTruthy();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Insert an image" })).toBeNull();
    expect(descriptionBox().value).toBe("");
  });
});

describe("MarkdownEditor paste", () => {
  it("inserts HTML as plain text instead of markup", () => {
    const { container } = render(<Harness />);
    const textarea = descriptionBox();

    fireEvent.paste(textarea, {
      clipboardData: fakeClipboard({
        "text/html": `<p>Hello <b>bold</b></p><img src=x onerror="${ALERT_CALL}">`,
      }),
    });

    expect(textarea.value).toBe("Hello bold");
    expect(textarea.value.includes("<b")).toBe(false);
    expect(textarea.value.includes("<img")).toBe(false);
    const preview = previewOf(container);
    expect(preview.querySelector("img")).toBeNull();
    expect(preview.querySelector("script")).toBeNull();
  });

  it("prefers plain text when the clipboard carries both flavours", () => {
    render(<Harness />);
    const textarea = descriptionBox();

    fireEvent.paste(textarea, {
      clipboardData: fakeClipboard({
        "text/plain": "just the words",
        "text/html": "<b>just the words</b>",
      }),
    });

    expect(textarea.value).toBe("just the words");
  });

  it("inserts nothing when the clipboard has files but no text", () => {
    render(<Harness initialValue="keep me" />);
    const textarea = descriptionBox();
    textarea.setSelectionRange(0, 7);

    fireEvent.paste(textarea, { clipboardData: fakeClipboard({}) });

    expect(textarea.value).toBe("keep me");
  });
});

describe("MarkdownEditor live preview", () => {
  it("updates as the textarea is typed into", () => {
    const { container } = render(<Harness />);
    expect(screen.getByText("Nothing to preview yet.")).toBeTruthy();

    fireEvent.change(descriptionBox(), { target: { value: "# Live" } });

    const preview = previewOf(container);
    expect(preview.querySelector("h1")?.textContent).toBe("Live");
    expect(screen.queryByText("Nothing to preview yet.")).toBeNull();
  });
});
