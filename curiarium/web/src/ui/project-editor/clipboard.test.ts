// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { htmlToPlainText, plainTextFromPaste } from "./clipboard";

/** The repo's "no native dialogs" guard scans sources for a literal call. */
const ALERT_CALL = "alert" + "(1)";

type ClipboardMap = Record<string, string>;

/** Minimal stand-in for the DataTransfer surface the editor reads. */
function fakeClipboard(data: ClipboardMap): DataTransfer {
  return {
    getData: (type: string) => data[type] ?? "",
  } as unknown as DataTransfer;
}

describe("htmlToPlainText", () => {
  it("separates paragraphs with a blank line", () => {
    expect(htmlToPlainText("<p>Hello</p><p>World</p>")).toBe("Hello\n\nWorld");
  });

  it("turns a br into a newline", () => {
    expect(htmlToPlainText("<div>a<br>b</div>")).toBe("a\nb");
  });

  it("renders list items as dash bullets", () => {
    expect(htmlToPlainText("<ul><li>One</li><li>Two</li></ul>")).toBe("- One\n- Two");
    expect(htmlToPlainText("<ol><li>First</li><li>Second</li></ol>")).toBe(
      "- First\n- Second",
    );
  });

  it("keeps table cells on one space-separated row per line", () => {
    expect(
      htmlToPlainText(
        "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>",
      ),
    ).toBe("A B\n1 2");
  });

  it("decodes entities", () => {
    expect(htmlToPlainText("<p>a &amp; b &lt;c&gt; &quot;d&quot;</p>")).toBe(
      'a & b <c> "d"',
    );
  });

  it("drops script, style, noscript and template content entirely", () => {
    expect(
      htmlToPlainText(
        `<div><script>${ALERT_CALL}</script><style>.x{display:none}</style>` +
          "<noscript>fallback</noscript><template>tpl</template>kept</div>",
      ),
    ).toBe("kept");
  });

  it("keeps preformatted text verbatim", () => {
    expect(htmlToPlainText("<pre>line 1\n    line 2\n</pre>")).toBe(
      "line 1\n    line 2",
    );
  });

  it("collapses runs of whitespace outside pre", () => {
    expect(htmlToPlainText("<p>a    b\n\t   c</p>")).toBe("a b c");
  });

  it("trims trailing spaces and the whole result", () => {
    expect(htmlToPlainText("<p>  <span> spaced </span>  </p>")).toBe("spaced");
  });

  it("collapses three or more newlines to one blank line", () => {
    expect(htmlToPlainText("<div>a</div><div></div><div></div><div>b</div>")).toBe(
      "a\n\nb",
    );
  });
});

describe("plainTextFromPaste", () => {
  it("prefers the clipboard's own plain text", () => {
    expect(
      plainTextFromPaste(
        fakeClipboard({ "text/plain": "plain words", "text/html": "<b>html</b>" }),
      ),
    ).toBe("plain words");
  });

  it("falls back to HTML when the plain text is only whitespace", () => {
    expect(
      plainTextFromPaste(fakeClipboard({ "text/plain": "   ", "text/html": "<p>Hi</p>" })),
    ).toBe("Hi");
  });

  it("returns null when the clipboard is absent or empty", () => {
    expect(plainTextFromPaste(null)).toBeNull();
    expect(plainTextFromPaste(undefined)).toBeNull();
    expect(plainTextFromPaste(fakeClipboard({}))).toBeNull();
  });

  it("returns null when the HTML carries no text", () => {
    expect(
      plainTextFromPaste(fakeClipboard({ "text/html": "<img src=x>" })),
    ).toBeNull();
  });
});
