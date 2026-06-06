"use client";

import { AuthGate } from "@/components/auth-gate";
import { DocumentUploader } from "@/components/documents/document-uploader";
import { DocumentsList } from "@/components/documents/documents-list";
import { AppShell } from "@/components/layout/app-shell";

export default function DocumentsPage() {
  return (
    <AuthGate>
      <AppShell>
        <div className="mx-auto flex h-full min-h-0 w-full max-w-5xl flex-col gap-6">
          <header className="flex shrink-0 flex-col gap-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Workspace
            </p>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              Your documents
            </h1>
            <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Add new files or remove existing ones. Status, size, and chunk
              counts are tracked here.
            </p>
          </header>

          <div className="flex min-h-0 flex-1 flex-col gap-6">
            <div className="shrink-0">
              <DocumentUploader compact />
            </div>
            <div className="flex min-h-0 flex-1 flex-col">
              <DocumentsList />
            </div>
          </div>
        </div>
      </AppShell>
    </AuthGate>
  );
}
