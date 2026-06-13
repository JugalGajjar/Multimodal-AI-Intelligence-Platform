"use client";

import {
  Database,
  Globe,
  Loader2,
  MessageSquareText,
  Plus,
  SendHorizontal,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Answer } from "@/components/chat/answer";
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
import { ToggleChip } from "@/components/ui/toggle-chip";
import { ApiError } from "@/lib/api";
import {
  streamChatQuery,
  type ChatResponse,
  type ChatStreamMeta,
  type ChatVerification,
} from "@/lib/chat-api";
import { useAuthStore } from "@/store/auth";
import { useChatSessionStore } from "@/store/chat-session";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401 || err.status === 403) return "Please sign in again.";
    if (err.status === 404)
      return "This chat session no longer exists. Start a new chat.";
    if (err.status === 422) return "Query is invalid.";
    if (err.status === 429)
      return "Free-tier rate limit hit. Wait a few seconds and retry.";
    if (err.status === 502)
      return "The model provider returned an error. Try again or pick a different model.";
    if (err.status === 503)
      return "Chat is not configured. A required provider key is missing on the server.";
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
  // From meta — buffer rendering until `done` when true.
  strict: boolean;
  strictRefusal: string | null;
};

const INITIAL_STREAM: StreamState = {
  status: "idle",
  meta: null,
  text: "",
  verification: null,
  error: null,
  strict: false,
  strictRefusal: null,
};

const STICK_TO_BOTTOM_PX = 80;

export function ChatPanel() {
  const token = useAuthStore((s) => s.token);
  const chatId = useChatSessionStore((s) => s.chatId);
  const turns = useChatSessionStore((s) => s.turns);
  const setChatId = useChatSessionStore((s) => s.setChatId);
  const addTurn = useChatSessionStore((s) => s.addTurn);
  const resetSession = useChatSessionStore((s) => s.reset);

  const [query, setQuery] = useState("");
  const [currentQuestion, setCurrentQuestion] = useState("");
  const [useRag, setUseRag] = useState(true);
  const [useWeb, setUseWeb] = useState(false);
  const [stream, setStream] = useState<StreamState>(INITIAL_STREAM);
  const pending = stream.status === "streaming";

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const nearBottomRef = useRef(true);

  // Stick to bottom only if the user was already there — don't yank them up.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && nearBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [stream.text, turns.length, pending]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    nearBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < STICK_TO_BOTTOM_PX;
  }

  function onNewChat() {
    if (pending) return;
    resetSession();
    setStream(INITIAL_STREAM);
    setQuery("");
    setCurrentQuestion("");
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !query.trim() || pending) return;

    const question = query.trim();
    setCurrentQuestion(question);
    setQuery("");
    nearBottomRef.current = true;

    // `acc` is the source of truth; setStream just mirrors it (React batching
    // makes setStream(s => ...) reads after `await` unreliable).
    const acc: StreamState = { ...INITIAL_STREAM, status: "streaming" };
    const sync = () => setStream({ ...acc });
    sync();

    try {
      await streamChatQuery(
        token,
        {
          query: question,
          top_k: 4,
          use_rag: useRag,
          use_web: useWeb,
          chat_id: chatId,
        },
        {
          onMeta: (meta) => {
            if (!useChatSessionStore.getState().chatId && meta.chat_id) {
              setChatId(meta.chat_id);
            }
            acc.meta = meta;
            acc.strict = meta.strict ?? false;
            sync();
          },
          onToken: (text) => {
            acc.text += text;
            sync();
          },
          onDone: (done) => {
            acc.status = "done";
            acc.verification = done.verification;
            acc.strictRefusal = done.strict_refusal ?? null;
            sync();
          },
          onError: (err) => {
            acc.status = "error";
            acc.error = err;
            // First-turn errors: backend cleans up the chat row, so drop the
            // id we just adopted or the retry hits 404 forever.
            if (useChatSessionStore.getState().turns.length === 0) {
              resetSession();
            }
            sync();
          },
        },
      );
      // Stream ended without `done` — treat as complete.
      if (acc.status === "streaming") {
        acc.status = "done";
        sync();
      }

      if (acc.status === "done") {
        const response = streamToResponse(acc);
        if (response) {
          addTurn(question, response);
          setStream(INITIAL_STREAM);
          setCurrentQuestion("");
        }
      } else {
        // Restore the question so the user can retry — backend persists nothing.
        setQuery(question);
      }
    } catch (err) {
      acc.status = "error";
      acc.error = err;
      sync();
      setQuery(question);
    }
  }

  const liveResponse = streamToResponse(stream);
  const hasThread = turns.length > 0 || pending || stream.status === "error";

  return (
    <Card className="glass flex w-full flex-col py-6">
      <CardHeader className="px-4 pb-2 sm:px-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <MessageSquareText
                className="size-4 text-[color:var(--brand)]"
                aria-hidden="true"
              />
              Ask your documents
            </CardTitle>
            <CardDescription className="mt-1">
              Retrieval-augmented chat over your uploaded text, PDFs, images,
              audio, and video. Follow-ups see earlier turns; a hard refresh
              starts a new chat.
            </CardDescription>
          </div>
          {hasThread && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onNewChat}
              disabled={pending}
              data-testid="chat-new"
              className="shrink-0 gap-1"
            >
              <Plus className="size-3.5" aria-hidden="true" />
              New chat
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-5 px-4 pt-2 sm:px-6">
        {/* Initial empty state, no thread yet */}
        {!hasThread && (
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

        {hasThread && (
          <div
            ref={scrollRef}
            onScroll={onScroll}
            className="max-h-[60svh] space-y-6 overflow-y-auto pr-1"
            data-testid="chat-thread"
          >
            {turns.map((turn) => (
              <div key={turn.id} className="space-y-2" data-testid="chat-turn">
                <QuestionBubble question={turn.question} />
                <Answer response={turn.response} />
              </div>
            ))}

            {/* In-flight turn */}
            {(pending || stream.status === "error") && (
              <div className="space-y-2" data-testid="chat-live-turn">
                <QuestionBubble question={currentQuestion} />

                {stream.status === "error" && (
                  <p
                    role="alert"
                    className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
                  >
                    {errorMessage(stream.error)}
                  </p>
                )}

                {/* Skeleton until meta/tokens arrive */}
                {pending && !liveResponse && !stream.strict && (
                  <div
                    className="space-y-3 rounded-xl border border-border/60 bg-background/50 px-5 py-4"
                    data-testid="chat-answer-skeleton"
                  >
                    <Skeleton className="h-3 w-full" />
                    <Skeleton className="h-3 w-11/12" />
                    <Skeleton className="h-3 w-3/4" />
                  </div>
                )}

                {/* Strict mode buffers rendering until `done` decides between
                    the answer and a refusal. */}
                {pending && stream.strict && (
                  <div
                    className="flex items-center gap-3 rounded-xl border border-border/60 bg-background/50 px-5 py-4 text-sm text-muted-foreground"
                    data-testid="chat-verifying"
                  >
                    <Loader2
                      className="size-4 animate-spin text-[color:var(--brand)]"
                      aria-hidden="true"
                    />
                    Generating &amp; verifying answer…
                  </div>
                )}

                {/* Keep partial answer visible after a mid-stream error. */}
                {liveResponse &&
                  (pending || stream.status === "error") &&
                  !stream.strict && (
                    <Answer response={liveResponse} streaming={pending} />
                  )}
              </div>
            )}
          </div>
        )}

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
              onKeyDown={(e) => {
                // Enter sends; Shift+Enter inserts a newline.
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  e.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder="What does the document say about…? (Enter to send, Shift+Enter for a new line)"
              rows={3}
              className="w-full resize-none rounded-xl border border-input bg-background/50 px-4 py-3.5 pb-12 pr-14 text-sm leading-relaxed shadow-sm transition-colors placeholder:text-muted-foreground/70 focus-visible:border-[color:var(--brand)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--brand)]/30 sm:pr-36"
              required
            />
            <div className="absolute bottom-3 left-3 flex items-center gap-1.5">
              <ToggleChip
                pressed={useRag}
                onPressedChange={setUseRag}
                disabled={pending}
                title="Answer from your uploaded documents"
                data-testid="toggle-rag"
              >
                <Database className="size-3" aria-hidden="true" />
                RAG
              </ToggleChip>
              <ToggleChip
                pressed={useWeb}
                onPressedChange={setUseWeb}
                disabled={pending}
                title="Augment with fresh web search results"
                data-testid="toggle-web"
              >
                <Globe className="size-3" aria-hidden="true" />
                Web
              </ToggleChip>
            </div>
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
      </CardContent>
    </Card>
  );
}

function QuestionBubble({ question }: { question: string }) {
  return (
    <div className="flex justify-end" data-testid="chat-question">
      <p className="max-w-[85%] whitespace-pre-wrap rounded-xl rounded-br-sm bg-[color:var(--brand)]/10 px-4 py-2.5 text-sm leading-relaxed">
        {question}
      </p>
    </div>
  );
}

function streamToResponse(stream: StreamState): ChatResponse | null {
  if (!stream.meta && stream.text === "" && stream.status !== "done") return null;
  const meta = stream.meta;
  return {
    answer: stream.strictRefusal ?? stream.text,
    citations: meta?.citations ?? [],
    entities_used: meta?.entities_used ?? [],
    model: meta?.model ?? "",
    used_context: meta?.used_context ?? false,
    used_graph: meta?.used_graph ?? false,
    used_web: meta?.used_web ?? false,
    web_citations: meta?.web_citations ?? [],
    verification: stream.verification ?? undefined,
    strict_refusal: stream.strictRefusal != null,
    intent: meta?.intent,
  };
}
