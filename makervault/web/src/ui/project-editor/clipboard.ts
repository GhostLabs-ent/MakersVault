/**
 * Clipboard plumbing for the markdown editor (Mf-dhtm).
 *
 * Pasted rich content must never reach the textarea as markup, so the editor
 * `preventDefault()`s every paste and inserts this module's plain-text result
 * instead. HTML is parsed in an inert `DOMParser` document: nothing here is
 * ever attached to the live page.
 */

/** Subtrees whose text content must never surface (a `<script>` is not text). */
const DROPPED_TAGS: ReadonlySet<string> = new Set([
  "script",
  "style",
  "noscript",
  "template",
  "head",
]);

/** Block-level tags: the text above and below them belongs on separate lines. */
const BLOCK_TAGS: ReadonlySet<string> = new Set([
  "p",
  "div",
  "li",
  "tr",
  "blockquote",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "pre",
  "table",
  "ul",
  "ol",
  "section",
  "article",
  "header",
  "footer",
  "figure",
]);

const TEXT_NODE = 3;
const ELEMENT_NODE = 1;

function appendText(text: string, out: string[], inPre: boolean): void {
  out.push(inPre ? text : text.replace(/\s+/g, " "));
}

function walkChildren(element: Element, out: string[], inPre: boolean): void {
  for (const child of Array.from(element.childNodes)) walkNode(child, out, inPre);
}

function walkNode(node: Node, out: string[], inPre: boolean): void {
  if (node.nodeType === TEXT_NODE) {
    appendText(node.nodeValue ?? "", out, inPre);
    return;
  }
  if (node.nodeType !== ELEMENT_NODE) return;

  const element = node as Element;
  const tag = element.tagName.toLowerCase();
  if (DROPPED_TAGS.has(tag)) return;

  if (tag === "br") {
    out.push("\n");
    return;
  }
  if (tag === "td" || tag === "th") {
    walkChildren(element, out, inPre);
    out.push(" ");
    return;
  }
  if (tag === "li") out.push("- ");

  const block = BLOCK_TAGS.has(tag);
  walkChildren(element, out, inPre || tag === "pre");

  // List items and table rows separate by a line; real blocks by a blank line,
  // which is what "separate paragraphs" means once newlines are collapsed.
  if (tag === "li" || tag === "tr") out.push("\n");
  else if (block) out.push("\n\n");
}

/** Trim each line, collapse runs of blank lines to one, trim the whole string. */
function normalize(raw: string): string {
  return raw
    .split("\n")
    .map(line => line.replace(/\s+$/, ""))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function htmlToPlainText(html: string): string {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const parts: string[] = [];
  walkChildren(parsed.body, parts, false);
  return normalize(parts.join(""));
}

/**
 * The plain text a paste should insert: the clipboard's own plain text when it
 * has any, otherwise its HTML converted, otherwise `null` (nothing to insert,
 * e.g. a copied file with no text).
 */
export function plainTextFromPaste(
  clipboard: DataTransfer | null | undefined,
): string | null {
  if (!clipboard) return null;

  const plain = clipboard.getData("text/plain");
  if (plain.trim()) return plain;

  const html = clipboard.getData("text/html");
  if (!html.trim()) return null;

  const text = htmlToPlainText(html);
  return text.trim() ? text : null;
}
