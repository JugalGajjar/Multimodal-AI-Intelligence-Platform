"use client";

import { useQuery } from "@tanstack/react-query";
import { Network, Search, Sparkles, X } from "lucide-react";
import { useMemo, useState } from "react";

import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
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

  // Pull in 1-hop neighbours of matched nodes.
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
    <div className="flex flex-col gap-6" data-testid="full-graph-view">
      <header className="flex flex-col gap-2">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Knowledge
        </p>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          <span className="text-gradient-brand">Knowledge graph</span>
        </h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Every entity and relationship the platform extracted from your
          uploads. Searchable, navigable, and tied back to source documents.
        </p>

        {data && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Badge
              variant="secondary"
              data-testid="kg-node-count"
              className="gap-1.5"
            >
              <Network className="size-3" aria-hidden="true" />
              {data.node_count} entities
            </Badge>
            <Badge
              variant="secondary"
              data-testid="kg-link-count"
              className="gap-1.5"
            >
              <Sparkles className="size-3" aria-hidden="true" />
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

      <div className="grid w-full gap-6 lg:grid-cols-[1fr_340px]">
        <Card className="glass overflow-hidden py-6">
          <CardHeader className="px-6 pb-3">
            <div className="space-y-2.5">
              <Label
                htmlFor="kg-search"
                className="text-xs uppercase text-muted-foreground"
              >
                Filter by name
              </Label>
              <div className="relative">
                <Search
                  className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                  aria-hidden="true"
                />
                <Input
                  id="kg-search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search entities by name…"
                  data-testid="kg-search"
                  className="h-11 pl-10 pr-4"
                />
              </div>
            </div>
          </CardHeader>
          <CardContent className="px-6">
            {query.isLoading && (
              <p
                className="py-10 text-center text-sm text-muted-foreground"
                data-testid="kg-loading"
              >
                Loading graph…
              </p>
            )}
            {query.isError && (
              <p
                className="py-10 text-center text-sm text-destructive"
                data-testid="kg-error"
              >
                Failed to load graph.
              </p>
            )}
            {data && data.nodes.length === 0 && (
              <EmptyGraphState />
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
          </CardContent>
        </Card>

        <aside data-testid="kg-side-panel">
          {selectedNode ? (
            <SelectedNodePanel
              node={selectedNode}
              outgoing={selectedRelations.outgoing}
              incoming={selectedRelations.incoming}
              onClose={() => setSelectedId(null)}
            />
          ) : (
            <Card className="glass h-full py-6">
              <CardHeader className="px-6">
                <CardTitle className="text-base">Entity details</CardTitle>
                <CardDescription className="mt-1">
                  Click a node to see its description and relationships.
                </CardDescription>
              </CardHeader>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}

function EmptyGraphState() {
  return (
    <div
      className="flex flex-col items-center justify-center gap-3 py-16 text-center"
      data-testid="kg-empty-full"
    >
      <span
        aria-hidden="true"
        className="grid size-14 place-items-center rounded-2xl bg-gradient-brand text-brand-foreground opacity-90 glow-brand"
      >
        <Network className="size-6" />
      </span>
      <p className="max-w-sm text-sm text-muted-foreground">
        No entities yet. Upload a document and the platform will extract them
        automatically. You can also click{" "}
        <span className="font-medium text-foreground">Re-index graph</span> on
        a processed document to retry extraction.
      </p>
    </div>
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
    <Card className="glass py-6" data-testid="kg-selected">
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0 px-6">
        <div className="space-y-1.5">
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
          <X className="size-4" aria-hidden="true" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-5 px-6 text-xs">
        {node.description && (
          <p className="text-foreground/90 leading-relaxed">{node.description}</p>
        )}

        {outgoing.length > 0 && (
          <RelationsBlock label="Outgoing" links={outgoing} side="from" />
        )}

        {incoming.length > 0 && (
          <RelationsBlock label="Incoming" links={incoming} side="to" />
        )}

        {node.document_ids && node.document_ids.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              From documents
            </p>
            <ul className="space-y-1 font-mono">
              {node.document_ids.map((id) => (
                <li
                  key={id}
                  className="truncate rounded-md border border-border/60 bg-muted/40 px-2 py-1"
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

function RelationsBlock({
  label,
  links,
  side,
}: {
  label: string;
  links: GraphLinkData[];
  side: "from" | "to";
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <ul className="space-y-1">
        {links.map((l) => (
          <li
            key={`${l.source}|${l.relation}|${l.target}`}
            className="rounded-md border border-border/60 bg-muted/40 px-2 py-1"
          >
            {side === "from" ? (
              <>
                <span className="font-mono text-[color:var(--brand)]">
                  {l.relation}
                </span>{" "}
                <span className="text-muted-foreground">→</span>{" "}
                <span>{l.target}</span>
              </>
            ) : (
              <>
                <span>{l.source}</span>{" "}
                <span className="text-muted-foreground">→</span>{" "}
                <span className="font-mono text-[color:var(--brand)]">
                  {l.relation}
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
