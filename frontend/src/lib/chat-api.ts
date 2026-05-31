import { apiFetch } from "@/lib/api";

export type ChatCitation = {
  chunk_id: string;
  document_id: string;
  chunk_index: number;
  score: number;
  text_preview: string;
};

export type ChatGraphRelationEdge = {
  relation: string;
  direction?: "in" | "out" | string;
  other: string;
  other_type?: string;
  other_description?: string;
  distance?: number;
  relation_chain?: string[];
};

export type ChatEntityUsed = {
  name: string;
  type: string;
  description: string;
  relations: ChatGraphRelationEdge[];
};

export type ChatResponse = {
  answer: string;
  citations: ChatCitation[];
  entities_used: ChatEntityUsed[];
  model: string;
  used_context: boolean;
  used_graph: boolean;
};

export type ChatRequest = {
  query: string;
  top_k?: number;
  document_ids?: string[];
};

export function sendChatQuery(
  token: string,
  request: ChatRequest,
): Promise<ChatResponse> {
  return apiFetch<ChatResponse>("/api/v1/chat", {
    token,
    method: "POST",
    body: JSON.stringify(request),
  });
}
