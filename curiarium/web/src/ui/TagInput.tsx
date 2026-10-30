import React from "react";
import TagBadge from "./TagBadge";

type TagInputProps = {
  value: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
};

export default function TagInput({ value, onChange, placeholder }: TagInputProps) {
  const [draft, setDraft] = React.useState("");
  const inputRef = React.useRef<HTMLInputElement | null>(null);

  const normalized = (t: string) => t.trim().replace(/\s+/g, " ");

  const addTag = (raw: string) => {
    const tag = normalized(raw);
    if (!tag) return;
    if (value.some(v => v.toLowerCase() === tag.toLowerCase())) {
      setDraft("");
      return;
    }
    onChange([...value, tag]);
    setDraft("");
  };

  const removeTag = (idx: number) => {
    const next = [...value.slice(0, idx), ...value.slice(idx + 1)];
    onChange(next);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(draft);
    } else if (e.key === "Backspace" && draft === "" && value.length) {
      e.preventDefault();
      removeTag(value.length - 1);
    }
  };

  const handleBlur = () => {
    if (draft.trim()) addTag(draft);
  };

  return (
    <div
      className="flex flex-wrap gap-2 px-2 py-2 rounded-md border border-panel-strong bg-panel-soft text-sm"
      onClick={() => inputRef.current?.focus()}
    >
      {value.map((tag, idx) => (
        <TagBadge key={`${tag}-${idx}`} tag={tag} onRemove={() => removeTag(idx)} />
      ))}
      <input
        ref={inputRef}
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        placeholder={value.length === 0 ? placeholder : ""}
        className="flex-1 min-w-[120px] bg-transparent outline-none text-sm text-foreground placeholder:text-[color:var(--mv-text-subtle)]"
      />
    </div>
  );
}
