"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  FileAudio,
  FileImage,
  FileText,
  FileType,
  Files,
  RefreshCw,
  ScrollText,
  Sparkles,
  Trash2,
} from "lucide-react";
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

function hasInFlight(items: DocumentItem[] | undefined): boolean {
  return (
    !!items &&
    items.some((d) => d.status === "uploaded" || d.status === "processing")
  );
}

function iconForMime(mime: string) {
  if (mime.startsWith("image/")) return FileImage;
  if (mime.startsWith("audio/")) return FileAudio;
  if (mime.includes("pdf")) return FileType;
  return FileText;
}

export function DocumentsList() {
  const token = useAuthStore((s) => s.token);
  const queryClient = useQueryClient();
  const [openId, setOpenId] = useState<string | null>(null);
  const [openSummaryId, setOpenSummaryId] = useState<string | null>(null);
  const [reindexStatus, setReindexStatus] = useState<{
    id: string;
    kind: "ok" | "err";
    message: string;
  } | null>(null);
  const [summarizeStatus, setSummarizeStatus] = useState<{
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

  const summarizeMutation = useMutation({
    mutationFn: (id: string) => resummarizeDocument(token!, id),
    onSuccess: (_, id) => {
      setSummarizeStatus({
        id,
        kind: "ok",
        message: "Summarizing… the summary will appear within ~10s.",
      });
      // Refresh once the worker should have written the summary.
      setTimeout(
        () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
        12_000,
      );
    },
    onError: (err: unknown, id) => {
      const msg = err instanceof Error ? err.message : "Summarize failed.";
      setSummarizeStatus({ id, kind: "err", message: msg });
    },
  });

  return (
    <Card className="glass w-full py-6">
      <CardHeader className="px-6 pb-2">
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
      <CardContent className="px-6 pt-2">
        {isLoading && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}
        {isError && (
          <p className="text-sm text-destructive">Failed to load documents.</p>
        )}
        {data && data.items.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
            <Files className="size-8 text-muted-foreground" aria-hidden="true" />
            <p className="text-sm text-muted-foreground">
              No documents yet. Upload one to get started.
            </p>
          </div>
        )}
        {data && data.items.length > 0 && (
          <ul className="space-y-3">
            {data.items.map((doc) => {
              const Icon = iconForMime(doc.content_type);
              const isOpen = openId === doc.id;
              return (
                <li
                  key={doc.id}
                  className="rounded-xl border border-border/60 bg-background/40 p-4 transition-colors hover:bg-background/70"
                >
                  <div className="flex items-start gap-4">
                    <span
                      aria-hidden="true"
                      className="grid size-9 shrink-0 place-items-center rounded-lg bg-accent/60 text-[color:var(--brand)]"
                    >
                      <Icon className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-medium">
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
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {formatBytes(doc.size_bytes)} · {doc.content_type}
                        {doc.status === "processed" && (
                          <>
                            {" · "}
                            <ChunkCount id={doc.id} />
                          </>
                        )}
                      </p>
                    </div>
                    <div className="ml-auto flex shrink-0 items-center gap-1">
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
                        onClick={() => {
                          setSummarizeStatus(null);
                          summarizeMutation.mutate(doc.id);
                        }}
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
                        onClick={() => {
                          setReindexStatus(null);
                          reindexMutation.mutate(doc.id);
                        }}
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
                  {reindexStatus?.id === doc.id && (
                    <p
                      className={
                        "mt-2 text-xs " +
                        (reindexStatus.kind === "ok"
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-destructive")
                      }
                      data-testid="reindex-status"
                    >
                      {reindexStatus.message}
                    </p>
                  )}
                  {summarizeStatus?.id === doc.id && (
                    <p
                      className={
                        "mt-2 text-xs " +
                        (summarizeStatus.kind === "ok"
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-destructive")
                      }
                      data-testid="summarize-status"
                    >
                      {summarizeStatus.message}
                    </p>
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
