"use client";

import type { ReactNode } from "react";

import { Sidebar } from "@/components/layout/sidebar";
import { TopBar } from "@/components/layout/top-bar";
import { useDocumentStatusToasts } from "@/hooks/use-document-status-toasts";

/** How the shell handles vertical overflow.
 *  - `inner`: shell pinned to viewport height; the main region scrolls
 *    internally. Good for pages with fixed-height widgets (canvas graph,
 *    settings forms) where the browser scroll would be awkward.
 *  - `page`: shell grows with content and the browser scrolls the page.
 *    Sidebar becomes position:sticky so it stays visible on desktop.
 *    Preferred for list-heavy pages (chat thread, documents, chats). */
type ScrollMode = "inner" | "page";

export function AppShell({
  children,
  scrollMode = "inner",
}: {
  children: ReactNode;
  scrollMode?: ScrollMode;
}) {
  // Background subscription so processing/processed/failed toasts follow
  // the user regardless of which authenticated page they're on.
  useDocumentStatusToasts();

  const isPageScroll = scrollMode === "page";

  return (
    <div
      className={
        isPageScroll
          ? "flex min-h-svh w-full"
          : "flex h-svh w-full overflow-hidden"
      }
    >
      <Sidebar sticky={isPageScroll} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main
          className={
            isPageScroll
              ? "flex-1 px-5 py-8 sm:px-10 sm:py-12"
              : "flex-1 overflow-y-auto px-5 py-8 sm:px-10 sm:py-12"
          }
          data-testid="app-shell-main"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
