import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
  type ReactElement,
} from "react";

import { stableFileUrl, type Asset } from "../../lib/api";
import Markdown from "../Markdown";
import ImagePickerDialog from "./ImagePickerDialog";
import MarkdownToolbar from "./MarkdownToolbar";
import { plainTextFromPaste } from "./clipboard";
import {
  insertImage,
  insertLink,
  insertText,
  toggleBold,
  toggleItalic,
  type TextCommand,
} from "./markdownCommands";

type Props = {
  value: string;
  onChange: (value: string) => void;
  /** The project's image members; the insert picker lists these. */
  images: Asset[];
  ariaLabel?: string;
  rows?: number;
  autoFocus?: boolean;
  /** Wrapper classes. */
  className?: string;
  /** ProjectLanding passes its `INPUT_BASE` styling here. */
  textareaClassName?: string;
  placeholder?: string;
};

type Selection = { selectionStart: number; selectionEnd: number };

function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

/**
 * The plain-textarea markdown editor for project descriptions (Mf-dhtm).
 *
 * The preview is `Markdown` — the same sanitised renderer the read-only
 * description uses — so what an author sees here is exactly what is stored and
 * rendered later. There is no rich-text layer and no second render pipeline.
 */
export default function MarkdownEditor({
  value,
  onChange,
  images,
  ariaLabel = "Description",
  rows = 10,
  autoFocus = false,
  className,
  textareaClassName,
  placeholder,
}: Props): ReactElement {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  /** Set by a transform, consumed once by the layout effect below. */
  const pendingSelectionRef = useRef<Selection | null>(null);
  /** The textarea selection at the moment the image picker took focus. */
  const stashedSelectionRef = useRef<Selection | null>(null);
  const [imagePickerOpen, setImagePickerOpen] = useState(false);

  const applyCommand = useCallback(
    (command: TextCommand, overrideSelection?: Selection) => {
      const textarea = textareaRef.current;
      // The picker stashes a selection before it takes focus; everything else
      // reads the live textarea selection.
      const selection: Selection = overrideSelection ?? {
        selectionStart: textarea?.selectionStart ?? value.length,
        selectionEnd: textarea?.selectionEnd ?? value.length,
      };
      const next = command({
        value: textarea?.value ?? value,
        ...selection,
      });
      pendingSelectionRef.current = {
        selectionStart: next.selectionStart,
        selectionEnd: next.selectionEnd,
      };
      onChange(next.value);
    },
    [onChange, value],
  );

  // Only a transform leaves a pending selection behind, so ordinary keystrokes
  // never have their caret moved out from under them.
  useLayoutEffect(() => {
    const pending = pendingSelectionRef.current;
    if (!pending) return;
    pendingSelectionRef.current = null;
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.focus();
    textarea.setSelectionRange(pending.selectionStart, pending.selectionEnd);
  }, [value]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    const key = event.key.toLowerCase();
    if (key === "b") {
      event.preventDefault();
      applyCommand(toggleBold);
    } else if (key === "i") {
      event.preventDefault();
      applyCommand(toggleItalic);
    } else if (key === "k") {
      event.preventDefault();
      applyCommand(insertLink);
    }
  };

  // HTML never reaches the textarea (or the browser's own paste handling):
  // every paste is converted to plain text here.
  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    event.preventDefault();
    const text = plainTextFromPaste(event.clipboardData);
    if (text === null) return;
    applyCommand(insertText(text));
  };

  const openImagePicker = () => {
    const textarea = textareaRef.current;
    stashedSelectionRef.current = {
      selectionStart: textarea?.selectionStart ?? value.length,
      selectionEnd: textarea?.selectionEnd ?? value.length,
    };
    setImagePickerOpen(true);
  };

  const closeImagePicker = () => {
    stashedSelectionRef.current = null;
    setImagePickerOpen(false);
    textareaRef.current?.focus();
  };

  const insertPickedImage = (asset: Asset) => {
    const selection = stashedSelectionRef.current ?? {
      selectionStart: value.length,
      selectionEnd: value.length,
    };
    stashedSelectionRef.current = null;
    setImagePickerOpen(false);
    applyCommand(insertImage({ url: stableFileUrl(asset.url), alt: asset.name }), selection);
  };

  const empty = value.trim() === "";

  return (
    <div className={cx("flex min-w-0 flex-col", className)}>
      <MarkdownToolbar onCommand={applyCommand} onPickImage={openImagePicker} />
      <div className="mt-2 grid gap-3 lg:grid-cols-2">
        <textarea
          ref={textareaRef}
          aria-label={ariaLabel}
          rows={rows}
          value={value}
          autoFocus={autoFocus}
          placeholder={placeholder}
          spellCheck={false}
          onChange={event => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          className={cx("min-w-0 resize-y font-mono leading-relaxed", textareaClassName)}
        />
        <div className="min-w-0">
          {empty && <p className="mb-2 text-sm text-muted">Nothing to preview yet.</p>}
          {/* Exactly one child: the shared Markdown renderer. */}
          <div
            data-markdown-preview=""
            role="region"
            aria-label="Markdown preview"
            className="min-h-[6rem] min-w-0 overflow-x-auto rounded-md border border-panel bg-panel-soft p-3"
          >
            <Markdown>{value}</Markdown>
          </div>
        </div>
      </div>

      {imagePickerOpen && (
        <ImagePickerDialog
          images={images}
          onInsert={insertPickedImage}
          onClose={closeImagePicker}
        />
      )}
    </div>
  );
}
