import { apiFetch } from "@/lib/api";

export type RagMode = "strict" | "regular";

export type ChatSettings = {
  rag_mode: RagMode;
  web_max_results: number;
};

export function fetchChatSettings(token: string): Promise<ChatSettings> {
  return apiFetch<ChatSettings>("/api/v1/auth/settings", { token });
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
