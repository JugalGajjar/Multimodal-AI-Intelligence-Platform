"use client";

import { AuthGate } from "@/components/auth-gate";
import { FullGraphView } from "@/components/graph/full-graph-view";
import { AppShell } from "@/components/layout/app-shell";

export default function DashboardGraphPage() {
  return (
    <AuthGate>
      <AppShell>
        <div className="mx-auto flex h-full min-h-0 w-full max-w-6xl flex-col">
          <FullGraphView />
        </div>
      </AppShell>
    </AuthGate>
  );
}
