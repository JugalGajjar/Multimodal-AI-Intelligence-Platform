"use client";

import { LogOut, Menu } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { BrandMark } from "@/components/layout/brand-mark";
import { MobileNav } from "@/components/layout/mobile-nav";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/store/auth";

export function TopBar() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const clearSession = useAuthStore((s) => s.clearSession);
  const [navOpen, setNavOpen] = useState(false);

  function onLogout() {
    clearSession();
    router.replace("/login");
  }

  return (
    <>
      <header
        data-testid="app-topbar"
        className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-border bg-background/70 px-4 backdrop-blur-xl sm:px-8"
      >
        <button
          type="button"
          aria-label="Open navigation"
          onClick={() => setNavOpen(true)}
          className="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground lg:hidden"
        >
          <Menu className="size-5" aria-hidden="true" />
        </button>

        <div className="lg:hidden">
          <BrandMark size="sm" />
        </div>

        <div className="ml-auto flex items-center gap-3 sm:gap-4">
          {user?.email && (
            <span
              className="hidden text-xs text-muted-foreground sm:inline"
              data-testid="topbar-user-email"
            >
              <span className="font-mono">{user.email}</span>
            </span>
          )}
          <ThemeToggle />
          <Button
            variant="ghost"
            size="sm"
            onClick={onLogout}
            data-testid="topbar-sign-out"
            className="gap-1.5 px-3"
          >
            <LogOut className="size-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">Sign out</span>
          </Button>
        </div>
      </header>

      <MobileNav open={navOpen} onClose={() => setNavOpen(false)} />
    </>
  );
}
