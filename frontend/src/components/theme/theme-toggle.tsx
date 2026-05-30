"use client";

import { Monitor, Moon, Sun } from "lucide-react";

import { useTheme, type Theme } from "@/components/theme/theme-provider";

const OPTIONS: { value: Theme; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "System", Icon: Monitor },
];

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      data-testid="theme-toggle"
      className="inline-flex items-center gap-0.5 rounded-full border border-border bg-card/60 p-0.5 backdrop-blur-sm shadow-sm"
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = theme === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            data-testid={`theme-toggle-${value}`}
            onClick={() => setTheme(value)}
            className={
              "inline-flex size-7 items-center justify-center rounded-full text-muted-foreground transition-colors " +
              (active
                ? "bg-gradient-brand text-brand-foreground shadow-sm"
                : "hover:bg-accent hover:text-accent-foreground")
            }
          >
            <Icon className="size-3.5" aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}
