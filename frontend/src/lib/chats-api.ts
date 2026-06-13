import { API_BASE_URL, ApiError, apiFetch } from "@/lib/api";
import type { ChatCitation, ChatVerification, WebCitation } from "@/lib/chat-api";

export type ChatListItem = {
  id: string;
  title: string;
  summary: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
};

export type ChatListResponse = {
  items: ChatListItem[];
  total: number;
};

export type ChatMessageItem = {
  id: string;
  seq: number;
  role: "user" | "assistant" | string;
  content: string;
  created_at: string;
  citations: ChatCitation[];
  web_citations: WebCitation[];
  verification: ChatVerification | null;
  response_meta: {
    model?: string;
    intent?: string;
    used_context?: boolean;
    used_graph?: boolean;
    used_web?: boolean;
    strict_refusal?: boolean;
    entities_used?: unknown[];
  } | null;
};

export type ChatDetail = {
  id: string;
  title: string;
  summary: string | null;
  created_at: string;
  updated_at: string;
  messages: ChatMessageItem[];
};

export type ChatSearchItem = ChatListItem & {
  snippet: string;
  match_source: "title" | "summary" | "message";
};

export type ChatSearchResponse = {
  items: ChatSearchItem[];
  total: number;
  query: string;
};

export function listChats(token: string): Promise<ChatListResponse> {
  return apiFetch<ChatListResponse>("/api/v1/chats", { token });
}

export function getChat(token: string, id: string): Promise<ChatDetail> {
  return apiFetch<ChatDetail>(`/api/v1/chats/${id}`, { token });
}

export function renameChat(
  token: string,
  id: string,
  title: string,
): Promise<ChatListItem> {
  return apiFetch<ChatListItem>(`/api/v1/chats/${id}`, {
    token,
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function searchChats(
  token: string,
  q: string,
): Promise<ChatSearchResponse> {
  return apiFetch<ChatSearchResponse>(
    `/api/v1/chats/search?q=${encodeURIComponent(q)}`,
    { token },
  );
}

export async function deleteChat(token: string, id: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/chats/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok && response.status !== 204) {
    const text = await response.text();
    let body: unknown = text;
    try {
      body = JSON.parse(text);
    } catch {
      // body stays as raw text
    }
    throw new ApiError(
      `Delete failed: ${response.status} ${response.statusText}`,
      response.status,
      body,
    );
  }
}
