"use client";

import { AuthGate } from "@/components/auth-gate";
import { DocumentUploader } from "@/components/documents/document-uploader";
import { DocumentsList } from "@/components/documents/documents-list";
import { AppShell } from "@/components/layout/app-shell";

export default function DocumentsPage() {
  return (
    <AuthGate>
      <AppShell>
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
          <header className="flex flex-col gap-2">
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

          <div className="flex flex-col gap-6">
            <DocumentUploader compact />
            <DocumentsList />
          </div>
        </div>
      </AppShell>
    </AuthGate>
  );
}
