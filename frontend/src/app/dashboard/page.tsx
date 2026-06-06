"use client";

import { useQuery } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import Link from "next/link";

import { AuthGate } from "@/components/auth-gate";
import { ChatPanel } from "@/components/chat/chat-panel";
import { DocumentUploader } from "@/components/documents/document-uploader";
import { AppShell } from "@/components/layout/app-shell";
import { listDocuments } from "@/lib/documents-api";
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
  const token = useAuthStore((s) => s.token);

  const { data: docs } = useQuery({
    queryKey: ["documents"],
    queryFn: () => listDocuments(token!),
    enabled: !!token,
  });
  const noDocsYet = docs?.total === 0;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-10">
      <header className="flex flex-col gap-2">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Workspace
        </p>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Welcome back
          {(() => {
            const display =
              user?.firstName?.trim() ||
              (user?.email ? user.email.split("@")[0] : null);
            return display ? (
              <>
                ,{" "}
                <span className="text-gradient-brand">{display}</span>
              </>
            ) : null;
          })()}
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Upload anything readable: PDFs, images, audio, text. Then chat over
          it with citations and a live knowledge graph.
        </p>
      </header>

      {noDocsYet && (
        <div
          className="flex items-start gap-3 rounded-xl border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/5 px-4 py-3 text-sm"
          data-testid="no-documents-nudge"
        >
          <Upload
            className="mt-0.5 size-4 shrink-0 text-[color:var(--brand)]"
            aria-hidden="true"
          />
          <p>
            You haven&rsquo;t uploaded anything yet. Drop a file below or open{" "}
            <Link
              href="/dashboard/documents"
              className="font-medium underline underline-offset-4"
            >
              Your documents
            </Link>{" "}
            to manage uploads.
          </p>
        </div>
      )}

      <DocumentUploader compact />

      <ChatPanel />
    </div>
  );
}
