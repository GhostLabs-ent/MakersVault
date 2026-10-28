// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import {
  insertImage,
  insertLink,
  insertTable,
  insertText,
  toggleBold,
  toggleBulletList,
  toggleFencedCode,
  toggleHeading,
  toggleInlineCode,
  toggleItalic,
  toggleOrderedList,
  type TextCommand,
  type TextState,
} from "./markdownCommands";

function state(value: string, selectionStart: number, selectionEnd = selectionStart): TextState {
  return { value, selectionStart, selectionEnd };
}

function run(command: TextCommand, input: TextState): TextState {
  return command(input);
}

/** The text the returned selection covers. */
function selected(result: TextState): string {
  return result.value.slice(result.selectionStart, result.selectionEnd);
}

type InlineCase = {
  name: string;
  command: TextCommand;
  marker: string;
};

const INLINE_CASES: InlineCase[] = [
  { name: "bold", command: toggleBold, marker: "**" },
  { name: "italic", command: toggleItalic, marker: "*" },
  { name: "inline code", command: toggleInlineCode, marker: "`" },
];

describe("inline markers", () => {
  for (const { name, command, marker } of INLINE_CASES) {
    describe(name, () => {
      it("wraps a selection and keeps the same text selected", () => {
        const result = run(command, state("hello world", 6, 11));

        expect(result.value).toBe(`hello ${marker}world${marker}`);
        expect(selected(result)).toBe("world");
        expect(result.selectionStart).toBe(6 + marker.length);
        expect(result.selectionEnd).toBe(11 + marker.length);
      });

      it("inserts an empty pair with the caret between them", () => {
        const result = run(command, state("ab", 1));

        expect(result.value).toBe(`a${marker}${marker}b`);
        expect(result.selectionStart).toBe(1 + marker.length);
        expect(result.selectionEnd).toBe(1 + marker.length);
      });

      it("strips markers that already wrap the selection from outside", () => {
        const result = run(
          command,
          state(`${marker}hello${marker}`, marker.length, marker.length + 5),
        );

        expect(result.value).toBe("hello");
        expect(selected(result)).toBe("hello");
      });

      it("strips markers included in the selection itself", () => {
        const wrapped = `${marker}hello${marker}`;
        const result = run(command, state(wrapped, 0, wrapped.length));

        expect(result.value).toBe("hello");
        expect(selected(result)).toBe("hello");
      });

      it("works at the end of the document", () => {
        const result = run(command, state("end", 3));

        expect(result.value).toBe(`end${marker}${marker}`);
        expect(result.selectionStart).toBe(3 + marker.length);
      });

      it("works in an empty document", () => {
        const result = run(command, state("", 0));

        expect(result.value).toBe(`${marker}${marker}`);
        expect(result.selectionStart).toBe(marker.length);
        expect(result.selectionEnd).toBe(marker.length);
      });
    });
  }
});

describe("toggleHeading", () => {
  it("adds a level-1 prefix with no selection", () => {
    const result = run(toggleHeading(1), state("Title", 0));

    expect(result.value).toBe("# Title");
    expect(result.selectionStart).toBe(2);
    expect(result.selectionEnd).toBe(2);
  });

  it("removes the prefix on a second application", () => {
    const result = run(toggleHeading(1), state("# Title", 4));

    expect(result.value).toBe("Title");
    expect(result.selectionStart).toBe(2);
  });

  it("replaces another level's prefix instead of stacking", () => {
    const result = run(toggleHeading(1), state("## Title", 3));

    expect(result.value).toBe("# Title");
    expect(result.selectionStart).toBe(2);
  });

  it("transforms every non-empty line of a multi-line selection", () => {
    const value = "One\n\nTwo";
    const result = run(toggleHeading(2), state(value, 0, value.length));

    expect(result.value).toBe("## One\n\n## Two");
    expect(selected(result)).toBe("## One\n\n## Two");
  });

  it("skips empty lines but still toggles the whole block off", () => {
    const value = "## One\n\n## Two";
    const result = run(toggleHeading(2), state(value, 0, value.length));

    expect(result.value).toBe("One\n\nTwo");
  });

  it("shifts a collapsed caret by the prefix delta", () => {
    const result = run(toggleHeading(3), state("body text", 5));

    expect(result.value).toBe("### body text");
    expect(result.selectionStart).toBe(5 + 4);
    expect(result.selectionEnd).toBe(5 + 4);
  });

  it("floors a collapsed caret at the line start when the prefix is removed", () => {
    const result = run(toggleHeading(1), state("# Title", 0));

    expect(result.value).toBe("Title");
    expect(result.selectionStart).toBe(0);
    expect(result.selectionEnd).toBe(0);
  });

  it("clamps a caret sitting inside the removed prefix", () => {
    const result = run(toggleHeading(3), state("### Title", 2));

    expect(result.value).toBe("Title");
    expect(result.selectionStart).toBe(0);
  });

  it("prefixes the caret's line at the end of the document", () => {
    const result = run(toggleHeading(2), state("a\nb", 3));

    expect(result.value).toBe("a\n## b");
    expect(result.selectionStart).toBe(6);
  });
});

describe("toggleBulletList", () => {
  it("adds a bullet marker to an empty caret line", () => {
    const result = run(toggleBulletList, state("Item", 0));

    expect(result.value).toBe("- Item");
    expect(result.selectionStart).toBe(2);
  });

  it("removes the marker when every line already has one", () => {
    const result = run(toggleBulletList, state("- Item", 4));

    expect(result.value).toBe("Item");
    expect(result.selectionStart).toBe(2);
  });

  it("switches an ordered list to a bullet list", () => {
    const result = run(toggleBulletList, state("1. Item", 3));

    expect(result.value).toBe("- Item");
  });

  it("marks every non-empty line of a multi-line selection", () => {
    const value = "One\nTwo";
    const result = run(toggleBulletList, state(value, 0, value.length));

    expect(result.value).toBe("- One\n- Two");
    expect(selected(result)).toBe("- One\n- Two");
  });

  it("floors a collapsed caret at the line start when the marker is removed", () => {
    const result = run(toggleBulletList, state("- Item", 0));

    expect(result.value).toBe("Item");
    expect(result.selectionStart).toBe(0);
    expect(result.selectionEnd).toBe(0);
  });
});

describe("toggleOrderedList", () => {
  it("numbers a multi-line selection from one", () => {
    const value = "One\nTwo";
    const result = run(toggleOrderedList, state(value, 0, value.length));

    expect(result.value).toBe("1. One\n2. Two");
  });

  it("switches a bullet list to an ordered one", () => {
    const result = run(toggleOrderedList, state("- Item", 2));

    expect(result.value).toBe("1. Item");
  });

  it("removes numbering when every line is already numbered", () => {
    const value = "1. One\n2. Two";
    const result = run(toggleOrderedList, state(value, 0, value.length));

    expect(result.value).toBe("One\nTwo");
  });

  it("skips empty lines when numbering", () => {
    const value = "One\n\nTwo";
    const result = run(toggleOrderedList, state(value, 0, value.length));

    expect(result.value).toBe("1. One\n\n2. Two");
  });
});

describe("insertLink", () => {
  it("wraps the selection and selects the url placeholder", () => {
    const result = run(insertLink, state("see docs", 4, 8));

    expect(result.value).toBe("see [docs](url)");
    expect(selected(result)).toBe("url");
  });

  it("uses the literal placeholder when nothing is selected", () => {
    const result = run(insertLink, state("", 0));

    expect(result.value).toBe("[link text](url)");
    expect(selected(result)).toBe("url");
    expect(result.selectionStart).toBe("[link text](".length);
  });
});

describe("insertImage", () => {
  const image = insertImage({ url: "/api/file/a2/logo.png", alt: "Logo" });

  it("takes the alt from the selection and leaves the caret after it", () => {
    const result = run(image, state("a Logo here", 2, 6));

    expect(result.value).toBe("a ![Logo](/api/file/a2/logo.png) here");
    expect(result.selectionStart).toBe(result.value.length - " here".length);
    expect(result.selectionEnd).toBe(result.selectionStart);
  });

  it("falls back to the supplied alt when nothing is selected", () => {
    const result = run(image, state("", 0));

    expect(result.value).toBe("![Logo](/api/file/a2/logo.png)");
    expect(result.selectionStart).toBe(result.value.length);
  });

  it("escapes a closing bracket and collapses newlines in the alt", () => {
    const result = run(image, state("a]b\nc", 0, 5));

    expect(result.value).toBe("![a\\]b c](/api/file/a2/logo.png)");
  });
});

describe("toggleFencedCode", () => {
  it("pads the fence onto fresh lines when the caret is mid-line", () => {
    const result = run(toggleFencedCode, state("texthere", 4));

    expect(result.value).toBe("text\n```\n\n```\nhere");
    expect(result.selectionStart).toBe("text\n```\n".length);
    expect(result.selectionEnd).toBe(result.selectionStart);
  });

  it("turns the selection into the fenced body and keeps it selected", () => {
    const result = run(toggleFencedCode, state("x = 1", 0, 5));

    expect(result.value).toBe("```\nx = 1\n```\n");
    expect(selected(result)).toBe("x = 1");
  });

  it("inserts an empty body line in an empty document", () => {
    const result = run(toggleFencedCode, state("", 0));

    expect(result.value).toBe("```\n\n```\n");
    expect(result.selectionStart).toBe("```\n".length);
    expect(result.selectionEnd).toBe(result.selectionStart);
  });
});

describe("insertTable", () => {
  it("inserts the table block and selects the first Column placeholder", () => {
    const result = run(insertTable(), state("", 0));

    expect(result.value).toBe(
      "| Column | Column |\n| --- | --- |\n| Cell | Cell |\n",
    );
    expect(selected(result)).toBe("Column");
    expect(result.selectionStart).toBe(2);
  });

  it("starts on a fresh line when the caret is mid-text", () => {
    const result = run(insertTable(), state("intro", 5));

    expect(result.value).toBe(
      "intro\n| Column | Column |\n| --- | --- |\n| Cell | Cell |\n",
    );
    expect(selected(result)).toBe("Column");
  });
});

describe("insertText", () => {
  it("replaces the selection and leaves the caret after the paste", () => {
    const result = run(insertText("XY"), state("abcdef", 2, 4));

    expect(result.value).toBe("abXYef");
    expect(result.selectionStart).toBe(4);
    expect(result.selectionEnd).toBe(4);
  });

  it("inserts at the caret when nothing is selected", () => {
    const result = run(insertText("XY"), state("ab", 1));

    expect(result.value).toBe("aXYb");
    expect(result.selectionStart).toBe(3);
  });
});
