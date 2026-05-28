"use client";

import { useRouter } from "next/navigation";

import { AuthGate } from "@/components/auth-gate";
import { ChatPanel } from "@/components/chat/chat-panel";
import { DocumentUploader } from "@/components/documents/document-uploader";
import { DocumentsList } from "@/components/documents/documents-list";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/store/auth";

export default function DashboardPage() {
  return (
    <AuthGate>
      <DashboardInner />
    </AuthGate>
  );
}

function DashboardInner() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const clearSession = useAuthStore((s) => s.clearSession);

  function onLogout() {
    clearSession();
    router.replace("/login");
  }

  return (
    <main className="flex flex-1 flex-col items-center gap-6 px-6 py-12">
      <div className="flex w-full max-w-2xl items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Signed in as <span className="font-mono">{user?.email}</span>
          </p>
        </div>
        <Button onClick={onLogout} variant="outline" size="sm">
          Sign out
        </Button>
      </div>
      <DocumentUploader />
      <DocumentsList />
      <ChatPanel />
    </main>
  );
}
