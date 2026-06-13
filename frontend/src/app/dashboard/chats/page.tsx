"use client";

import { History } from "lucide-react";

import { AuthGate } from "@/components/auth-gate";
import { ChatsList } from "@/components/chats/chats-list";
import { AppShell } from "@/components/layout/app-shell";

export default function ChatsPage() {
  return (
    <AuthGate>
      <AppShell>
        <div className="mx-auto flex h-full min-h-0 w-full max-w-5xl flex-col gap-6">
          <header className="flex flex-col gap-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Workspace
            </p>
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight sm:text-3xl">
              <History
                className="size-6 text-[color:var(--brand)]"
                aria-hidden="true"
              />
              Chat history
            </h1>
            <p className="text-sm text-muted-foreground">
              Every conversation is saved with a title and summary. Search
              across titles, summaries, and full message text; open a chat to
              read its transcript.
            </p>
          </header>
          <div className="flex min-h-0 flex-1 flex-col gap-6">
            <ChatsList />
          </div>
        </div>
      </AppShell>
    </AuthGate>
  );
}
