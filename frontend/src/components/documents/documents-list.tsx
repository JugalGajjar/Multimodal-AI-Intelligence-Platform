"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  FileAudio,
  FileImage,
  FileText,
  FileType,
  FileVideo,
  Files,
  RefreshCw,
  ScrollText,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  deleteDocument,
  formatBytes,
  getDocumentText,
  listDocumentChunks,
  listDocuments,
  reindexDocumentGraph,
  resummarizeDocument,
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

/** Decide how aggressively to poll /documents based on item state.
 *  - "uploaded" / "processing": worker is actively running → poll fast.
 *  - "processed" without a summary, recently updated: summary writes happen
 *    AFTER status flips to processed, so keep polling briefly to catch them.
 *  - Otherwise: stop polling. */
function pollIntervalMs(items: DocumentItem[] | undefined): number | false {
  if (!items) return false;
  if (items.some((d) => d.status === "uploaded" || d.status === "processing")) {
    return 1500;
  }
  const now = Date.now();
  const waitingForSummary = items.some(
    (d) =>
      d.status === "processed" &&
      !d.summary &&
      now - new Date(d.updated_at).getTime() < 60_000,
  );
  return waitingForSummary ? 2500 : false;
}

function iconForMime(mime: string) {
  if (mime.startsWith("image/")) return FileImage;
  if (mime.startsWith("audio/")) return FileAudio;
  if (mime.startsWith("video/")) return FileVideo;
  if (mime.includes("pdf")) return FileType;
  return FileText;
}

export function DocumentsList() {
  const token = useAuthStore((s) => s.token);
  const queryClient = useQueryClient();
  const [openId, setOpenId] = useState<string | null>(null);
  const [openSummaryId, setOpenSummaryId] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery<DocumentListResponse>({
    queryKey: ["documents"],
    queryFn: () => listDocuments(token!),
    enabled: !!token,
    refetchInterval: (query) => pollIntervalMs(query.state.data?.items),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteDocument(token!, id),
    onSuccess: () => {
      toast.success("Document deleted.");
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (err: unknown) =>
      toast.error(err instanceof Error ? err.message : "Delete failed."),
  });

  const reindexMutation = useMutation({
    mutationFn: (id: string) => reindexDocumentGraph(token!, id),
    onSuccess: () =>
      toast.success("Re-indexing graph", {
        description: "New entities will appear within ~10s.",
      }),
    onError: (err: unknown) =>
      toast.error(err instanceof Error ? err.message : "Re-index failed."),
  });

  const summarizeMutation = useMutation({
    mutationFn: (id: string) => resummarizeDocument(token!, id),
    onSuccess: () => {
      toast.success("Summarizing", {
        description: "The summary will appear within ~10s.",
      });
      setTimeout(
        () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
        12_000,
      );
    },
    onError: (err: unknown) =>
      toast.error(err instanceof Error ? err.message : "Summarize failed."),
  });

  return (
    <Card className="glass flex h-full min-h-0 w-full flex-col py-6">
      <CardHeader className="shrink-0 px-4 pb-2 sm:px-6">
        <CardTitle className="flex items-center gap-2 text-base">
          <Files className="size-4 text-[color:var(--brand)]" aria-hidden="true" />
          Your documents
        </CardTitle>
        <CardDescription className="mt-1">
          {data
            ? `${data.total} document${data.total === 1 ? "" : "s"}`
            : "Loading…"}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col px-4 pt-2 sm:px-6">
        {isLoading && (
          <ul className="space-y-3" data-testid="documents-skeleton">
            {[0, 1, 2].map((i) => (
              <li
                key={i}
                className="rounded-xl border border-border/60 bg-background/40 p-4"
              >
                <div className="flex items-start gap-4">
                  <Skeleton className="size-9 shrink-0 rounded-lg" />
                  <div className="min-w-0 flex-1 space-y-2">
                    <Skeleton className="h-4 w-2/3" />
                    <Skeleton className="h-3 w-1/3" />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        {isError && (
          <p className="text-sm text-destructive">Failed to load documents.</p>
        )}
        {data && data.items.length === 0 && (
          <div
            className="flex flex-col items-center justify-center gap-3 py-12 text-center"
            data-testid="documents-empty"
          >
            <div
              aria-hidden="true"
              className="grid size-14 place-items-center rounded-2xl bg-gradient-brand text-brand-foreground glow-brand"
            >
              <Upload className="size-6" />
            </div>
            <div className="space-y-1">
              <p className="text-sm font-medium">No documents yet</p>
              <p className="text-xs text-muted-foreground">
                Drop a file in the panel above. PDFs, images, audio, video,
                or text.
              </p>
            </div>
          </div>
        )}
        {data && data.items.length > 0 && (
          <ul
            className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1"
            data-testid="documents-scroll"
          >
            {data.items.map((doc) => {
              const Icon = iconForMime(doc.content_type);
              const isOpen = openId === doc.id;
              return (
                <li
                  key={doc.id}
                  className="rounded-xl border border-border/60 bg-background/40 p-3 transition-colors hover:bg-background/70 sm:p-4"
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-4">
                    <div className="flex min-w-0 items-start gap-3 sm:flex-1 sm:gap-4">
                      <span
                        aria-hidden="true"
                        className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/60 text-[color:var(--brand)]"
                      >
                        <Icon className="size-4" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="min-w-0 truncate text-sm font-medium">
                            {doc.filename}
                          </p>
                          <Badge
                            variant={STATUS_VARIANT[doc.status]}
                            className={
                              doc.status === "processed"
                                ? "bg-gradient-brand text-brand-foreground"
                                : ""
                            }
                          >
                            {doc.status}
                          </Badge>
                        </div>
                        <p className="mt-0.5 break-words text-xs text-muted-foreground">
                          {formatBytes(doc.size_bytes)} · {doc.content_type}
                          {doc.status === "processed" && (
                            <>
                              {" · "}
                              <ChunkCount id={doc.id} />
                            </>
                          )}
                        </p>
                        {doc.status === "failed" && doc.error_message && (
                          <p className="mt-1 break-words text-xs text-destructive">
                            {doc.error_message}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="-ml-1 flex flex-wrap items-center gap-1 sm:ml-auto sm:shrink-0 sm:flex-nowrap">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={doc.status !== "processed"}
                        onClick={() =>
                          setOpenId((id) => (id === doc.id ? null : doc.id))
                        }
                        title={isOpen ? "Hide text" : "View text"}
                        className="gap-1"
                      >
                        {isOpen ? (
                          <ChevronUp className="size-3.5" aria-hidden="true" />
                        ) : (
                          <ChevronDown className="size-3.5" aria-hidden="true" />
                        )}
                        <span className="hidden sm:inline">
                          {isOpen ? "Hide text" : "View text"}
                        </span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={
                          doc.status !== "processed" ||
                          (summarizeMutation.isPending &&
                            summarizeMutation.variables === doc.id)
                        }
                        onClick={() => summarizeMutation.mutate(doc.id)}
                        title={
                          doc.summary
                            ? "Re-run summarization"
                            : "Generate a TL;DR + key points + topics"
                        }
                        data-testid="summarize-button"
                        className="gap-1"
                      >
                        <Sparkles
                          className={
                            "size-3.5 " +
                            (summarizeMutation.isPending &&
                            summarizeMutation.variables === doc.id
                              ? "animate-pulse"
                              : "")
                          }
                          aria-hidden="true"
                        />
                        <span className="hidden sm:inline">
                          {summarizeMutation.isPending &&
                          summarizeMutation.variables === doc.id
                            ? "Summarizing…"
                            : doc.summary
                              ? "Re-summarize"
                              : "Summarize"}
                        </span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={
                          doc.status !== "processed" ||
                          (reindexMutation.isPending &&
                            reindexMutation.variables === doc.id)
                        }
                        onClick={() => reindexMutation.mutate(doc.id)}
                        title="Re-run entity extraction over this document's chunks"
                        data-testid="reindex-graph-button"
                        className="gap-1"
                      >
                        <RefreshCw
                          className={
                            "size-3.5 " +
                            (reindexMutation.isPending &&
                            reindexMutation.variables === doc.id
                              ? "animate-spin"
                              : "")
                          }
                          aria-hidden="true"
                        />
                        <span className="hidden sm:inline">
                          {reindexMutation.isPending &&
                          reindexMutation.variables === doc.id
                            ? "Re-indexing…"
                            : "Re-index graph"}
                        </span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={deleteMutation.isPending}
                        onClick={() => deleteMutation.mutate(doc.id)}
                        title="Delete document"
                        className="gap-1 text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 className="size-3.5" aria-hidden="true" />
                        <span className="hidden sm:inline">Delete</span>
                      </Button>
                    </div>
                  </div>
                  {doc.summary && (
                    <SummaryBlock
                      summary={doc.summary}
                      expanded={openSummaryId === doc.id}
                      onToggle={() =>
                        setOpenSummaryId((id) =>
                          id === doc.id ? null : doc.id,
                        )
                      }
                    />
                  )}
                  {isOpen && <DocumentText id={doc.id} />}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function SummaryBlock({
  summary,
  expanded,
  onToggle,
}: {
  summary: NonNullable<DocumentItem["summary"]>;
  expanded: boolean;
  onToggle: () => void;
}) {
  const hasDetails =
    summary.key_points.length > 0 || summary.topics.length > 0;

  return (
    <div
      className="mt-3 rounded-lg border border-[color:var(--brand)]/20 bg-[color:var(--brand)]/5 p-3"
      data-testid="document-summary"
    >
      <div className="flex items-start gap-2.5">
        <ScrollText
          className="mt-0.5 size-3.5 shrink-0 text-[color:var(--brand)]"
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <p
            className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground"
            aria-hidden="true"
          >
            Summary
          </p>
          <p className="mt-1 text-xs leading-relaxed text-foreground/90">
            {summary.tldr || "(no TL;DR)"}
          </p>
          {hasDetails && (
            <button
              type="button"
              onClick={onToggle}
              className="mt-2 inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground hover:text-foreground"
              aria-expanded={expanded}
              data-testid="summary-toggle"
            >
              {expanded ? (
                <ChevronUp className="size-3" aria-hidden="true" />
              ) : (
                <ChevronDown className="size-3" aria-hidden="true" />
              )}
              {expanded ? "Hide details" : "Show key points + topics"}
            </button>
          )}
          {expanded && hasDetails && (
            <div className="mt-3 space-y-3" data-testid="summary-details">
              {summary.key_points.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    Key points
                  </p>
                  <ul className="space-y-1 text-xs text-foreground/90">
                    {summary.key_points.map((p, i) => (
                      <li
                        key={`${i}-${p.slice(0, 24)}`}
                        className="flex gap-2"
                      >
                        <span
                          className="mt-1.5 inline-block size-1 shrink-0 rounded-full bg-[color:var(--brand)]"
                          aria-hidden="true"
                        />
                        <span>{p}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {summary.topics.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    Topics
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {summary.topics.map((t, i) => (
                      <Badge
                        key={`${i}-${t}`}
                        variant="outline"
                        className="font-normal"
                      >
                        {t}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
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
    <div className="mt-3 rounded-lg border border-border/60 bg-muted/40 p-3">
      {isLoading && (
        <p className="text-xs text-muted-foreground">Loading text…</p>
      )}
      {isError && (
        <p className="text-xs text-destructive">Failed to load text.</p>
      )}
      {data && (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs">
          {data.extracted_text?.trim() || "(no text extracted)"}
        </pre>
      )}
    </div>
  );
}
