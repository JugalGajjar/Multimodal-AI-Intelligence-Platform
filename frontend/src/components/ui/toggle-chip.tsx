"use client";

import { cn } from "@/lib/utils";

type ToggleChipProps = {
  pressed: boolean;
  onPressedChange: (pressed: boolean) => void;
  disabled?: boolean;
  title?: string;
  children: React.ReactNode;
  "data-testid"?: string;
};

export function ToggleChip({
  pressed,
  onPressedChange,
  disabled = false,
  title,
  children,
  ...rest
}: ToggleChipProps) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      disabled={disabled}
      title={title}
      onClick={() => onPressedChange(!pressed)}
      className={cn(
        "inline-flex h-7 select-none items-center gap-1 rounded-full border px-2.5 text-[11px] font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--brand)]/40",
        "disabled:pointer-events-none disabled:opacity-50",
        pressed
          ? "border-transparent bg-gradient-brand text-brand-foreground"
          : "border-input bg-background/60 text-muted-foreground hover:text-foreground",
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
