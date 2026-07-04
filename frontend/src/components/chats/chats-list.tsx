"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  ChevronUp,
  History,
  MessageSquareText,
  Pencil,
  Play,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Answer } from "@/components/chat/answer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { ChatResponse } from "@/lib/chat-api";
import {
  deleteChat,
  getChat,
  listChats,
  renameChat,
  searchChats,
  type ChatDetail,
  type ChatListItem,
  type ChatMessageItem,
  type ChatSearchItem,
} from "@/lib/chats-api";
import { useAuthStore } from "@/store/auth";
import { useChatSessionStore } from "@/store/chat-session";

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function ChatsList() {
  const token = useAuthStore((s) => s.token);
  const queryClient = useQueryClient();
  const router = useRouter();
  const hydrateFromChat = useChatSessionStore((s) => s.hydrateFromChat);
  const [search, setSearch] = useState("");
  const debouncedQ = useDebounced(search.trim(), 300);
  const [openId, setOpenId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [continuingId, setContinuingId] = useState<string | null>(null);

  const searching = debouncedQ.length > 0;
  const { data, isLoading, isError } = useQuery({
    queryKey: searching ? ["chats", "search", debouncedQ] : ["chats"],
    queryFn: () =>
      searching ? searchChats(token!, debouncedQ) : listChats(token!),
    enabled: !!token,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteChat(token!, id),
    onSuccess: () => {
      toast.success("Chat deleted.");
      queryClient.invalidateQueries({ queryKey: ["chats"] });
    },
    onError: (err: unknown) =>
      toast.error(err instanceof Error ? err.message : "Delete failed."),
  });

  const continueMutation = useMutation({
    mutationFn: async (id: string): Promise<ChatDetail> => {
      setContinuingId(id);
      // Reuse the transcript cache when the row is expanded; otherwise fetch.
      return queryClient.fetchQuery({
        queryKey: ["chat", id],
        queryFn: () => getChat(token!, id),
      });
    },
    onSuccess: (detail) => {
      hydrateFromChat(detail.id, messagesToTurns(detail.messages));
      router.push("/dashboard");
    },
    onError: (err: unknown) =>
      toast.error(err instanceof Error ? err.message : "Could not load chat."),
    onSettled: () => setContinuingId(null),
  });

  const items = data?.items ?? [];

  return (
    <Card className="glass w-full py-6">
      <CardHeader className="px-4 pb-2 sm:px-6">
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="size-4 text-[color:var(--brand)]" aria-hidden="true" />
          Saved chats
        </CardTitle>
        <CardDescription>
          {data ? `${data.total} chat${data.total === 1 ? "" : "s"}` : "Loading…"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 px-4 pt-2 sm:px-6">
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search titles, summaries, and messages…"
            aria-label="Search chats"
            className="pl-9"
            data-testid="chats-search"
          />
        </div>

        {isLoading && (
          <ul className="space-y-3" data-testid="chats-skeleton">
            {[0, 1, 2].map((i) => (
              <li key={i}>
                <Skeleton className="h-16 w-full" />
              </li>
            ))}
          </ul>
        )}

        {isError && (
          <p className="text-sm text-destructive">Could not load chats.</p>
        )}

        {data && items.length === 0 && (
          <div
            className="rounded-xl border border-dashed border-border/70 bg-background/30 px-5 py-6 text-center"
            data-testid="chats-empty"
          >
            <MessageSquareText
              className="mx-auto size-6 text-muted-foreground/70"
              aria-hidden="true"
            />
            <p className="mt-2 text-xs text-muted-foreground">
              {searching
                ? "No chats match your search."
                : "No chats yet. Ask a question on the dashboard to start one."}
            </p>
          </div>
        )}

        {items.length > 0 && (
          <ul className="space-y-3" data-testid="chats-scroll">
            {items.map((chat) => (
              <ChatRow
                key={chat.id}
                chat={chat}
                open={openId === chat.id}
                renaming={renamingId === chat.id}
                continuing={continuingId === chat.id}
                onToggleOpen={() =>
                  setOpenId((id) => (id === chat.id ? null : chat.id))
                }
                onStartRename={() => setRenamingId(chat.id)}
                onEndRename={() => setRenamingId(null)}
                onDelete={() => deleteMutation.mutate(chat.id)}
                onContinue={() => continueMutation.mutate(chat.id)}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function ChatRow({
  chat,
  open,
  renaming,
  continuing,
  onToggleOpen,
  onStartRename,
  onEndRename,
  onDelete,
  onContinue,
}: {
  chat: ChatListItem | ChatSearchItem;
  open: boolean;
  renaming: boolean;
  continuing: boolean;
  onToggleOpen: () => void;
  onStartRename: () => void;
  onEndRename: () => void;
  onDelete: () => void;
  onContinue: () => void;
}) {
  const snippet = "snippet" in chat ? chat : null;

  return (
    <li
      className="rounded-xl border border-border/60 bg-background/40 p-3 transition-colors hover:bg-background/70 sm:p-4"
      data-testid="chat-row"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-4">
        <div className="min-w-0 flex-1">
          {renaming ? (
            <RenameForm chat={chat} onDone={onEndRename} />
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <p className="min-w-0 truncate text-sm font-medium" data-testid="chat-title">
                {chat.title}
              </p>
              <Badge variant="outline" className="shrink-0 text-[10px]">
                {chat.message_count} message{chat.message_count === 1 ? "" : "s"}
              </Badge>
              {snippet && (
                <Badge variant="ghost" className="shrink-0 text-[10px] text-muted-foreground">
                  matched {snippet.match_source}
                </Badge>
              )}
            </div>
          )}
          {chat.summary && !renaming && (
            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
              {chat.summary}
            </p>
          )}
          {snippet && (
            <p
              className="mt-1.5 rounded-md bg-[color:var(--brand)]/5 px-2 py-1 text-xs text-foreground/80"
              data-testid="chat-snippet"
            >
              {snippet.snippet}
            </p>
          )}
          <p className="mt-1 text-[11px] text-muted-foreground">
            {formatDate(chat.updated_at)}
          </p>
        </div>
        <div className="-ml-1 flex shrink-0 flex-wrap items-center gap-1 sm:ml-auto">
          <Button
            variant="ghost"
            size="sm"
            onClick={onContinue}
            disabled={continuing}
            title="Continue this chat on the dashboard"
            data-testid="chat-continue-button"
            className="gap-1"
          >
            <Play className="size-3.5" aria-hidden="true" />
            <span className="hidden sm:inline">
              {continuing ? "Loading…" : "Continue"}
            </span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleOpen}
            title={open ? "Hide transcript" : "View transcript"}
            className="gap-1"
          >
            {open ? (
              <ChevronUp className="size-3.5" aria-hidden="true" />
            ) : (
              <ChevronDown className="size-3.5" aria-hidden="true" />
            )}
            <span className="hidden sm:inline">
              {open ? "Hide" : "Transcript"}
            </span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onStartRename}
            disabled={renaming}
            title="Rename chat"
            aria-label="Rename chat"
            data-testid="chat-rename-button"
          >
            <Pencil className="size-3.5" aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onDelete}
            title="Delete chat"
            aria-label="Delete chat"
            data-testid="chat-delete-button"
            className="text-destructive hover:text-destructive"
          >
            <Trash2 className="size-3.5" aria-hidden="true" />
          </Button>
        </div>
      </div>

      {open && <Transcript chatId={chat.id} />}
    </li>
  );
}

function RenameForm({
  chat,
  onDone,
}: {
  chat: ChatListItem;
  onDone: () => void;
}) {
  const token = useAuthStore((s) => s.token);
  const queryClient = useQueryClient();
  const [title, setTitle] = useState(chat.title);

  const renameMutation = useMutation({
    mutationFn: () => renameChat(token!, chat.id, title.trim()),
    onSuccess: () => {
      toast.success("Chat renamed.");
      queryClient.invalidateQueries({ queryKey: ["chats"] });
      onDone();
    },
    onError: (err: unknown) =>
      toast.error(err instanceof Error ? err.message : "Rename failed."),
  });

  function submit() {
    if (title.trim() && title.trim() !== chat.title) {
      renameMutation.mutate();
    } else {
      onDone();
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <Input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            submit();
          } else if (e.key === "Escape") {
            onDone();
          }
        }}
        maxLength={200}
        autoFocus
        aria-label="Chat title"
        data-testid="chat-rename-input"
        className="h-8 text-sm"
      />
      <Button
        variant="ghost"
        size="sm"
        onClick={submit}
        disabled={renameMutation.isPending || !title.trim()}
        aria-label="Save title"
        data-testid="chat-rename-save"
      >
        <Check className="size-3.5" aria-hidden="true" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        onClick={onDone}
        aria-label="Cancel rename"
      >
        <X className="size-3.5" aria-hidden="true" />
      </Button>
    </div>
  );
}

/** Walk the seq-ordered message list and pair each user message with the
 *  assistant message immediately after it. Orphan messages (a user turn with
 *  no assistant reply yet, or an assistant reply without a preceding user)
 *  are skipped — they can't be represented as a ChatTurn. */
function messagesToTurns(
  messages: ChatMessageItem[],
): Array<{ question: string; response: ChatResponse }> {
  const turns: Array<{ question: string; response: ChatResponse }> = [];
  for (let i = 0; i < messages.length - 1; i += 1) {
    const user = messages[i];
    const assistant = messages[i + 1];
    if (user.role === "user" && assistant.role === "assistant") {
      turns.push({
        question: user.content,
        response: messageToResponse(assistant),
      });
      i += 1; // consumed the assistant reply too
    }
  }
  return turns;
}

function messageToResponse(m: ChatMessageItem): ChatResponse {
  const meta = m.response_meta ?? {};
  return {
    answer: m.content,
    citations: m.citations ?? [],
    entities_used: [],
    model: meta.model ?? "",
    used_context: meta.used_context ?? false,
    used_graph: false, // transcript view skips the inline graph
    used_web: meta.used_web ?? false,
    web_citations: m.web_citations ?? [],
    verification: m.verification ?? undefined,
    strict_refusal: meta.strict_refusal ?? false,
    intent: meta.intent,
  };
}

function Transcript({ chatId }: { chatId: string }) {
  const token = useAuthStore((s) => s.token);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["chat", chatId],
    queryFn: () => getChat(token!, chatId),
    enabled: !!token,
  });

  return (
    <div
      className="mt-4 space-y-5 rounded-lg border border-border/60 bg-muted/30 p-3 sm:p-4"
      data-testid="chat-transcript"
    >
      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-11/12" />
          <Skeleton className="h-3 w-3/4" />
        </div>
      )}
      {isError && (
        <p className="text-xs text-destructive">Failed to load transcript.</p>
      )}
      {data &&
        data.messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="flex justify-end">
              <p className="max-w-[85%] whitespace-pre-wrap rounded-xl rounded-br-sm bg-[color:var(--brand)]/10 px-4 py-2.5 text-sm leading-relaxed">
                {m.content}
              </p>
            </div>
          ) : (
            <Answer key={m.id} response={messageToResponse(m)} />
          ),
        )}
    </div>
  );
}
