"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  deleteDocument,
  formatBytes,
  listDocuments,
  type DocumentListResponse,
} from "@/lib/documents-api";
import { useAuthStore } from "@/store/auth";

export function DocumentsList() {
  const token = useAuthStore((s) => s.token);
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery<DocumentListResponse>({
    queryKey: ["documents"],
    queryFn: () => listDocuments(token!),
    enabled: !!token,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteDocument(token!, id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });

  return (
    <Card className="w-full max-w-2xl">
      <CardHeader>
        <CardTitle>Your documents</CardTitle>
        <CardDescription>
          {data
            ? `${data.total} document${data.total === 1 ? "" : "s"}`
            : "Loading…"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}
        {isError && (
          <p className="text-sm text-destructive">
            Failed to load documents.
          </p>
        )}
        {data && data.items.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No documents yet. Upload one to get started.
          </p>
        )}
        {data && data.items.length > 0 && (
          <ul className="divide-y divide-border">
            {data.items.map((doc) => (
              <li
                key={doc.id}
                className="flex items-center justify-between gap-4 py-3 text-sm"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{doc.filename}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatBytes(doc.size_bytes)} · {doc.content_type}
                  </p>
                </div>
                <Badge variant="secondary">{doc.status}</Badge>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={deleteMutation.isPending}
                  onClick={() => deleteMutation.mutate(doc.id)}
                >
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
