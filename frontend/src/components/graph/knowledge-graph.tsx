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
  // Force-graph mutates these in place during simulation.
  x?: number;
  y?: number;
};

type ForceLink = GraphLinkData & {
  id: string;
  // After the simulation runs, source/target are mutated to node references.
  source: string | ForceNode;
  target: string | ForceNode;
};

export type KnowledgeGraphProps = {
  nodes: GraphNodeData[];
  links: GraphLinkData[];
  width?: number;
  height?: number;
  highlighted?: ReadonlySet<string>;
  onNodeClick?: (node: GraphNodeData) => void;
  showLegend?: boolean;
};

// Tuned for legibility on dense graphs: smaller default nodes with a slightly
// bigger ring around highlighted ones, and labels that scale with zoom so they
// don't pile up at fit-to-screen.
const BASE_RADIUS = 4;
const HIGHLIGHT_RADIUS = 6;
const LABEL_BASE_SIZE_PX = 11;
const LINK_LABEL_BASE_SIZE_PX = 9;
// Below this canvas zoom level we hide labels to keep dense graphs readable
// when fully zoomed out.
const LABEL_MIN_SCALE = 1.1;

function labelColors(): { fill: string; stroke: string } {
  if (typeof document === "undefined") {
    return { fill: "#0f172a", stroke: "rgba(255,255,255,0.85)" };
  }
  const isDark = document.documentElement.classList.contains("dark");
  return isDark
    ? { fill: "#e2e8f0", stroke: "rgba(15,23,42,0.85)" }
    : { fill: "#0f172a", stroke: "rgba(255,255,255,0.9)" };
}

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
          // We do the painting ourselves (circle + label). `replace` mode means
          // force-graph won't draw the default circle on top of ours.
          nodeCanvasObjectMode={() => "replace"}
          nodeCanvasObject={(rawNode, ctx, globalScale) => {
            const node = rawNode as unknown as ForceNode;
            if (typeof node.x !== "number" || typeof node.y !== "number") return;

            const radius = node.highlighted ? HIGHLIGHT_RADIUS : BASE_RADIUS;

            // Circle fill
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
            ctx.fillStyle = node.color;
            ctx.fill();

            // Highlighted ring
            if (node.highlighted) {
              ctx.lineWidth = 1.5 / globalScale;
              ctx.strokeStyle = node.color;
              ctx.globalAlpha = 0.35;
              ctx.beginPath();
              ctx.arc(node.x, node.y, radius + 3, 0, 2 * Math.PI, false);
              ctx.stroke();
              ctx.globalAlpha = 1;
            }

            // Label — always shown when highlighted; otherwise gated by zoom
            // so dense graphs stay legible at fit-to-screen.
            if (!node.highlighted && globalScale < LABEL_MIN_SCALE) return;

            const fontSize = LABEL_BASE_SIZE_PX / globalScale;
            ctx.font = `${
              node.highlighted ? "600 " : ""
            }${fontSize}px ui-sans-serif, system-ui, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            const { fill, stroke } = labelColors();
            // Stroke first as an outline for legibility over edges/other nodes.
            ctx.lineWidth = 3 / globalScale;
            ctx.strokeStyle = stroke;
            ctx.strokeText(node.name, node.x, node.y + radius + 2);
            ctx.fillStyle = fill;
            ctx.fillText(node.name, node.x, node.y + radius + 2);
          }}
          // Keep the default pointer hit area roughly the same as the visible
          // circle so clicks still register on the small nodes.
          nodePointerAreaPaint={(rawNode, color, ctx) => {
            const node = rawNode as unknown as ForceNode;
            if (typeof node.x !== "number" || typeof node.y !== "number") return;
            const radius = node.highlighted ? HIGHLIGHT_RADIUS : BASE_RADIUS;
            ctx.fillStyle = color;
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius + 4, 0, 2 * Math.PI, false);
            ctx.fill();
          }}
          linkLabel={(l) => (l as unknown as ForceLink).relation}
          linkColor={() => "#94a3b8"}
          linkWidth={(l) => {
            const link = l as unknown as ForceLink;
            const src =
              typeof link.source === "string"
                ? link.source
                : (link.source as ForceNode)?.id;
            const tgt =
              typeof link.target === "string"
                ? link.target
                : (link.target as ForceNode)?.id;
            const both =
              !!highlighted && highlighted.has(src) && highlighted.has(tgt);
            return both ? 1.6 : 0.8;
          }}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={0.92}
          // Draw the relation label centered on the edge, AFTER the link line
          // so the label sits on top.
          linkCanvasObjectMode={() => "after"}
          linkCanvasObject={(rawLink, ctx, globalScale) => {
            if (globalScale < LABEL_MIN_SCALE) return;
            const link = rawLink as unknown as ForceLink;
            const src = link.source as ForceNode;
            const tgt = link.target as ForceNode;
            if (
              !src ||
              !tgt ||
              typeof src.x !== "number" ||
              typeof src.y !== "number" ||
              typeof tgt.x !== "number" ||
              typeof tgt.y !== "number"
            ) {
              return;
            }
            const midX = (src.x + tgt.x) / 2;
            const midY = (src.y + tgt.y) / 2;
            const label = link.relation;
            if (!label) return;
            const fontSize = LINK_LABEL_BASE_SIZE_PX / globalScale;
            ctx.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            const { fill, stroke } = labelColors();
            ctx.lineWidth = 3 / globalScale;
            ctx.strokeStyle = stroke;
            ctx.strokeText(label, midX, midY);
            ctx.fillStyle = fill;
            ctx.globalAlpha = 0.85;
            ctx.fillText(label, midX, midY);
            ctx.globalAlpha = 1;
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
          <Badge
            variant="outline"
            className="ml-auto text-muted-foreground"
            title="Labels appear when zoomed in or for highlighted nodes"
          >
            zoom to reveal labels
          </Badge>
        </div>
      )}
    </div>
  );
}
