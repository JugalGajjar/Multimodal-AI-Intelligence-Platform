"use client";

import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  MessageSquareText,
  Network,
  Route,
  ScrollText,
  SendHorizontal,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import {
  streamChatQuery,
  type ChatCitation,
  type ChatResponse,
  type ChatStreamMeta,
  type ChatVerification,
  type VerificationVerdict,
} from "@/lib/chat-api";
import { chatToGraphProps } from "@/lib/graph-from-chat";
import { useAuthStore } from "@/store/auth";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403) return "Please sign in again.";
    if (err.status === 422) return "Query is invalid.";
    if (err.status === 429)
      return "Free-tier rate limit hit. Wait a few seconds and retry.";
    if (err.status === 502)
      return "The model provider returned an error. Try again or pick a different model.";
    if (err.status === 503)
      return "Chat is not configured. The OpenRouter API key is missing.";
    return `Request failed (${err.status}).`;
  }
  if (err && typeof err === "object" && "status" in err && "detail" in err) {
    const { status: s, detail } = err as { status: number; detail: string };
    if (s === 429) return "Free-tier rate limit hit. Wait a few seconds and retry.";
    if (s === 503) return "Chat is not configured. The model provider key is missing.";
    return `Request failed (${s}): ${detail}`;
  }
  return "Network error. Try again.";
}

type StreamState = {
  status: "idle" | "streaming" | "done" | "error";
  meta: ChatStreamMeta | null;
  text: string;
  verification: ChatVerification | null;
  error: unknown | null;
};

const INITIAL_STREAM: StreamState = {
  status: "idle",
  meta: null,
  text: "",
  verification: null,
  error: null,
};

export function ChatPanel() {
  const token = useAuthStore((s) => s.token);
  const [query, setQuery] = useState("");
  const [stream, setStream] = useState<StreamState>(INITIAL_STREAM);
  const pending = stream.status === "streaming";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !query.trim() || pending) return;

    setStream({ ...INITIAL_STREAM, status: "streaming" });

    try {
      await streamChatQuery(
        token,
        { query: query.trim(), top_k: 4 },
        {
          onMeta: (meta) => setStream((s) => ({ ...s, meta })),
          onToken: (text) =>
            setStream((s) => ({ ...s, text: s.text + text })),
          onDone: (done) =>
            setStream((s) => ({
              ...s,
              status: "done",
              verification: done.verification,
            })),
          onError: (err) =>
            setStream((s) => ({ ...s, status: "error", error: err })),
        },
      );
      // If the stream ended without a `done` event, treat as complete.
      setStream((s) => (s.status === "streaming" ? { ...s, status: "done" } : s));
    } catch (err) {
      setStream((s) => ({ ...s, status: "error", error: err }));
    }
  }

  const response = streamToResponse(stream);

  return (
    <Card className="glass w-full py-6">
      <CardHeader className="px-4 pb-2 sm:px-6">
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquareText
            className="size-4 text-[color:var(--brand)]"
            aria-hidden="true"
          />
          Ask your documents
        </CardTitle>
        <CardDescription className="mt-1">
          Retrieval-augmented chat over your uploaded text, PDFs, images,
          audio, and video. Answers stream as the model thinks.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5 px-4 pt-2 sm:px-6">
        <form onSubmit={onSubmit} className="space-y-2.5">
          <Label
            htmlFor="chat-query"
            className="text-xs uppercase text-muted-foreground"
          >
            Question
          </Label>
          <div className="relative">
            <textarea
              id="chat-query"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="What does the document say about…?"
              rows={3}
              className="w-full resize-none rounded-xl border border-input bg-background/50 px-4 py-3.5 pr-14 text-sm leading-relaxed shadow-sm transition-colors placeholder:text-muted-foreground/70 focus-visible:border-[color:var(--brand)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--brand)]/30 sm:pr-36"
              required
            />
            <Button
              type="submit"
              disabled={pending || !query.trim()}
              aria-label={pending ? "Thinking" : "Send"}
              className="absolute bottom-3 right-3 bg-gradient-brand text-brand-foreground glow-brand px-3 sm:px-4"
              size="sm"
            >
              {pending ? (
                <>
                  <Loader2
                    className="size-3.5 animate-spin"
                    aria-hidden="true"
                  />
                  <span className="hidden sm:inline">Thinking…</span>
                </>
              ) : (
                <>
                  <SendHorizontal className="size-3.5" aria-hidden="true" />
                  <span className="hidden sm:inline">Send</span>
                </>
              )}
            </Button>
          </div>
        </form>

        {stream.status === "error" && (
          <p
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            {errorMessage(stream.error)}
          </p>
        )}

        {/* Initial empty state, no query yet */}
        {stream.status === "idle" && !response && (
          <div
            className="rounded-xl border border-dashed border-border/70 bg-background/30 px-5 py-6 text-center"
            data-testid="chat-empty"
          >
            <MessageSquareText
              className="mx-auto size-6 text-muted-foreground/70"
              aria-hidden="true"
            />
            <p className="mt-2 text-xs text-muted-foreground">
              Ask anything about your documents. Answers stream with citations
              and a live entity graph when relevant.
            </p>
          </div>
        )}

        {/* Skeleton while streaming has started but no meta + no tokens arrived */}
        {pending && !response && (
          <div
            className="space-y-3 rounded-xl border border-border/60 bg-background/50 px-5 py-4"
            data-testid="chat-answer-skeleton"
          >
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-11/12" />
            <Skeleton className="h-3 w-3/4" />
          </div>
        )}

        {response && <Answer response={response} streaming={pending} />}
      </CardContent>
    </Card>
  );
}

function streamToResponse(stream: StreamState): ChatResponse | null {
  if (!stream.meta && stream.text === "" && stream.status !== "done") return null;
  const meta = stream.meta;
  return {
    answer: stream.text,
    citations: meta?.citations ?? [],
    entities_used: meta?.entities_used ?? [],
    model: meta?.model ?? "",
    used_context: meta?.used_context ?? false,
    used_graph: meta?.used_graph ?? false,
    verification: stream.verification ?? undefined,
    intent: meta?.intent,
  };
}

function Answer({
  response,
  streaming = false,
}: {
  response: ChatResponse;
  streaming?: boolean;
}) {
  const { data: graphData, highlighted, hasGraph } = chatToGraphProps(response);

  return (
    <div className="space-y-5 pt-2" data-testid="chat-answer">
      <div className="flex flex-wrap items-center gap-2">
        {response.model && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {response.model}
          </Badge>
        )}
        {response.intent && response.intent !== "chat" && (
          <IntentBadge intent={response.intent} />
        )}
        {response.used_context ? (
          <Badge className="gap-1 bg-gradient-brand text-brand-foreground">
            <Sparkles className="size-3" aria-hidden="true" />
            used context
          </Badge>
        ) : (
          <Badge variant="outline">no context</Badge>
        )}
        {response.used_graph && (
          <Badge className="gap-1 bg-emerald-500/90 text-white hover:bg-emerald-500 dark:bg-emerald-500/80">
            <Network className="size-3" aria-hidden="true" />
            used graph
          </Badge>
        )}
        {response.verification && (
          <VerificationBadge verification={response.verification} />
        )}
      </div>

      <div className="rounded-xl border border-border/60 bg-background/50 px-4 py-4 text-sm leading-relaxed break-words sm:px-5">
        <p className="whitespace-pre-wrap" data-testid="chat-answer-text">
          {response.answer}
          {streaming && (
            <span
              aria-hidden="true"
              className="ml-0.5 inline-block h-3.5 w-1.5 -translate-y-px animate-pulse bg-[color:var(--brand)]"
              data-testid="streaming-cursor"
            />
          )}
        </p>
      </div>

      {response.verification &&
        response.verification.verdict !== "skipped" &&
        response.verification.unsupported_claims.length > 0 && (
          <UnsupportedClaimsPanel verification={response.verification} />
        )}

      {response.citations.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Citations
          </p>
          <ol className="space-y-2">
            {response.citations.map((c, i) => (
              <CitationItem key={c.chunk_id} index={i + 1} citation={c} />
            ))}
          </ol>
        </div>
      )}

      {hasGraph && (
        <div className="space-y-2" data-testid="inline-graph">
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Knowledge graph
            </p>
            <Link
              href="/dashboard/graph"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-[color:var(--brand)]"
              data-testid="inline-graph-explore-link"
            >
              Explore full graph
              <ArrowUpRight className="size-3" aria-hidden="true" />
            </Link>
          </div>
          <div className="h-[40svh] min-h-[260px] overflow-hidden rounded-xl border border-border/60 bg-background/30 sm:h-[45svh]">
            <KnowledgeGraph
              nodes={graphData.nodes}
              links={graphData.links}
              highlighted={highlighted}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Highlighted nodes are entities the answer mentions by name.
          </p>
        </div>
      )}
    </div>
  );
}

function IntentBadge({ intent }: { intent: string }) {
  const label =
    intent === "summarize"
      ? "summary route"
      : intent === "explain_graph"
        ? "graph route"
        : intent;
  const Icon =
    intent === "summarize" ? ScrollText : intent === "explain_graph" ? Network : Route;
  return (
    <Badge
      variant="outline"
      className="gap-1 border-[color:var(--brand)]/40 text-[color:var(--brand)]"
      title={`Router classified this query as "${intent}"`}
      data-testid="intent-badge"
    >
      <Icon className="size-3" aria-hidden="true" />
      {label}
    </Badge>
  );
}

const VERDICT_STYLES: Record<
  VerificationVerdict,
  { label: string; className: string; Icon: typeof ShieldCheck }
> = {
  verified: {
    label: "verified",
    className: "bg-emerald-500/90 text-white hover:bg-emerald-500",
    Icon: ShieldCheck,
  },
  partial: {
    label: "partial support",
    className: "bg-amber-500/90 text-white hover:bg-amber-500",
    Icon: ShieldAlert,
  },
  unsupported: {
    label: "unsupported",
    className: "bg-red-500/90 text-white hover:bg-red-500",
    Icon: ShieldAlert,
  },
  skipped: {
    label: "not verified",
    className: "",
    Icon: ShieldQuestion,
  },
};

function VerificationBadge({
  verification,
}: {
  verification: ChatVerification;
}) {
  const v = verification.verdict;
  const style = VERDICT_STYLES[v];
  const Icon = style.Icon;
  const pct = Math.round(verification.groundedness_score * 100);
  const counts =
    verification.total_claims > 0
      ? ` · ${verification.supported_claims}/${verification.total_claims}`
      : "";
  const title =
    v === "skipped"
      ? verification.skip_reason || "verification skipped"
      : `groundedness ${pct}%${counts}`;

  if (v === "skipped") {
    return (
      <Badge
        variant="outline"
        className="gap-1 text-muted-foreground"
        title={title}
        data-testid="verification-badge"
      >
        <Icon className="size-3" aria-hidden="true" />
        not verified
      </Badge>
    );
  }

  return (
    <Badge
      className={"gap-1 " + style.className}
      title={title}
      data-testid="verification-badge"
    >
      <Icon className="size-3" aria-hidden="true" />
      {style.label}
      {verification.total_claims > 0 && (
        <span className="ml-0.5 opacity-90">· {pct}%</span>
      )}
    </Badge>
  );
}

function UnsupportedClaimsPanel({
  verification,
}: {
  verification: ChatVerification;
}) {
  const [open, setOpen] = useState(false);
  const count = verification.unsupported_claims.length;

  return (
    <div
      className="rounded-xl border border-amber-500/40 bg-amber-500/5"
      data-testid="unsupported-claims-panel"
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-xs font-medium"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          <AlertTriangle
            className="size-3.5 text-amber-600 dark:text-amber-400"
            aria-hidden="true"
          />
          <span>
            {count} unsupported claim{count === 1 ? "" : "s"}
          </span>
          <span className="font-normal text-muted-foreground">
            (not entailed by the cited context)
          </span>
        </span>
        {open ? (
          <ChevronUp className="size-3.5 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden="true" />
        )}
      </button>
      {open && (
        <ul
          className="space-y-1.5 border-t border-amber-500/30 px-4 py-3 text-xs text-foreground/90"
          data-testid="unsupported-claims-list"
        >
          {verification.unsupported_claims.map((c, i) => (
            <li key={`${i}-${c.slice(0, 24)}`} className="flex gap-2">
              <CheckCircle2
                className="mt-0.5 size-3 shrink-0 rotate-180 text-muted-foreground"
                aria-hidden="true"
              />
              <span>{c}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function CitationItem({
  index,
  citation,
}: {
  index: number;
  citation: ChatCitation;
}) {
  return (
    <li
      className="rounded-lg border border-border/60 bg-background/50 px-3 py-2.5 text-xs"
      data-testid="citation-item"
    >
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="font-mono text-muted-foreground">
          <span className="text-[color:var(--brand)]">[{index}]</span> doc{" "}
          {citation.document_id.slice(0, 8)}… · chunk {citation.chunk_index}
        </span>
        <span className="text-muted-foreground">
          score {citation.score.toFixed(3)}
        </span>
      </div>
      <p className="text-foreground/90">{citation.text_preview}</p>
    </li>
  );
}
