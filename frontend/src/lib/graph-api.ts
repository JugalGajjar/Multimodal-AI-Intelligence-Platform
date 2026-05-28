import { apiFetch } from "@/lib/api";

export type GraphNodeData = {
  id: string;
  name: string;
  type: string;
  description: string;
  document_ids: string[];
};

export type GraphLinkData = {
  source: string;
  target: string;
  relation: string;
};

export type GraphSnapshotResponse = {
  nodes: GraphNodeData[];
  links: GraphLinkData[];
  node_count: number;
  link_count: number;
};

export function fetchGraphSnapshot(
  token: string,
  opts: { limit_nodes?: number; limit_links?: number } = {},
): Promise<GraphSnapshotResponse> {
  const params = new URLSearchParams();
  if (opts.limit_nodes != null)
    params.set("limit_nodes", String(opts.limit_nodes));
  if (opts.limit_links != null)
    params.set("limit_links", String(opts.limit_links));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<GraphSnapshotResponse>(`/api/v1/graph/snapshot${qs}`, {
    token,
  });
}
