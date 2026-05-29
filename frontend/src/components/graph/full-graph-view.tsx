"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";

import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  fetchGraphSnapshot,
  type GraphLinkData,
  type GraphNodeData,
  type GraphSnapshotResponse,
} from "@/lib/graph-api";
import { useAuthStore } from "@/store/auth";

import { colorForEntityType } from "./entity-colors";

type FilteredGraph = {
  nodes: GraphNodeData[];
  links: GraphLinkData[];
};

function filterBySearch(
  full: GraphSnapshotResponse,
  search: string,
): FilteredGraph {
  const needle = search.trim().toLowerCase();
  if (!needle) {
    return { nodes: full.nodes, links: full.links };
  }

  const directMatches = new Set(
    full.nodes
      .filter((n) => n.name.toLowerCase().includes(needle))
      .map((n) => n.id),
  );

  // Pull in immediate neighbours of matched nodes (one hop).
  const expanded = new Set(directMatches);
  for (const link of full.links) {
    if (directMatches.has(link.source)) expanded.add(link.target);
    if (directMatches.has(link.target)) expanded.add(link.source);
  }

  return {
    nodes: full.nodes.filter((n) => expanded.has(n.id)),
    links: full.links.filter(
      (l) => expanded.has(l.source) && expanded.has(l.target),
    ),
  };
}

function relationsForNode(nodeId: string, links: GraphLinkData[]) {
  const outgoing = links.filter((l) => l.source === nodeId);
  const incoming = links.filter((l) => l.target === nodeId);
  return { outgoing, incoming };
}

export function FullGraphView() {
  const token = useAuthStore((s) => s.token);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const query = useQuery<GraphSnapshotResponse>({
    queryKey: ["graph", "snapshot"],
    queryFn: () => fetchGraphSnapshot(token!, { limit_nodes: 500 }),
    enabled: !!token,
  });

  const data = query.data;
  const filtered = useMemo(
    () => (data ? filterBySearch(data, search) : { nodes: [], links: [] }),
    [data, search],
  );

  const selectedNode = useMemo(
    () =>
      selectedId
        ? (data?.nodes.find((n) => n.id === selectedId) ?? null)
        : null,
    [selectedId, data],
  );

  const selectedRelations = useMemo(
    () =>
      selectedNode && data
        ? relationsForNode(selectedNode.id, data.links)
        : { outgoing: [], incoming: [] },
    [selectedNode, data],
  );

  // Highlight the nodes matching the current search (the additional 1-hop
  // neighbours we pulled in for context don't get highlighted).
  const searchHighlighted = useMemo(() => {
    if (!data || !search.trim()) return new Set<string>();
    const needle = search.trim().toLowerCase();
    return new Set(
      data.nodes
        .filter((n) => n.name.toLowerCase().includes(needle))
        .map((n) => n.id),
    );
  }, [data, search]);

  return (
    <main className="flex flex-1 flex-col gap-4 px-6 py-8" data-testid="full-graph-view">
      <header className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">Knowledge graph</h1>
            <p className="text-sm text-muted-foreground">
              Everything the platform extracted from your uploads.
            </p>
          </div>
          <Link
            href="/dashboard"
            className={buttonVariants({ variant: "outline", size: "sm" })}
            data-testid="back-to-dashboard"
          >
            ← Dashboard
          </Link>
        </div>

        {data && (
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <Badge variant="secondary" data-testid="kg-node-count">
              {data.node_count} entities
            </Badge>
            <Badge variant="secondary" data-testid="kg-link-count">
              {data.link_count} relationships
            </Badge>
            {search && (
              <Badge variant="outline">
                showing {filtered.nodes.length} matching + 1-hop
              </Badge>
            )}
          </div>
        )}
      </header>

      <div className="grid w-full gap-4 lg:grid-cols-[1fr_320px]">
        <div className="flex flex-col gap-3">
          <div className="space-y-1">
            <Label htmlFor="kg-search">Filter by name</Label>
            <Input
              id="kg-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search entities by name…"
              data-testid="kg-search"
            />
          </div>

          {query.isLoading && (
            <p className="text-sm text-muted-foreground" data-testid="kg-loading">
              Loading graph…
            </p>
          )}
          {query.isError && (
            <p className="text-sm text-destructive" data-testid="kg-error">
              Failed to load graph.
            </p>
          )}
          {data && data.nodes.length === 0 && (
            <div
              className="flex h-64 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground"
              data-testid="kg-empty-full"
            >
              No entities yet — upload a document and the platform will
              extract them automatically.
            </div>
          )}
          {data && data.nodes.length > 0 && (
            <KnowledgeGraph
              nodes={filtered.nodes}
              links={filtered.links}
              height={560}
              highlighted={searchHighlighted}
              onNodeClick={(node) => setSelectedId(node.id)}
            />
          )}
        </div>

        <aside data-testid="kg-side-panel">
          {selectedNode ? (
            <SelectedNodePanel
              node={selectedNode}
              outgoing={selectedRelations.outgoing}
              incoming={selectedRelations.incoming}
              onClose={() => setSelectedId(null)}
            />
          ) : (
            <Card className="h-full">
              <CardHeader>
                <CardTitle className="text-base">Entity details</CardTitle>
                <CardDescription>
                  Click a node to see its description and relationships.
                </CardDescription>
              </CardHeader>
            </Card>
          )}
        </aside>
      </div>
    </main>
  );
}

function SelectedNodePanel({
  node,
  outgoing,
  incoming,
  onClose,
}: {
  node: GraphNodeData;
  outgoing: GraphLinkData[];
  incoming: GraphLinkData[];
  onClose: () => void;
}) {
  return (
    <Card data-testid="kg-selected">
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0">
        <div className="space-y-1">
          <CardTitle className="text-base break-all">{node.name}</CardTitle>
          <CardDescription className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="inline-block size-2 rounded-full"
              style={{ backgroundColor: colorForEntityType(node.type) }}
            />
            {node.type}
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClose}
          data-testid="kg-close-details"
          aria-label="Clear selection"
        >
          ×
        </Button>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        {node.description && (
          <p className="text-foreground">{node.description}</p>
        )}

        {outgoing.length > 0 && (
          <div className="space-y-1">
            <p className="text-muted-foreground uppercase">Outgoing</p>
            <ul className="space-y-1">
              {outgoing.map((l) => (
                <li
                  key={`${l.source}|${l.relation}|${l.target}`}
                  className="rounded-md border bg-muted/30 px-2 py-1"
                >
                  <span className="font-mono">{l.relation}</span>{" "}
                  <span className="text-muted-foreground">→</span>{" "}
                  <span>{l.target}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {incoming.length > 0 && (
          <div className="space-y-1">
            <p className="text-muted-foreground uppercase">Incoming</p>
            <ul className="space-y-1">
              {incoming.map((l) => (
                <li
                  key={`${l.source}|${l.relation}|${l.target}`}
                  className="rounded-md border bg-muted/30 px-2 py-1"
                >
                  <span>{l.source}</span>{" "}
                  <span className="text-muted-foreground">→</span>{" "}
                  <span className="font-mono">{l.relation}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {node.document_ids && node.document_ids.length > 0 && (
          <div className="space-y-1">
            <p className="text-muted-foreground uppercase">From documents</p>
            <ul className="space-y-1 font-mono">
              {node.document_ids.map((id) => (
                <li
                  key={id}
                  className="truncate rounded-md border bg-muted/30 px-2 py-1"
                  title={id}
                >
                  {id.slice(0, 8)}…
                </li>
              ))}
            </ul>
          </div>
        )}

        {outgoing.length === 0 &&
          incoming.length === 0 &&
          !node.description && (
            <p className="text-muted-foreground">No description or relations.</p>
          )}
      </CardContent>
    </Card>
  );
}
