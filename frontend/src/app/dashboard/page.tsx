"use client";

import { AuthGate } from "@/components/auth-gate";
import { ChatPanel } from "@/components/chat/chat-panel";
import { DocumentUploader } from "@/components/documents/document-uploader";
import { DocumentsList } from "@/components/documents/documents-list";
import { AppShell } from "@/components/layout/app-shell";
import { useAuthStore } from "@/store/auth";

export default function DashboardPage() {
  return (
    <AuthGate>
      <AppShell>
        <DashboardInner />
      </AppShell>
    </AuthGate>
  );
}

function DashboardInner() {
  const user = useAuthStore((s) => s.user);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
      <header className="flex flex-col gap-1">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Workspace
        </p>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Welcome back
          {user?.email ? (
            <>
              ,{" "}
              <span className="text-gradient-brand">
                {user.email.split("@")[0]}
              </span>
            </>
          ) : null}
        </h1>
        <p className="text-sm text-muted-foreground">
          Upload anything readable — PDFs, images, audio, text — then chat over
          it with citations and a live knowledge graph.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <DocumentUploader />
        <DocumentsList />
      </div>

      <ChatPanel />
    </div>
  );
}
