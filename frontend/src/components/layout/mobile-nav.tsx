"use client";

import { X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { BrandMark } from "@/components/layout/brand-mark";
import { ABOUT_ITEM, NAV_ITEMS } from "@/components/layout/nav-items";

export function MobileNav({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname() ?? "";

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-30 lg:hidden" data-testid="mobile-nav">
      <div
        className="absolute inset-0 bg-foreground/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className="relative ml-0 flex h-full w-72 max-w-[80%] flex-col border-r border-sidebar-border bg-sidebar shadow-xl">
        <div className="flex h-16 items-center justify-between px-5">
          <BrandMark size="md" />
          <button
            type="button"
            aria-label="Close navigation"
            onClick={onClose}
            className="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          >
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>
        <nav className="flex-1 space-y-1 px-3" aria-label="Mobile">
          {[...NAV_ITEMS, ABOUT_ITEM].map(({ href, label, Icon, match }) => {
            const active = match ? match(pathname) : pathname === href;
            return (
              <Link
                key={href}
                href={href}
                onClick={onClose}
                aria-current={active ? "page" : undefined}
                data-testid={`mobile-nav-${label.toLowerCase().replace(/\s+/g, "-")}`}
                className={
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors " +
                  (active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground")
                }
              >
                <Icon className="size-4" aria-hidden="true" />
                {label}
              </Link>
            );
          })}
        </nav>
      </aside>
    </div>
  );
}
