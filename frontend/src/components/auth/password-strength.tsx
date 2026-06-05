"use client";

import { Check, X } from "lucide-react";

import { evaluatePassword } from "@/lib/password-validator";
import { cn } from "@/lib/utils";

type Props = {
  password: string;
  email?: string;
  className?: string;
};

export function PasswordStrength({ password, email, className }: Props) {
  if (!password) return null;
  const rules = evaluatePassword(password, email);

  return (
    <ul
      data-testid="password-strength"
      className={cn(
        "grid grid-cols-1 gap-1 text-xs text-muted-foreground sm:grid-cols-2",
        className,
      )}
    >
      {rules.map((r) => (
        <li
          key={r.id}
          className={cn(
            "flex items-center gap-1.5",
            r.ok && "text-foreground/80",
          )}
        >
          {r.ok ? (
            <Check className="size-3.5 text-emerald-500" aria-hidden="true" />
          ) : (
            <X className="size-3.5 text-muted-foreground/60" aria-hidden="true" />
          )}
          <span>{r.label}</span>
        </li>
      ))}
    </ul>
  );
}
