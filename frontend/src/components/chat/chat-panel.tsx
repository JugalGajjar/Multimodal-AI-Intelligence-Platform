"use client";

import {
  Database,
  Globe,
  Loader2,
  MessageSquareText,
  Plus,
  SendHorizontal,
  Square,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Answer } from "@/components/chat/answer";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
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
const TEXTAREA_MAX_LINES = 5;

export function ChatPanel() {
  const token = useAuthStore((s) => s.token);
  const chatId = useChatSessionStore((s) => s.chatId);
  const turns = useChatSessionStore((s) => s.turns);
  const useRag = useChatSessionStore((s) => s.useRag);
  const useWeb = useChatSessionStore((s) => s.useWeb);
  const setChatId = useChatSessionStore((s) => s.setChatId);
  const addTurn = useChatSessionStore((s) => s.addTurn);
  const setUseRag = useChatSessionStore((s) => s.setUseRag);
  const setUseWeb = useChatSessionStore((s) => s.setUseWeb);
  const resetSession = useChatSessionStore((s) => s.reset);

  const [query, setQuery] = useState("");
  const [currentQuestion, setCurrentQuestion] = useState("");
  const [stream, setStream] = useState<StreamState>(INITIAL_STREAM);
  const pending = stream.status === "streaming";

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const nearBottomRef = useRef(true);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const resizeTextarea = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const cs = getComputedStyle(el);
    const lineHeight = parseFloat(cs.lineHeight) || 20;
    const padY = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const max = lineHeight * TEXTAREA_MAX_LINES + padY;
    el.style.height = `${Math.min(el.scrollHeight, max)}px`;
  }, []);

  // Re-fit whenever the value changes (covers programmatic resets too).
  useEffect(() => {
    resizeTextarea();
  }, [query, resizeTextarea]);

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

  function onStop() {
    // Aborting the fetch throws inside streamChatQuery; the AbortError branch
    // in onSubmit's catch clears the in-flight stream and restores the query.
    abortRef.current?.abort();
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

    const controller = new AbortController();
    abortRef.current = controller;

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
            // Move the turn into the thread immediately — the backend keeps
            // the body open while it runs post-done persistence + summary
            // (Groq), which can take 20-30s.
            const response = streamToResponse(acc);
            if (response) {
              addTurn(question, response);
              setStream(INITIAL_STREAM);
              setCurrentQuestion("");
            } else {
              sync();
            }
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
        controller.signal,
      );
      // Stream ended without `done` — finalize whatever we got.
      if (acc.status === "streaming") {
        acc.status = "done";
        const response = streamToResponse(acc);
        if (response) {
          addTurn(question, response);
          setStream(INITIAL_STREAM);
          setCurrentQuestion("");
        }
      } else if (acc.status === "error") {
        // Restore the question so the user can retry — backend persists nothing.
        setQuery(question);
      }
    } catch (err) {
      // User clicked stop: soft cancel — drop the in-flight turn, restore the
      // question so they can edit + retry, and if this was the first turn drop
      // the chat_id (server won't have persisted the row).
      if (err instanceof DOMException && err.name === "AbortError") {
        setStream(INITIAL_STREAM);
        setCurrentQuestion("");
        setQuery(question);
        if (useChatSessionStore.getState().turns.length === 0) {
          resetSession();
        }
      } else {
        acc.status = "error";
        acc.error = err;
        sync();
        setQuery(question);
      }
    } finally {
      abortRef.current = null;
    }
  }

  const liveResponse = streamToResponse(stream);
  const hasThread = turns.length > 0 || pending || stream.status === "error";

  return (
    <Card className="glass flex w-full flex-col py-6">
      <CardHeader className="px-4 pb-2 sm:px-6">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <MessageSquareText
              className="size-4 text-[color:var(--brand)]"
              aria-hidden="true"
            />
            Current chat
          </CardTitle>
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

        <form onSubmit={onSubmit}>
          <Label htmlFor="chat-query" className="sr-only">
            Question
          </Label>
          <div className="rounded-xl border border-input bg-background/50 shadow-sm transition-colors focus-within:border-[color:var(--brand)] focus-within:ring-2 focus-within:ring-[color:var(--brand)]/30">
            <textarea
              ref={textareaRef}
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
              placeholder="Ask anything. Enter to send, Shift+Enter for a new line."
              rows={1}
              className="block w-full resize-none overflow-y-auto rounded-t-xl border-0 bg-transparent px-4 py-3 text-sm leading-relaxed placeholder:text-muted-foreground/70 focus:outline-none"
              required
            />
            <div className="flex items-center justify-between gap-2 border-t border-border/40 px-2.5 py-2">
              <div className="flex items-center gap-1.5">
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
                type={pending ? "button" : "submit"}
                onClick={pending ? onStop : undefined}
                disabled={!pending && !query.trim()}
                aria-label={pending ? "Stop" : "Send"}
                className="bg-gradient-brand text-brand-foreground glow-brand px-3 sm:px-4"
                size="sm"
              >
                {pending ? (
                  <>
                    <Square
                      className="size-3.5 fill-current"
                      aria-hidden="true"
                    />
                    <span className="hidden sm:inline">Stop</span>
                  </>
                ) : (
                  <>
                    <SendHorizontal className="size-3.5" aria-hidden="true" />
                    <span className="hidden sm:inline">Send</span>
                  </>
                )}
              </Button>
            </div>
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
