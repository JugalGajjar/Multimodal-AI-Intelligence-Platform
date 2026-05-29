"use client";

import { useMutation } from "@tanstack/react-query";
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
    <Card className="w-full max-w-2xl">
      <CardHeader>
        <CardTitle>Ask your documents</CardTitle>
        <CardDescription>
          Retrieval-augmented chat over your uploaded text and PDFs.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={onSubmit} className="space-y-2">
          <Label htmlFor="chat-query">Question</Label>
          <textarea
            id="chat-query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="What does the document say about…?"
            rows={3}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            required
          />
          <Button
            type="submit"
            disabled={mutation.isPending || !query.trim()}
          >
            {mutation.isPending ? "Thinking…" : "Send"}
          </Button>
        </form>

        {mutation.isError && (
          <p role="alert" className="text-sm text-destructive">
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
    <div className="space-y-3" data-testid="chat-answer">
      <div className="flex items-center gap-2">
        <Badge variant="secondary">{response.model}</Badge>
        {response.used_context ? (
          <Badge variant="default">used context</Badge>
        ) : (
          <Badge variant="outline">no context</Badge>
        )}
        {response.used_graph && (
          <Badge variant="default" className="bg-emerald-600 hover:bg-emerald-700">
            used graph
          </Badge>
        )}
      </div>

      <div className="rounded-md border bg-muted/30 p-3 text-sm">
        <p className="whitespace-pre-wrap">{response.answer}</p>
      </div>

      {response.citations.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase text-muted-foreground">
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
            <p className="text-xs font-medium uppercase text-muted-foreground">
              Knowledge graph
            </p>
            <Link
              href="/dashboard/graph"
              className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
              data-testid="inline-graph-explore-link"
            >
              Explore full graph →
            </Link>
          </div>
          <KnowledgeGraph
            nodes={graphData.nodes}
            links={graphData.links}
            height={300}
            highlighted={highlighted}
          />
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
      className="rounded-md border bg-background p-2 text-xs"
      data-testid="citation-item"
    >
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="font-mono text-muted-foreground">
          [{index}] doc {citation.document_id.slice(0, 8)}… · chunk{" "}
          {citation.chunk_index}
        </span>
        <span className="text-muted-foreground">
          score {citation.score.toFixed(3)}
        </span>
      </div>
      <p className="text-foreground">{citation.text_preview}</p>
    </li>
  );
}
