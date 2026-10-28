import type { ComponentPropsWithoutRef, ReactElement } from "react";
import ReactMarkdown, {
  defaultUrlTransform,
  type Components,
  type ExtraProps,
} from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { renderFileUrl } from "../lib/api";

/**
 * The single renderer for untrusted markdown in the app.
 *
 * Project descriptions land here now, and the markdown editor's live preview
 * (Mf-dhtm) will render through this exact component later. That reuse is the
 * point: `rehype-sanitize` runs in *this* pipeline and nowhere else, so there is
 * exactly one place to audit and one behaviour to trust. Do not fork it.
 *
 * Two rules keep that guarantee:
 *
 * 1. `rehype-raw` must NEVER be added. Without it, markdown-embedded HTML is not
 *    parsed into hast elements at all — react-markdown hands it to the rehype
 *    tree as inert `raw` nodes and `rehype-sanitize` has no rule for `raw`, so
 *    they are dropped. A `<script>` tag in a description is therefore *stripped*,
 *    not executed. Adding `rehype-raw` would turn that text back into live
 *    elements and move the entire security burden onto the schema.
 *
 * 2. `rehype-sanitize` stays LAST in the rehype list, and every component below
 *    returns plain React elements — never `dangerouslySetInnerHTML`, because
 *    `components` render *after* plugins and would bypass the sanitiser.
 */

/**
 * Deliberately byte-for-byte `defaultSchema` (the GitHub-flavoured rules):
 * `script` stripped with children, unknown elements unwrapped, no `on*`
 * attributes, no `style`, `className` only for `code[class^="language-"]` and
 * GFM task lists, `data:` stripped from `img[src]`, `align` allowed so tables
 * keep their alignment.
 *
 * Do not relax it. No extra protocols, no `data:`, no extra attributes. If a
 * feature seems to need a schema change, the comment above is the thing to
 * argue with first.
 */
export const schema = defaultSchema;

/** Schemes that must never reach the DOM, even as a relative-looking URL. */
const BLOCKED_URL_SCHEMES: ReadonlySet<string> = new Set([
  "javascript",
  "vbscript",
  "data",
  "file",
]);

/** Drop leading whitespace and control characters (codes 0x00-0x20). */
function trimLeadingBlanks(url: string): string {
  let index = 0;
  while (index < url.length && url.charCodeAt(index) <= 0x20) index += 1;
  return url.slice(index);
}

/**
 * Return the URL scheme, or `null` when the URL has none. A colon only starts a
 * scheme when it appears before the first `/`, `?` or `#` (`/a:b` is a path, not
 * a scheme). Leading whitespace and control characters are ignored because URL
 * parsers ignore them too, so `"  javascript:x"` still means `javascript:x`.
 */
function schemeOf(url: string): string | null {
  const normalized = trimLeadingBlanks(url).toLowerCase();
  const colon = normalized.indexOf(":");
  if (colon === -1) return null;

  for (const separator of ["/", "?", "#"]) {
    const index = normalized.indexOf(separator);
    if (index !== -1 && index < colon) return null;
  }

  return normalized.slice(0, colon);
}

/**
 * Belt-and-braces on top of `defaultUrlTransform` (which only allows
 * `http|https|irc|ircs|mailto|xmpp` plus relative/protocol-relative URLs).
 * Anything that still looks like a dangerous scheme is blanked instead of
 * rendered, so a future change to react-markdown's defaults cannot silently
 * let `javascript:`/`data:`/`file:` through.
 */
export function safeUrlTransform(url: string): string {
  const scheme = schemeOf(url);
  if (scheme !== null && BLOCKED_URL_SCHEMES.has(scheme)) return "";
  return defaultUrlTransform(url);
}

function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

/** Only absolute `http(s)` links leave the app; everything else stays in place. */
function isAbsoluteHttpUrl(url: string | undefined): boolean {
  return typeof url === "string" && /^https?:\/\/\S/i.test(url.trim());
}

type AnchorProps = ComponentPropsWithoutRef<"a"> & ExtraProps;

function MarkdownLink({
  node: _node,
  href,
  title,
  children,
  className,
  ...rest
}: AnchorProps): ReactElement {
  const external = isAbsoluteHttpUrl(href);
  return (
    <a
      // The remainder is spread on purpose: `rest` comes from sanitised hast, so
      // `rehype-sanitize` has already removed every `on*` handler, `style` and
      // unknown attribute. There is nothing unsafe left to forward.
      {...rest}
      href={href}
      title={title}
      rel="noopener noreferrer"
      target={external ? "_blank" : undefined}
      className={cx(
        "text-accent underline underline-offset-2 break-words hover:opacity-80",
        className,
      )}
    >
      {children}
    </a>
  );
}

type ImageProps = ComponentPropsWithoutRef<"img"> & ExtraProps;

function MarkdownImage({
  node: _node,
  src,
  alt,
  title,
  longDesc,
  className,
  ...rest
}: ImageProps & { longDesc?: string }): ReactElement {
  return (
    <img
      {...rest}
      // The stored src is token-less and stable (`stableFileUrl`); a browser
      // <img> sends no bearer header, so each viewer resolves their own token
      // here. Non-`/api/` srcs pass through unchanged.
      src={renderFileUrl(src)}
      alt={alt ?? ""}
      // `longDesc` is allowed by the schema but is not a React-renderable
      // attribute; surfacing it as the tooltip keeps the text reachable.
      title={title ?? longDesc}
      loading="lazy"
      decoding="async"
      className={cx("max-w-full rounded-lg border border-panel", className)}
    />
  );
}

type TableProps = ComponentPropsWithoutRef<"table"> & ExtraProps;

function MarkdownTable({
  node: _node,
  children,
  className,
  ...rest
}: TableProps): ReactElement {
  return (
    // A wide GFM table must scroll inside its own box instead of stretching the
    // page: narrow viewports are the normal case for a described project.
    <div className="my-4 w-full overflow-x-auto" data-md-table="">
      <table {...rest} className={cx("w-full border-collapse text-sm", className)}>
        {children}
      </table>
    </div>
  );
}

type HeadingProps = ComponentPropsWithoutRef<"h1"> & ExtraProps;
type ParagraphProps = ComponentPropsWithoutRef<"p"> & ExtraProps;
type UnorderedListProps = ComponentPropsWithoutRef<"ul"> & ExtraProps;
type OrderedListProps = ComponentPropsWithoutRef<"ol"> & ExtraProps;
type ListItemProps = ComponentPropsWithoutRef<"li"> & ExtraProps;
type QuoteProps = ComponentPropsWithoutRef<"blockquote"> & ExtraProps;
type RuleProps = ComponentPropsWithoutRef<"hr"> & ExtraProps;
type PreProps = ComponentPropsWithoutRef<"pre"> & ExtraProps;
type CodeProps = ComponentPropsWithoutRef<"code"> & ExtraProps;
type CellProps = ComponentPropsWithoutRef<"th"> & ExtraProps;

function MarkdownH1({ node: _node, className, children, ...rest }: HeadingProps): ReactElement {
  return (
    <h1
      {...rest}
      className={cx(
        "mt-6 mb-3 text-2xl font-semibold tracking-tight text-foreground first:mt-0",
        className,
      )}
    >
      {children}
    </h1>
  );
}

function MarkdownH2({ node: _node, className, children, ...rest }: HeadingProps): ReactElement {
  return (
    <h2
      {...rest}
      className={cx(
        "mt-6 mb-2.5 text-xl font-semibold tracking-tight text-foreground first:mt-0",
        className,
      )}
    >
      {children}
    </h2>
  );
}

function MarkdownH3({ node: _node, className, children, ...rest }: HeadingProps): ReactElement {
  return (
    <h3
      {...rest}
      className={cx("mt-5 mb-2 text-lg font-semibold text-foreground first:mt-0", className)}
    >
      {children}
    </h3>
  );
}

function MarkdownH4({ node: _node, className, children, ...rest }: HeadingProps): ReactElement {
  return (
    <h4
      {...rest}
      className={cx("mt-4 mb-1.5 text-base font-semibold text-foreground first:mt-0", className)}
    >
      {children}
    </h4>
  );
}

function MarkdownH5({ node: _node, className, children, ...rest }: HeadingProps): ReactElement {
  return (
    <h5
      {...rest}
      className={cx("mt-4 mb-1 text-sm font-semibold text-foreground first:mt-0", className)}
    >
      {children}
    </h5>
  );
}

function MarkdownH6({ node: _node, className, children, ...rest }: HeadingProps): ReactElement {
  return (
    <h6
      {...rest}
      className={cx(
        "mt-4 mb-1 text-xs font-semibold uppercase tracking-wider text-muted first:mt-0",
        className,
      )}
    >
      {children}
    </h6>
  );
}

function MarkdownParagraph({
  node: _node,
  className,
  children,
  ...rest
}: ParagraphProps): ReactElement {
  return (
    <p
      {...rest}
      className={cx(
        "my-3 text-sm leading-relaxed text-foreground first:mt-0 last:mb-0",
        className,
      )}
    >
      {children}
    </p>
  );
}

function MarkdownUnorderedList({
  node: _node,
  className,
  children,
  ...rest
}: UnorderedListProps): ReactElement {
  return (
    <ul
      {...rest}
      className={cx(
        "my-3 ml-5 list-disc space-y-1 pl-1 text-sm leading-relaxed text-foreground",
        className,
      )}
    >
      {children}
    </ul>
  );
}

function MarkdownOrderedList({
  node: _node,
  className,
  children,
  ...rest
}: OrderedListProps): ReactElement {
  return (
    <ol
      {...rest}
      className={cx(
        "my-3 ml-5 list-decimal space-y-1 pl-1 text-sm leading-relaxed text-foreground",
        className,
      )}
    >
      {children}
    </ol>
  );
}

function MarkdownListItem({
  node: _node,
  className,
  children,
  ...rest
}: ListItemProps): ReactElement {
  return (
    <li {...rest} className={cx("pl-1 [&>p]:my-1", className)}>
      {children}
    </li>
  );
}

function MarkdownBlockquote({
  node: _node,
  className,
  children,
  ...rest
}: QuoteProps): ReactElement {
  return (
    <blockquote
      {...rest}
      className={cx("my-4 border-l-2 border-accent-soft pl-4 text-sm italic text-muted", className)}
    >
      {children}
    </blockquote>
  );
}

function MarkdownRule({ node: _node, className, ...rest }: RuleProps): ReactElement {
  return <hr {...rest} className={cx("my-6 border-t border-panel", className)} />;
}

function MarkdownPre({ node: _node, className, children, ...rest }: PreProps): ReactElement {
  return (
    // The nested `code` keeps our inline-code chrome; strip it back inside `pre`.
    <pre
      {...rest}
      className={cx(
        "my-4 overflow-x-auto rounded-lg border border-panel bg-panel-soft p-3 text-xs",
        "font-mono leading-relaxed text-foreground",
        "[&_code]:bg-transparent [&_code]:p-0 [&_code]:text-inherit",
        className,
      )}
    >
      {children}
    </pre>
  );
}

function MarkdownCode({ node: _node, className, children, ...rest }: CodeProps): ReactElement {
  return (
    // `className` is the sanitised one (`language-js` for fenced blocks); it is
    // merged, never replaced, so highlighting hooks survive.
    <code
      {...rest}
      className={cx(
        "rounded bg-panel-soft px-1 py-0.5 font-mono text-[0.85em] text-foreground",
        className,
      )}
    >
      {children}
    </code>
  );
}

function MarkdownHeaderCell({ node: _node, className, children, ...rest }: CellProps): ReactElement {
  return (
    <th
      {...rest}
      className={cx(
        "border border-panel bg-panel-soft px-3 py-2 text-left align-top font-semibold text-foreground",
        className,
      )}
    >
      {children}
    </th>
  );
}

function MarkdownCell({ node: _node, className, children, ...rest }: CellProps): ReactElement {
  return (
    <td {...rest} className={cx("border border-panel px-3 py-2 align-top", className)}>
      {children}
    </td>
  );
}

const components: Components = {
  a: MarkdownLink,
  img: MarkdownImage,
  table: MarkdownTable,
  th: MarkdownHeaderCell,
  td: MarkdownCell,
  h1: MarkdownH1,
  h2: MarkdownH2,
  h3: MarkdownH3,
  h4: MarkdownH4,
  h5: MarkdownH5,
  h6: MarkdownH6,
  p: MarkdownParagraph,
  ul: MarkdownUnorderedList,
  ol: MarkdownOrderedList,
  li: MarkdownListItem,
  blockquote: MarkdownBlockquote,
  hr: MarkdownRule,
  pre: MarkdownPre,
  code: MarkdownCode,
};

export default function Markdown({ children }: { children: string }): ReactElement {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[[rehypeSanitize, schema]]}
      urlTransform={safeUrlTransform}
      components={components}
    >
      {children}
    </ReactMarkdown>
  );
}
