"use client";

import { AuthGate } from "@/components/auth-gate";
import { FullGraphView } from "@/components/graph/full-graph-view";

export default function DashboardGraphPage() {
  return (
    <AuthGate>
      <FullGraphView />
    </AuthGate>
  );
}
