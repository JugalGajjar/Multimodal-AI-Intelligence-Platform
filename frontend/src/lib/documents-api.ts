import { API_BASE_URL, ApiError, apiFetch } from "@/lib/api";

export type DocumentStatus =
  | "uploaded"
  | "processing"
  | "processed"
  | "failed";

export type DocumentItem = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  status: DocumentStatus;
  created_at: string;
  updated_at: string;
};

export type DocumentListResponse = {
  items: DocumentItem[];
  total: number;
};

export function listDocuments(token: string): Promise<DocumentListResponse> {
  return apiFetch<DocumentListResponse>("/api/v1/documents", { token });
}

export function getDocument(token: string, id: string): Promise<DocumentItem> {
  return apiFetch<DocumentItem>(`/api/v1/documents/${id}`, { token });
}

export type DocumentTextResponse = {
  id: string;
  status: DocumentStatus;
  extracted_text: string | null;
};

export function getDocumentText(
  token: string,
  id: string,
): Promise<DocumentTextResponse> {
  return apiFetch<DocumentTextResponse>(`/api/v1/documents/${id}/text`, {
    token,
  });
}

export async function uploadDocument(
  token: string,
  file: File,
): Promise<DocumentItem> {
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/v1/documents`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      // No Content-Type — the browser sets multipart boundary.
    },
    body: form,
  });

  if (!response.ok) {
    const text = await response.text();
    let body: unknown = text;
    try {
      body = JSON.parse(text);
    } catch {
      // raw text
    }
    throw new ApiError(
      `Upload failed: ${response.status} ${response.statusText}`,
      response.status,
      body,
    );
  }

  return (await response.json()) as DocumentItem;
}

export async function deleteDocument(
  token: string,
  id: string,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/documents/${id}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok && response.status !== 204) {
    throw new ApiError(
      `Delete failed: ${response.status} ${response.statusText}`,
      response.status,
      null,
    );
  }
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(2)} MB`;
}
