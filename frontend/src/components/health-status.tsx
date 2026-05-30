"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleCheck, CircleX, Loader2 } from "lucide-react";

import { fetchHealth, type HealthResponse } from "@/lib/api";

export function HealthStatus() {
  const { data, isLoading, isError } = useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });

  if (isLoading) {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-card/60 px-3 py-1 text-xs text-muted-foreground backdrop-blur-sm">
        <Loader2 className="size-3 animate-spin" aria-hidden="true" />
        Probing backend…
      </span>
    );
  }

  if (isError) {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-destructive/30 bg-destructive/10 px-3 py-1 text-xs text-destructive">
        <CircleX className="size-3" aria-hidden="true" />
        Backend unreachable
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-700 dark:text-emerald-300">
      <CircleCheck className="size-3" aria-hidden="true" />
      Backend {data?.status} · v{data?.version} · {data?.environment}
    </span>
  );
}
