import type { ReactElement } from "react";
import {
  Bold,
  Code,
  Heading1,
  Heading2,
  Heading3,
  ImagePlus,
  Italic,
  Link,
  List,
  ListOrdered,
  SquareCode,
  Table,
  type LucideIcon,
} from "lucide-react";

import {
  insertLink,
  insertTable,
  toggleBold,
  toggleBulletList,
  toggleFencedCode,
  toggleHeading,
  toggleInlineCode,
  toggleItalic,
  toggleOrderedList,
  type TextCommand,
} from "./markdownCommands";

const FOCUS_VISIBLE =
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
const BUTTON_ICON = `inline-flex items-center justify-center rounded-md border border-panel-strong p-1.5 text-muted transition-colors hover:bg-panel-soft hover:text-foreground disabled:opacity-60 ${FOCUS_VISIBLE}`;

type Props = {
  onCommand: (command: TextCommand) => void;
  onPickImage: () => void;
  disabled?: boolean;
};

type CommandButton = { label: string; icon: LucideIcon; command: TextCommand };

/** Toolbar order is the order a description is usually written in. */
const COMMAND_BUTTONS: CommandButton[] = [
  { label: "Heading 1", icon: Heading1, command: toggleHeading(1) },
  { label: "Heading 2", icon: Heading2, command: toggleHeading(2) },
  { label: "Heading 3", icon: Heading3, command: toggleHeading(3) },
  { label: "Bold", icon: Bold, command: toggleBold },
  { label: "Italic", icon: Italic, command: toggleItalic },
  { label: "Bullet list", icon: List, command: toggleBulletList },
  { label: "Numbered list", icon: ListOrdered, command: toggleOrderedList },
  { label: "Link", icon: Link, command: insertLink },
  { label: "Inline code", icon: Code, command: toggleInlineCode },
  { label: "Code block", icon: SquareCode, command: toggleFencedCode },
  { label: "Table", icon: Table, command: insertTable() },
];

export default function MarkdownToolbar({
  onCommand,
  onPickImage,
  disabled = false,
}: Props): ReactElement {
  return (
    // `preventDefault` on mousedown keeps focus (and therefore the selection)
    // in the textarea while a toolbar button is pressed.
    <div
      role="toolbar"
      aria-label="Markdown formatting"
      className="flex flex-wrap gap-1"
      onMouseDown={event => event.preventDefault()}
    >
      {COMMAND_BUTTONS.map(({ label, icon: Icon, command }) => (
        <button
          key={label}
          type="button"
          aria-label={label}
          title={label}
          className={BUTTON_ICON}
          disabled={disabled}
          onClick={() => onCommand(command)}
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
        </button>
      ))}
      <button
        type="button"
        aria-label="Insert image"
        title="Insert image"
        className={BUTTON_ICON}
        disabled={disabled}
        onClick={onPickImage}
      >
        <ImagePlus className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}
