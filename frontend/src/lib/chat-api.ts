import { API_BASE_URL, ApiError, apiFetch } from "@/lib/api";

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

export type VerificationVerdict =
  | "verified"
  | "partial"
  | "unsupported"
  | "skipped";

export type ChatVerification = {
  verdict: VerificationVerdict;
  groundedness_score: number;
  total_claims: number;
  supported_claims: number;
  unsupported_claims: string[];
  skip_reason: string;
};

export type ChatIntent = "chat" | "summarize" | "explain_graph";

export type WebCitation = {
  url: string;
  title: string;
  snippet: string;
  score: number;
};

export type ChatResponse = {
  answer: string;
  citations: ChatCitation[];
  entities_used: ChatEntityUsed[];
  model: string;
  used_context: boolean;
  used_graph: boolean;
  used_web?: boolean;
  web_citations?: WebCitation[];
  verification?: ChatVerification;
  strict_refusal?: boolean;
  intent?: ChatIntent | string;
};

export type ChatRequest = {
  query: string;
  top_k?: number;
  document_ids?: string[];
  use_rag?: boolean;
  use_web?: boolean;
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

export type ChatStreamMeta = {
  intent: ChatIntent | string;
  used_context: boolean;
  used_graph: boolean;
  used_web: boolean;
  model: string;
  citations: ChatCitation[];
  entities_used: ChatEntityUsed[];
  web_citations: WebCitation[];
  // True when strict mode applies to this turn — the client buffers
  // rendering until `done` decides between the answer and a refusal.
  strict: boolean;
};

export type ChatStreamDone = {
  verification: ChatVerification;
  strict_refusal: string | null;
};

export type ChatStreamHandlers = {
  onMeta?: (meta: ChatStreamMeta) => void;
  onToken?: (text: string) => void;
  onDone?: (done: ChatStreamDone) => void;
  onError?: (error: { status: number; detail: string }) => void;
};

// Parse a single SSE block — one `event:` line followed by one or more
// `data:` lines, terminated by a blank line.
function parseSseBlock(block: string): { event: string; data: string } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // SSE comment
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}

export async function streamChatQuery(
  token: string,
  request: ChatRequest,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok || !response.body) {
    const text = await response.text();
    let body: unknown = text;
    try {
      body = JSON.parse(text);
    } catch {
      // body stays as raw text
    }
    throw new ApiError(
      `Stream failed: ${response.status} ${response.statusText}`,
      response.status,
      body,
    );
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseBlock(block);
      if (parsed) {
        try {
          const data = JSON.parse(parsed.data);
          if (parsed.event === "meta") handlers.onMeta?.(data as ChatStreamMeta);
          else if (parsed.event === "token") handlers.onToken?.(data.text);
          else if (parsed.event === "done") handlers.onDone?.(data as ChatStreamDone);
          else if (parsed.event === "error") handlers.onError?.(data);
        } catch {
          // Skip malformed blocks.
        }
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}
