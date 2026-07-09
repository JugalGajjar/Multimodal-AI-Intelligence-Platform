"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import {
  listDocuments,
  type DocumentItem,
  type DocumentStatus,
} from "@/lib/documents-api";
import { useAuthStore } from "@/store/auth";

const TOAST_DURATION_MS = 5000;

function pollIntervalMs(items: DocumentItem[] | undefined): number | false {
  if (!items) return false;
  if (items.some((d) => d.status === "uploaded" || d.status === "processing")) {
    return 1500;
  }
  const waitingForSummary = items.some(
    (d) => d.status === "processed" && !d.summary,
  );
  return waitingForSummary ? 2500 : false;
}

/** Polls /documents in the background and fires a toast whenever any document
 *  transitions status (uploaded → processing → processed/failed). Meant to be
 *  mounted once from the AppShell so the same notifications follow the user
 *  across dashboard / documents / graph pages. */
export function useDocumentStatusToasts() {
  const token = useAuthStore((s) => s.token);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const prevByIdRef = useRef<Map<string, DocumentStatus>>(new Map());

  const { data } = useQuery({
    queryKey: ["documents"],
    queryFn: () => listDocuments(token!),
    enabled: isAuthenticated && !!token,
    refetchInterval: (query) => pollIntervalMs(query.state.data?.items),
  });

  useEffect(() => {
    if (!data?.items) return;

    const prev = prevByIdRef.current;
    const next = new Map<string, DocumentStatus>();

    for (const doc of data.items) {
      const before = prev.get(doc.id);
      next.set(doc.id, doc.status);

      if (!before || before === doc.status) continue;

      // uploaded → processing: worker has picked it up.
      if (before === "uploaded" && doc.status === "processing") {
        toast.info(doc.filename, {
          description:
            "Generating document insights and adding to knowledge graph.",
          duration: TOAST_DURATION_MS,
        });
      } else if (doc.status === "processed") {
        toast.success(doc.filename, {
          description: "Ready. You can now chat about this document.",
          duration: TOAST_DURATION_MS,
        });
      } else if (doc.status === "failed") {
        toast.error(doc.filename, {
          description:
            doc.error_message ||
            "Processing failed. Try re-uploading or check the format.",
          duration: TOAST_DURATION_MS,
        });
      }
    }

    prevByIdRef.current = next;
  }, [data]);
}
