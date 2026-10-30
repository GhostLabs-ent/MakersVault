import React from "react";

type ThemeToggleProps = {
  value: "light" | "dark";
  onToggle: () => void;
};

export default function ThemeToggle({ value, onToggle }: ThemeToggleProps) {
  const isDark = value === "dark";
  return (
    <button
      onClick={onToggle}
      className="flex items-center gap-3 select-none"
      aria-label="Toggle theme"
      type="button"
    >
      <span
        className={`w-14 h-7 rounded-full border-2 flex items-center ${
          isDark
            ? "border-white bg-neutral-900 dark:border-neutral-200"
            : "border-neutral-900 bg-white dark:bg-neutral-200"
        }`}
      >
        <span
          className={`h-6 w-6 rounded-full border-2 transition-transform duration-200 ${
            isDark
              ? "translate-x-6 border-white bg-white"
              : "translate-x-0 border-neutral-900 bg-neutral-900"
          }`}
          style={{ marginLeft: "2px" }}
        />
      </span>
      <span className="text-sm font-medium">Theme: {isDark ? "Dark" : "Light"}</span>
    </button>
  );
}
