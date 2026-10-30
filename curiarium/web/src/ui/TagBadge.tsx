import React from "react";
import { colorForTag } from "./tagColors";

type TagBadgeProps = {
  tag: string;
  className?: string;
  onRemove?: () => void;
};

export default function TagBadge({ tag, className = "", onRemove }: TagBadgeProps) {
  const colors = colorForTag(tag);
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${className}`}
      style={{
        backgroundColor: colors.bg,
        color: colors.text,
        borderColor: colors.border,
      }}
    >
      {tag}
      {onRemove && (
        <button
          type="button"
          className="text-[10px] leading-none opacity-70 hover:opacity-100"
          onClick={onRemove}
          aria-label={`Remove ${tag}`}
        >
          ×
        </button>
      )}
    </span>
  );
}
