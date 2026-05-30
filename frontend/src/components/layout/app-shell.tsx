"use client";

import type { ReactNode } from "react";

import { Sidebar } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/top-bar";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh w-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main
          className="flex-1 px-4 py-6 sm:px-8 sm:py-10"
          data-testid="app-shell-main"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
