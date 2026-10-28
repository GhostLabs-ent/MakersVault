// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { clearToken, storeToken } from "../lib/auth";
import Markdown, { safeUrlTransform } from "./Markdown";

/**
 * jsdom reports a `window.localStorage` getter but, under Node's experimental
 * global localStorage, it resolves to `undefined`; install a real in-memory
 * Storage so the code under test finds a working store.
 */
function installMemoryStorage(): void {
  const store = new Map<string, string>();
  const storage: Storage = {
    get length(): number {
      return store.size;
    },
    clear(): void {
      store.clear();
    },
    getItem(key: string): string | null {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number): string | null {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string): void {
      store.delete(key);
    },
    setItem(key: string, value: string): void {
      store.set(key, String(value));
    },
  };
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
}

function renderMarkdown(markdown: string): HTMLElement {
  const { container } = render(<Markdown>{markdown}</Markdown>);
  return container;
}

function textOf(container: HTMLElement, selector: string): string[] {
  return Array.from(container.querySelectorAll(selector)).map(
    (element) => element.textContent ?? "",
  );
}

const FIXTURE = [
  "# Project title",
  "",
  "Intro paragraph with **bold**, *italic*, ~~struck~~ text, `inline code`,",
  "a [link](https://example.com/docs) and an emoji 🚀.",
  "",
  "## Highlights",
  "",
  "- Outer one",
  "  - Inner two",
  "  - Inner three",
  "- Outer two",
  "",
  "1. First step",
  "2. Second step",
  "   1. Nested ordered",
  "",
  "> Quoted wisdom",
  "",
  "### Benchmarks",
  "",
  "| Step | Time | Notes |",
  "| :--- | :---: | ---: |",
  "| Cut | 2 min | *fast* |",
  "| Weld | 10 min | hot |",
  "",
  "```js",
  "const answer = 42;",
  "```",
  "",
  "---",
  "",
  "![Fixture image](/asset/1/preview.png)",
].join("\n");

describe("Markdown rendering", () => {
  afterEach(cleanup);

  it("renders headings, nested lists, GFM table, code, inline marks, link, image, emoji, quote", () => {
    const container = renderMarkdown(FIXTURE);

    // Headings h1-h3 with their real text.
    expect(Array.from(container.querySelectorAll("h1,h2,h3")).length).toBe(3);
    expect(textOf(container, "h1")).toEqual(["Project title"]);
    expect(textOf(container, "h2")).toEqual(["Highlights"]);
    expect(textOf(container, "h3")).toEqual(["Benchmarks"]);

    // Inline marks and the literal emoji survive as text, not as markup.
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("em")?.textContent).toBe("italic");
    expect(container.querySelector("del")?.textContent).toBe("struck");
    expect(container.textContent ?? "").toContain("🚀");

    // GFM table: header cells, body cells and per-column alignment.
    const table = container.querySelector("[data-md-table] table");
    expect(table).toBeTruthy();
    expect(textOf(container, "table th")).toEqual(["Step", "Time", "Notes"]);
    expect(textOf(container, "table tbody tr:first-child td")).toEqual([
      "Cut",
      "2 min",
      "fast",
    ]);
    // GFM column alignment reaches the DOM as an inline `text-align`.
    expect(
      Array.from(container.querySelectorAll("table th")).map(
        (cell) => (cell as HTMLElement).style.textAlign,
      ),
    ).toEqual(["left", "center", "right"]);

    // Fenced block keeps its language class; inline code stays inline.
    const code = container.querySelector("pre code");
    expect(code).toBeTruthy();
    expect((code?.className ?? "").includes("language-js")).toBe(true);
    // Fenced code keeps its trailing newline from the source block.
    expect(code?.textContent?.trim()).toBe("const answer = 42;");
    expect(textOf(container, "p code")).toEqual(["inline code"]);

    // Links, images, quote, rule.
    const link = container.querySelector("a");
    expect(link?.getAttribute("href")).toBe("https://example.com/docs");
    expect(link?.textContent).toBe("link");
    const image = container.querySelector("img");
    expect(image?.getAttribute("src")).toBe("/asset/1/preview.png");
    expect(image?.getAttribute("alt")).toBe("Fixture image");
    expect(container.querySelector("blockquote")?.textContent?.trim()).toBe("Quoted wisdom");
    expect(container.querySelector("hr")).toBeTruthy();

    // Nested list depth is real: a ul inside an li inside a ul, and an ol in an ol.
    const nestedUnordered = container.querySelector("ul > li > ul");
    expect(nestedUnordered).toBeTruthy();
    expect(textOf(container, "ul > li > ul > li")).toEqual([
      "Inner two",
      "Inner three",
    ]);
    const nestedOrdered = container.querySelector("ol > li > ol > li");
    expect(nestedOrdered?.textContent).toBe("Nested ordered");
  });
});

/**
 * One `it` per attack vector. Note: vitest's jsdom runs with
 * `runScripts: "dangerously"`, so "no script element exists in the DOM" is the
 * honest assertion to make here — jsdom would happily execute an injected
 * script, which is exactly why the sanitiser must never emit one.
 */
/**
 * The payload body is assembled instead of written out: the repo-wide "no
 * native dialogs" guard test scans *every* source line for a call to the
 * `alert`/`confirm` globals, and a literal one here would trip it.
 */
const ALERT_CALL: string = "alert" + "(1)";

const XSS_VECTORS: Array<[name: string, markdown: string]> = [
  ["a script tag", `<script>${ALERT_CALL}</script>`],
  ["an img with an inline error handler", `<img src=x onerror="${ALERT_CALL}">`],
  ["a javascript: link", `[x](javascript:${ALERT_CALL})`],
  ["a data: image", "![x](data:text/html;base64,PHNjcmlwdD4=)"],
  ["an iframe", '<iframe src="https://evil"></iframe>'],
  ["an svg with an onload handler", `<svg onload="${ALERT_CALL}"></svg>`],
  ["a bold tag with an onmouseover handler", `<b onmouseover="${ALERT_CALL}">bold</b>`],
  ["a mixed-case javascript: link", `[x](JaVaScRiPt:${ALERT_CALL})`],
  ["a leading-whitespace javascript: link", `[x](  javascript:${ALERT_CALL})`],
  ["an anchor tag with a javascript: href", `<a href="javascript:${ALERT_CALL}">x</a>`],
  ["a vbscript: image", "![x](vbscript:msgbox(1))"],
  ["a style tag", "<style>body{display:none}</style>"],
];

const FORBIDDEN_TAGS = "script,iframe,object,embed,style,base,form,link,meta";
const DANGEROUS_URL = /^\s*(javascript|data|vbscript|file):/i;

/** One shared DOM assertion: nothing executable, nothing dangerous, no handler. */
function expectInertDom(container: HTMLElement): void {
  const forbidden = Array.from(container.querySelectorAll(FORBIDDEN_TAGS)).map(
    (element) => element.tagName.toLowerCase(),
  );
  expect(forbidden.join(",")).toBe("");

  const violations: string[] = [];
  for (const element of Array.from(container.querySelectorAll("*"))) {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on")) {
        violations.push(`handler ${name} on <${element.tagName.toLowerCase()}>`);
      }
      if ((name === "href" || name === "src") && DANGEROUS_URL.test(attribute.value)) {
        violations.push(`${name}="${attribute.value}" on <${element.tagName.toLowerCase()}>`);
      }
    }
  }
  expect(violations.join(", ")).toBe("");

  expect((container.textContent ?? "").includes("<script")).toBe(false);
}

describe("Markdown XSS corpus", () => {
  afterEach(cleanup);

  for (const [name, markdown] of XSS_VECTORS) {
    it(`renders ${name} inert`, () => {
      const container = renderMarkdown(markdown);
      expectInertDom(container);
    });
  }

  it("leaves a javascript: link with no usable javascript: href", () => {
    const container = renderMarkdown(`[x](javascript:${ALERT_CALL})`);
    const anchor = container.querySelector("a") as HTMLAnchorElement | null;

    // The anchor may survive (react-markdown blanks the URL to ""), but the
    // resolved href must never still be a javascript: URL.
    expect((anchor?.href ?? "").toLowerCase().startsWith("javascript:")).toBe(false);
  });

  it("drops data: image sources entirely", () => {
    const container = renderMarkdown("![x](data:text/html;base64,PHNjcmlwdD4=)");
    const image = container.querySelector("img");
    expect((image?.getAttribute("src") ?? "").toLowerCase().startsWith("data:")).toBe(false);
  });
});

describe("Markdown link hardening", () => {
  afterEach(cleanup);

  it("opens absolute https links in a new tab with a noopener rel", () => {
    const container = renderMarkdown("[docs](https://example.com/docs)");
    const anchor = container.querySelector("a");

    expect(anchor?.getAttribute("target")).toBe("_blank");
    expect(anchor?.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("keeps relative links in place while still setting rel", () => {
    const container = renderMarkdown("[asset](/asset/1/x)");
    const anchor = container.querySelector("a");

    expect(anchor?.getAttribute("href")).toBe("/asset/1/x");
    expect(anchor?.getAttribute("target")).toBeNull();
    expect(anchor?.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("does not open mailto links in a new tab", () => {
    const container = renderMarkdown("[mail](mailto:maker@example.com)");
    const anchor = container.querySelector("a");

    expect(anchor?.getAttribute("target")).toBeNull();
    expect(anchor?.getAttribute("rel")).toBe("noopener noreferrer");
  });
});

describe("Markdown narrow viewports", () => {
  afterEach(cleanup);

  it("wraps tables in a horizontally scrollable container", () => {
    const container = renderMarkdown("| A | B |\n| - | - |\n| 1 | 2 |");
    const wrapper = container.querySelector("[data-md-table]");

    expect(wrapper).toBeTruthy();
    expect((wrapper?.className ?? "").includes("overflow-x-auto")).toBe(true);
    expect(wrapper?.querySelector("table")).toBeTruthy();
  });
});

describe("safeUrlTransform", () => {
  it("blanks blocked schemes of any case", () => {
    expect(safeUrlTransform(`javascript:${ALERT_CALL}`)).toBe("");
    expect(safeUrlTransform(`JaVaScRiPt:${ALERT_CALL}`)).toBe("");
    expect(safeUrlTransform("vbscript:msgbox(1)")).toBe("");
    expect(safeUrlTransform("data:text/html;base64,PHNjcmlwdD4=")).toBe("");
    expect(safeUrlTransform("file:///etc/passwd")).toBe("");
  });

  it("blanks blocked schemes hidden behind leading whitespace and control chars", () => {
    expect(safeUrlTransform(`   javascript:${ALERT_CALL}`)).toBe("");
    expect(safeUrlTransform(`\u0000\tjavascript:${ALERT_CALL}`)).toBe("");
  });

  it("keeps ordinary and relative URLs unchanged", () => {
    expect(safeUrlTransform("https://example.com/docs")).toBe("https://example.com/docs");
    expect(safeUrlTransform("mailto:maker@example.com")).toBe("mailto:maker@example.com");
    expect(safeUrlTransform("/asset/1/x")).toBe("/asset/1/x");
    expect(safeUrlTransform("#section")).toBe("#section");
  });

  it("treats a colon after / ? or # as part of the path, not a scheme", () => {
    expect(safeUrlTransform("/asset/javascript:1")).toBe("/asset/javascript:1");
    expect(safeUrlTransform("/a?next=javascript:1")).toBe("/a?next=javascript:1");
    expect(safeUrlTransform("/a#javascript:1")).toBe("/a#javascript:1");
  });
});

/**
 * A persisted project description stores token-less `/api/...` image URLs
 * (`stableFileUrl`) and a browser `<img>` sends no bearer header, so the render
 * side has to attach the viewer's own token or every description image 401s.
 */
describe("project file images resolve the viewer's token at render time", () => {
  beforeEach(() => {
    installMemoryStorage();
    window.localStorage.clear();
  });

  afterEach(() => {
    clearToken();
    cleanup();
  });

  it("appends the stored token to a /api file src", () => {
    storeToken("viewer-token");

    const container = renderMarkdown("![Logo](/api/file/abc123/logo.png)");
    const src = container.querySelector("img")?.getAttribute("src") ?? "";
    const parsed = new URL(src, "http://localhost");

    expect(parsed.pathname).toBe("/api/file/abc123/logo.png");
    expect(parsed.searchParams.get("token")).toBe("viewer-token");
  });

  it("leaves a foreign image src token-free and intact", () => {
    storeToken("viewer-token");

    const container = renderMarkdown("![x](https://example.com/x.png)");
    const src = container.querySelector("img")?.getAttribute("src") ?? "";
    const parsed = new URL(src, "http://localhost");

    expect(parsed.origin + parsed.pathname).toBe("https://example.com/x.png");
    expect(parsed.searchParams.has("token")).toBe(false);
  });

  it("leaves a /api file src token-free when logged out", () => {
    const container = renderMarkdown("![Logo](/api/file/abc123/logo.png)");

    expect(container.querySelector("img")?.getAttribute("src")).toBe(
      "/api/file/abc123/logo.png",
    );
  });
});
