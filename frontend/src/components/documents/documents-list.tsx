"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

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
  getDocumentText,
  listDocumentChunks,
  listDocuments,
  reindexDocumentGraph,
  type DocumentItem,
  type DocumentListResponse,
  type DocumentStatus,
} from "@/lib/documents-api";
import { useAuthStore } from "@/store/auth";

const STATUS_VARIANT: Record<
  DocumentStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  uploaded: "outline",
  processing: "secondary",
  processed: "default",
  failed: "destructive",
};

function hasInFlight(items: DocumentItem[] | undefined): boolean {
  return (
    !!items &&
    items.some((d) => d.status === "uploaded" || d.status === "processing")
  );
}

export function DocumentsList() {
  const token = useAuthStore((s) => s.token);
  const queryClient = useQueryClient();
  const [openId, setOpenId] = useState<string | null>(null);
  const [reindexStatus, setReindexStatus] = useState<{
    id: string;
    kind: "ok" | "err";
    message: string;
  } | null>(null);

  const { data, isLoading, isError } = useQuery<DocumentListResponse>({
    queryKey: ["documents"],
    queryFn: () => listDocuments(token!),
    enabled: !!token,
    refetchInterval: (query) =>
      hasInFlight(query.state.data?.items) ? 1500 : false,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteDocument(token!, id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["documents"] }),
  });

  const reindexMutation = useMutation({
    mutationFn: (id: string) => reindexDocumentGraph(token!, id),
    onSuccess: (_, id) => {
      setReindexStatus({
        id,
        kind: "ok",
        message: "Re-indexing graph… new entities will appear within ~10s.",
      });
    },
    onError: (err: unknown, id) => {
      const msg = err instanceof Error ? err.message : "Re-index failed.";
      setReindexStatus({ id, kind: "err", message: msg });
    },
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
          <p className="text-sm text-destructive">Failed to load documents.</p>
        )}
        {data && data.items.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No documents yet. Upload one to get started.
          </p>
        )}
        {data && data.items.length > 0 && (
          <ul className="divide-y divide-border">
            {data.items.map((doc) => (
              <li key={doc.id} className="py-3 text-sm">
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{doc.filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatBytes(doc.size_bytes)} · {doc.content_type}
                      {doc.status === "processed" && (
                        <>
                          {" · "}
                          <ChunkCount id={doc.id} />
                        </>
                      )}
                    </p>
                  </div>
                  <Badge variant={STATUS_VARIANT[doc.status]}>
                    {doc.status}
                  </Badge>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={doc.status !== "processed"}
                    onClick={() =>
                      setOpenId((id) => (id === doc.id ? null : doc.id))
                    }
                  >
                    {openId === doc.id ? "Hide text" : "View text"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={
                      doc.status !== "processed" ||
                      (reindexMutation.isPending &&
                        reindexMutation.variables === doc.id)
                    }
                    onClick={() => {
                      setReindexStatus(null);
                      reindexMutation.mutate(doc.id);
                    }}
                    title="Re-run entity extraction over this document's chunks"
                    data-testid="reindex-graph-button"
                  >
                    {reindexMutation.isPending &&
                    reindexMutation.variables === doc.id
                      ? "Re-indexing…"
                      : "Re-index graph"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={deleteMutation.isPending}
                    onClick={() => deleteMutation.mutate(doc.id)}
                  >
                    Delete
                  </Button>
                </div>
                {reindexStatus?.id === doc.id && (
                  <p
                    className={`mt-2 text-xs ${reindexStatus.kind === "ok" ? "text-emerald-600" : "text-destructive"}`}
                    data-testid="reindex-status"
                  >
                    {reindexStatus.message}
                  </p>
                )}
                {openId === doc.id && <DocumentText id={doc.id} />}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function ChunkCount({ id }: { id: string }) {
  const token = useAuthStore((s) => s.token);
  const { data } = useQuery({
    queryKey: ["documents", id, "chunks", "count"],
    queryFn: () => listDocumentChunks(token!, id),
    enabled: !!token,
  });
  if (!data) return <span aria-label="loading chunk count">…</span>;
  return (
    <span aria-label="chunk count">
      {data.total} chunk{data.total === 1 ? "" : "s"}
    </span>
  );
}

function DocumentText({ id }: { id: string }) {
  const token = useAuthStore((s) => s.token);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["documents", id, "text"],
    queryFn: () => getDocumentText(token!, id),
    enabled: !!token,
  });

  return (
    <div className="mt-3 rounded-md border bg-muted/50 p-3">
      {isLoading && (
        <p className="text-xs text-muted-foreground">Loading text…</p>
      )}
      {isError && (
        <p className="text-xs text-destructive">Failed to load text.</p>
      )}
      {data && (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">
          {data.extracted_text?.trim() || "(no text extracted)"}
        </pre>
      )}
    </div>
  );
}
