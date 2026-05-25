"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { fetchHealth, type HealthResponse } from "@/lib/api";

export function HealthStatus() {
  const { data, isLoading, isError, error } = useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Backend status</CardTitle>
        <CardDescription>Live probe of /api/v1/health</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && <p className="text-sm text-muted-foreground">Probing…</p>}
        {isError && (
          <p className="text-sm text-destructive">
            Failed to reach backend: {(error as Error).message}
          </p>
        )}
        {data && (
          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Status</span>
              <Badge variant="secondary">{data.status}</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Version</span>
              <span className="font-mono">{data.version}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Environment</span>
              <span className="font-mono">{data.environment}</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
