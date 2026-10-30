import { useRef, type KeyboardEvent } from "react";
import { FolderTree, Layers3 } from "lucide-react";

import type { LibraryMode } from "../lib/mode";

type Props = {
  mode: LibraryMode;
  onChange: (mode: LibraryMode) => void;
};

const OPTIONS: { value: LibraryMode; label: string; Icon: typeof FolderTree }[] = [
  { value: "files", label: "Files", Icon: FolderTree },
  { value: "projects", label: "Projects", Icon: Layers3 },
];

/** Segmented Files/Projects switch. Selection follows focus, like a radio group. */
export default function ModeSwitch({ mode, onChange }: Props) {
  const filesRef = useRef<HTMLButtonElement | null>(null);
  const projectsRef = useRef<HTMLButtonElement | null>(null);

  const refFor = (value: LibraryMode) => (value === "files" ? filesRef : projectsRef);

  const selectAndFocus = (next: LibraryMode) => {
    if (next !== mode) onChange(next);
    refFor(next).current?.focus();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const index = OPTIONS.findIndex(option => option.value === mode);
    const last = OPTIONS.length - 1;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        selectAndFocus(OPTIONS[(index + 1) % OPTIONS.length].value);
        return;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        selectAndFocus(OPTIONS[(index - 1 + OPTIONS.length) % OPTIONS.length].value);
        return;
      case "Home":
        event.preventDefault();
        selectAndFocus(OPTIONS[0].value);
        return;
      case "End":
        event.preventDefault();
        selectAndFocus(OPTIONS[last].value);
        return;
      default:
        return;
    }
  };

  return (
    <div
      className="mode-switch"
      role="radiogroup"
      aria-label="Library mode"
      onKeyDown={handleKeyDown}
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const checked = value === mode;
        return (
          <button
            key={value}
            ref={refFor(value)}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            className="mode-switch-option"
            onClick={() => selectAndFocus(value)}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{label}</span>
          </button>
        );
      })}
    </div>
  );
}
