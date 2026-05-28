"use client";

import dynamic from "next/dynamic";
import { useMemo, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { colorForEntityType, ENTITY_TYPE_LEGEND } from "./entity-colors";
import type { GraphLinkData, GraphNodeData } from "@/lib/graph-api";

// `react-force-graph-2d` draws to canvas and requires `window` — exclude it
// from server rendering. Keep this *outside* the component body so the dynamic
// import is only resolved once per module load, not per render.
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => (
    <div
      role="status"
      aria-label="loading graph"
      className="flex h-full w-full items-center justify-center text-xs text-muted-foreground"
    >
      Loading graph…
    </div>
  ),
});

type ForceNode = GraphNodeData & {
  color: string;
  highlighted: boolean;
};

type ForceLink = GraphLinkData & { id: string };

export type KnowledgeGraphProps = {
  nodes: GraphNodeData[];
  links: GraphLinkData[];
  width?: number;
  height?: number;
  highlighted?: ReadonlySet<string>;
  onNodeClick?: (node: GraphNodeData) => void;
  showLegend?: boolean;
};

export function KnowledgeGraph({
  nodes,
  links,
  width,
  height = 360,
  highlighted,
  onNodeClick,
  showLegend = true,
}: KnowledgeGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const graphData = useMemo(() => {
    const enrichedNodes: ForceNode[] = nodes.map((n) => ({
      ...n,
      color: colorForEntityType(n.type),
      highlighted: highlighted?.has(n.id) ?? false,
    }));
    const enrichedLinks: ForceLink[] = links.map((l, i) => ({
      ...l,
      id: `${l.source}|${l.relation}|${l.target}|${i}`,
    }));
    return { nodes: enrichedNodes, links: enrichedLinks };
  }, [nodes, links, highlighted]);

  if (nodes.length === 0) {
    return (
      <div
        data-testid="kg-empty"
        className="flex h-40 w-full items-center justify-center rounded-md border border-dashed text-xs text-muted-foreground"
      >
        No entities to graph yet — upload a document to populate the
        knowledge graph.
      </div>
    );
  }

  const usedTypes = new Set(nodes.map((n) => n.type));

  return (
    <div className="flex w-full flex-col gap-2" data-testid="knowledge-graph">
      <div
        ref={containerRef}
        className="overflow-hidden rounded-md border bg-background"
        style={{ height }}
      >
        <ForceGraph2D
          graphData={graphData}
          width={width}
          height={height}
          backgroundColor="transparent"
          nodeLabel={(n) => {
            const node = n as unknown as ForceNode;
            return node.description
              ? `${node.name} — ${node.description}`
              : node.name;
          }}
          nodeColor={(n) => (n as unknown as ForceNode).color}
          nodeVal={(n) => ((n as unknown as ForceNode).highlighted ? 8 : 3)}
          nodeRelSize={6}
          linkLabel={(l) => (l as unknown as ForceLink).relation}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={0.95}
          linkColor={() => "#94a3b8"}
          linkWidth={(l) => {
            const link = l as unknown as ForceLink;
            const src =
              typeof link.source === "string" ? link.source : (link.source as ForceNode)?.id;
            const tgt =
              typeof link.target === "string" ? link.target : (link.target as ForceNode)?.id;
            const both =
              !!highlighted && highlighted.has(src) && highlighted.has(tgt);
            return both ? 2 : 1;
          }}
          onNodeClick={(n) =>
            onNodeClick?.({
              id: (n as unknown as ForceNode).id,
              name: (n as unknown as ForceNode).name,
              type: (n as unknown as ForceNode).type,
              description: (n as unknown as ForceNode).description,
              document_ids: (n as unknown as ForceNode).document_ids,
            })
          }
          cooldownTicks={120}
        />
      </div>

      {showLegend && (
        <div
          className="flex flex-wrap gap-1.5 text-xs"
          data-testid="kg-legend"
        >
          {ENTITY_TYPE_LEGEND.filter((entry) => usedTypes.has(entry.type)).map(
            (entry) => (
              <Badge
                key={entry.type}
                variant="outline"
                className="gap-1.5"
              >
                <span
                  aria-hidden="true"
                  className="inline-block size-2 rounded-full"
                  style={{ backgroundColor: entry.color }}
                />
                {entry.type}
              </Badge>
            ),
          )}
        </div>
      )}
    </div>
  );
}
