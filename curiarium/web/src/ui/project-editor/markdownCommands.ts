/**
 * Pure text transforms behind the markdown toolbar (Mf-dhtm).
 *
 * Nothing in here touches the DOM: every command maps one `TextState` to the
 * next, so the editor only has to write `value` back and restore the returned
 * selection. That also makes all of the tricky caret maths unit-testable
 * without a textarea.
 */

export type TextState = {
  value: string;
  selectionStart: number;
  selectionEnd: number;
};

export type TextCommand = (state: TextState) => TextState;

export type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6;

type LineSpan = { start: number; end: number };

type BlockInsertion = {
  value: string;
  /** Offset in `value` where the inserted block itself begins. */
  blockStart: number;
};

const HEADING_PREFIX = /^#{1,6}\s+/;
/** Any existing list marker, bullet or ordered ("- ", "* ", "12. "). */
const LIST_MARKER = /^([-*+]|\d+\.)\s+/;
const BULLET_MARKER = /^[-*+]\s+/;
const ORDERED_MARKER = /^\d+\.\s+/;

const TABLE_BLOCK = "| Column | Column |\n| --- | --- |\n| Cell | Cell |";
const LINK_PLACEHOLDER = "link text";
const URL_PLACEHOLDER = "url";

/** The line containing `position` (a caret at `value.length` belongs to the last one). */
function lineSpanAt(value: string, position: number): LineSpan {
  const start = value.lastIndexOf("\n", position - 1) + 1;
  const nextBreak = value.indexOf("\n", position);
  return { start, end: nextBreak === -1 ? value.length : nextBreak };
}

/**
 * The line range a selection touches. A selection that ends exactly on a line
 * break does not drag the following line in, so "select line 1 + its newline"
 * only transforms line 1.
 */
function selectionLineSpan(state: TextState): LineSpan {
  const first = lineSpanAt(state.value, state.selectionStart);
  const endsOnBreak =
    state.selectionEnd > state.selectionStart &&
    state.value[state.selectionEnd - 1] === "\n";
  const last = lineSpanAt(state.value, endsOnBreak ? state.selectionEnd - 1 : state.selectionEnd);
  return { start: first.start, end: last.end };
}

/**
 * Rewrites every line the selection touches and restores a selection around the
 * rewritten block. A collapsed caret keeps its distance from the transformed
 * line's start; an expanded selection covers the whole rewritten range.
 */
function transformBlock(
  state: TextState,
  transform: (lines: string[], multiLine: boolean) => string[],
): TextState {
  const span = selectionLineSpan(state);
  const block = state.value.slice(span.start, span.end);
  const lines = block.split("\n");
  const multiLine = lines.length > 1;
  const nextBlock = transform(lines, multiLine).join("\n");
  const value = state.value.slice(0, span.start) + nextBlock + state.value.slice(span.end);

  if (state.selectionStart === state.selectionEnd) {
    // Toggling a prefix *off* can shrink the block by more than the caret's
    // distance from the line start ("# Title" with the caret at 0), so the
    // shift is floored at the line start instead of going negative.
    const caret = Math.max(
      span.start,
      state.selectionStart + (nextBlock.length - block.length),
    );
    return { value, selectionStart: caret, selectionEnd: caret };
  }
  return {
    value,
    selectionStart: span.start,
    selectionEnd: span.start + nextBlock.length,
  };
}

function collapsed(value: string, caret: number): TextState {
  return { value, selectionStart: caret, selectionEnd: caret };
}

/** Empty lines inside a multi-line selection are left alone. */
function isSkippedLine(line: string, multiLine: boolean): boolean {
  return multiLine && line.trim() === "";
}

/** `**`, `*` and `` ` `` share one behaviour, so they share one factory. */
function wrapInline(marker: string): TextCommand {
  return state => {
    const { value, selectionStart, selectionEnd } = state;
    const before = value.slice(0, selectionStart);
    const selected = value.slice(selectionStart, selectionEnd);
    const after = value.slice(selectionEnd);

    // Already wrapped from the outside: `**|text|**` → `|text|`.
    if (before.endsWith(marker) && after.startsWith(marker)) {
      return {
        value:
          value.slice(0, selectionStart - marker.length) +
          selected +
          value.slice(selectionEnd + marker.length),
        selectionStart: selectionStart - marker.length,
        selectionEnd: selectionEnd - marker.length,
      };
    }

    // The selection itself carries the markers: `|**text**|` → `|text|`.
    if (
      selected.length > marker.length * 2 &&
      selected.startsWith(marker) &&
      selected.endsWith(marker)
    ) {
      const inner = selected.slice(marker.length, selected.length - marker.length);
      return {
        value: before + inner + after,
        selectionStart,
        selectionEnd: selectionStart + inner.length,
      };
    }

    if (selectionStart === selectionEnd) {
      return collapsed(before + marker + marker + after, selectionStart + marker.length);
    }

    return {
      value: before + marker + selected + marker + after,
      selectionStart: selectionStart + marker.length,
      selectionEnd: selectionEnd + marker.length,
    };
  };
}

export const toggleBold: TextCommand = wrapInline("**");
export const toggleItalic: TextCommand = wrapInline("*");
export const toggleInlineCode: TextCommand = wrapInline("`");

export function toggleHeading(level: HeadingLevel): TextCommand {
  const prefix = `${"#".repeat(level)} `;
  return state =>
    transformBlock(state, (lines, multiLine) => {
      const editable = lines.filter(line => !isSkippedLine(line, multiLine));
      const active = editable.length > 0 && editable.every(line => line.startsWith(prefix));
      return lines.map(line => {
        if (isSkippedLine(line, multiLine)) return line;
        if (active) return line.slice(prefix.length);
        return prefix + line.replace(HEADING_PREFIX, "");
      });
    });
}

function hasListMarker(line: string, kind: "bullet" | "ordered"): boolean {
  return kind === "bullet" ? BULLET_MARKER.test(line) : ORDERED_MARKER.test(line);
}

function toggleList(kind: "bullet" | "ordered"): TextCommand {
  return state =>
    transformBlock(state, (lines, multiLine) => {
      const editable = lines.filter(line => !isSkippedLine(line, multiLine));
      const active =
        editable.length > 0 && editable.every(line => hasListMarker(line, kind));
      let counter = 0;
      return lines.map(line => {
        if (isSkippedLine(line, multiLine)) return line;
        counter += 1;
        if (active) return line.replace(LIST_MARKER, "");
        const body = line.replace(LIST_MARKER, "");
        return kind === "bullet" ? `- ${body}` : `${counter}. ${body}`;
      });
    });
}

export const toggleBulletList: TextCommand = toggleList("bullet");
export const toggleOrderedList: TextCommand = toggleList("ordered");

/** `[text](url)` with the `url` placeholder selected, ready to be typed over. */
export function insertLink(state: TextState): TextState {
  const { value, selectionStart, selectionEnd } = state;
  const selected = value.slice(selectionStart, selectionEnd);
  const text = selected === "" ? LINK_PLACEHOLDER : selected;
  const urlStart = selectionStart + 1 + text.length + 2; // "[", text, "](", then "url"
  return {
    value: `${value.slice(0, selectionStart)}[${text}](${URL_PLACEHOLDER})${value.slice(selectionEnd)}`,
    selectionStart: urlStart,
    selectionEnd: urlStart + URL_PLACEHOLDER.length,
  };
}

export type InsertImageOptions = { url: string; alt: string };

/** `![alt](url)`; selecting text first makes that text the alt. */
export function insertImage(options: InsertImageOptions): TextCommand {
  return state => {
    const { value, selectionStart, selectionEnd } = state;
    const selected = value.slice(selectionStart, selectionEnd);
    const alt = (selected === "" ? options.alt : selected)
      .replace(/\r?\n/g, " ")
      .replace(/\]/g, "\\]");
    const image = `![${alt}](${options.url})`;
    const caret = selectionStart + image.length;
    return collapsed(value.slice(0, selectionStart) + image + value.slice(selectionEnd), caret);
  };
}

/**
 * Places `block` on lines of its own: a newline before it when the caret sits
 * mid-text, and a trailing newline so following content starts below it. At the
 * very start of the document there is no leading blank line.
 */
function insertBlock(state: TextState, block: string): BlockInsertion {
  const before = state.value.slice(0, state.selectionStart);
  const after = state.value.slice(state.selectionEnd);
  const prefix = before.length > 0 && !before.endsWith("\n") ? "\n" : "";
  return {
    value: `${before}${prefix}${block}\n${after}`,
    blockStart: before.length + prefix.length,
  };
}

/**
 * A fence has to start at a line start to parse, so this is always a block
 * insert. A non-empty selection becomes the fence body and stays selected; an
 * empty one leaves the caret on an empty body line.
 */
export function toggleFencedCode(state: TextState): TextState {
  const selected = state.value.slice(state.selectionStart, state.selectionEnd);
  const insertion = insertBlock(
    state,
    selected.length > 0 ? `\`\`\`\n${selected}\n\`\`\`` : "```\n\n```",
  );
  const bodyStart = insertion.blockStart + 4; // past the opening "```\n"
  if (selected.length > 0) {
    return {
      value: insertion.value,
      selectionStart: bodyStart,
      selectionEnd: bodyStart + selected.length,
    };
  }
  return collapsed(insertion.value, bodyStart);
}

const TABLE_FIRST_COLUMN = "Column";

export function insertTable(): TextCommand {
  return state => {
    const insertion = insertBlock(state, TABLE_BLOCK);
    const start = insertion.value.indexOf(
      TABLE_FIRST_COLUMN,
      insertion.blockStart,
    );
    return {
      value: insertion.value,
      selectionStart: start,
      selectionEnd: start + TABLE_FIRST_COLUMN.length,
    };
  };
}

/** Replaces the selection with `text` (paste) and leaves the caret after it. */
export function insertText(text: string): TextCommand {
  return state => {
    const { value, selectionStart, selectionEnd } = state;
    return collapsed(
      value.slice(0, selectionStart) + text + value.slice(selectionEnd),
      selectionStart + text.length,
    );
  };
}
