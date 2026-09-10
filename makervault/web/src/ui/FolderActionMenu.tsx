import React, { useRef, useState } from "react";
import { MoreHorizontal } from "lucide-react";

type Props = {
  name: string;
  children: (close: () => void) => React.ReactNode;
};

/** Keep native disclosure behavior, but build action contents only while open. */
export default function FolderActionMenu({ name, children }: Props) {
  const details = useRef<HTMLDetailsElement>(null);
  const summary = useRef<HTMLElement>(null);
  const [open, setOpen] = useState(false);

  const close = () => {
    if (details.current) details.current.open = false;
    setOpen(false);
    summary.current?.focus();
  };

  return (
    <details ref={details} onToggle={event => setOpen(event.currentTarget.open)}
      onKeyDown={event => {
        if (event.key === "Escape" && event.currentTarget.open) {
          event.preventDefault();
          event.stopPropagation();
          close();
        }
      }}>
      <summary ref={summary} className="sidebar-action-trigger" aria-label={`Actions for ${name}`}>
        <MoreHorizontal className="h-4 w-4" />
      </summary>
      {open && <div className="sidebar-folder-menu">{children(close)}</div>}
    </details>
  );
}
