import { apiFetch } from "@/lib/api";

export type RagMode = "strict" | "regular";

export type ChatSettings = {
  rag_mode: RagMode;
  web_max_results: number;
  /** null = follow the server default. Otherwise a curated model id
   *  (see fetchChatModels). */
  chat_model: string | null;
};

export type ChatModelChoice = {
  id: string;
  label: string;
  provider: string;
  category: "open-source";
  notes: string;
  is_default: boolean;
};

export type ChatModelsResponse = {
  default: string;
  models: ChatModelChoice[];
};

export function fetchChatSettings(token: string): Promise<ChatSettings> {
  return apiFetch<ChatSettings>("/api/v1/auth/settings", { token });
}

export function fetchChatModels(token: string): Promise<ChatModelsResponse> {
  return apiFetch<ChatModelsResponse>("/api/v1/chat/models", { token });
}

export function updateChatSettings(
  token: string,
  patch: Partial<ChatSettings>,
): Promise<ChatSettings> {
  return apiFetch<ChatSettings>("/api/v1/auth/settings", {
    token,
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}
