"use client";

import { AuthGate } from "@/components/auth-gate";
import { FullGraphView } from "@/components/graph/full-graph-view";
import { AppShell } from "@/components/layout/app-shell";

export default function DashboardGraphPage() {
  return (
    <AuthGate>
      <AppShell>
        <div className="mx-auto w-full max-w-6xl">
          <FullGraphView />
        </div>
      </AppShell>
    </AuthGate>
  );
}
