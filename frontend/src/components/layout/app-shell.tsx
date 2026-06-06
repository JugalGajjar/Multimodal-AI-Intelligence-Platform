"use client";

import type { ReactNode } from "react";

import { Sidebar } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/top-bar";
import { useDocumentStatusToasts } from "@/hooks/use-document-status-toasts";

export function AppShell({ children }: { children: ReactNode }) {
  // Background subscription so processing/processed/failed toasts follow
  // the user regardless of which authenticated page they're on.
  useDocumentStatusToasts();

  return (
    <div className="flex h-svh w-full overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main
          className="flex-1 overflow-y-auto px-5 py-8 sm:px-10 sm:py-12"
          data-testid="app-shell-main"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
