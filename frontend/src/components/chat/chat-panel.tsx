"use client";

import { useMutation } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Loader2,
  MessageSquareText,
  Network,
  SendHorizontal,
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
import { ApiError } from "@/lib/api";
import {
  sendChatQuery,
  type ChatCitation,
  type ChatResponse,
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
      return "Chat is not configured — the OpenRouter API key is missing.";
    return `Request failed (${err.status}).`;
  }
  return "Network error. Try again.";
}

export function ChatPanel() {
  const token = useAuthStore((s) => s.token);
  const [query, setQuery] = useState("");

  const mutation = useMutation<ChatResponse, unknown, string>({
    mutationFn: (q: string) => sendChatQuery(token!, { query: q, top_k: 4 }),
  });

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !query.trim()) return;
    mutation.mutate(query.trim());
  }

  return (
    <Card className="glass w-full py-6">
      <CardHeader className="px-6 pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquareText
            className="size-4 text-[color:var(--brand)]"
            aria-hidden="true"
          />
          Ask your documents
        </CardTitle>
        <CardDescription className="mt-1">
          Retrieval-augmented chat over your uploaded text, PDFs, images, and
          audio. Answers are grounded and cited.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5 px-6 pt-2">
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
              className="w-full resize-none rounded-xl border border-input bg-background/50 px-4 py-3.5 pr-36 text-sm leading-relaxed shadow-sm transition-colors placeholder:text-muted-foreground/70 focus-visible:border-[color:var(--brand)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--brand)]/30"
              required
            />
            <Button
              type="submit"
              disabled={mutation.isPending || !query.trim()}
              className="absolute bottom-3 right-3 bg-gradient-brand text-brand-foreground glow-brand px-4"
              size="sm"
            >
              {mutation.isPending ? (
                <>
                  <Loader2
                    className="size-3.5 animate-spin"
                    aria-hidden="true"
                  />
                  Thinking…
                </>
              ) : (
                <>
                  <SendHorizontal className="size-3.5" aria-hidden="true" />
                  Send
                </>
              )}
            </Button>
          </div>
        </form>

        {mutation.isError && (
          <p
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            {errorMessage(mutation.error)}
          </p>
        )}

        {mutation.data && <Answer response={mutation.data} />}
      </CardContent>
    </Card>
  );
}

function Answer({ response }: { response: ChatResponse }) {
  const { data: graphData, highlighted, hasGraph } = chatToGraphProps(response);

  return (
    <div className="space-y-5 pt-2" data-testid="chat-answer">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="font-mono text-[10px]">
          {response.model}
        </Badge>
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
      </div>

      <div className="rounded-xl border border-border/60 bg-background/50 px-5 py-4 text-sm leading-relaxed">
        <p className="whitespace-pre-wrap">{response.answer}</p>
      </div>

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
          <div className="overflow-hidden rounded-xl border border-border/60 bg-background/30">
            <KnowledgeGraph
              nodes={graphData.nodes}
              links={graphData.links}
              height={300}
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
