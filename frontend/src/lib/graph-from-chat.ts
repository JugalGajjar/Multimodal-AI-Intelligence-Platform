import type { ChatCitation, ChatResponse } from "@/lib/chat-api";
import type { GraphLinkData, GraphNodeData } from "@/lib/graph-api";

// Mirrors the snake_case shape FastAPI emits.
export type EntityUsed = {
  name: string;
  type: string;
  description: string;
  relations: Array<{
    relation: string;
    direction: "in" | "out" | string;
    other: string;
    other_type?: string;
    other_description?: string;
  }>;
};

export type ChatGraphData = {
  nodes: GraphNodeData[];
  links: GraphLinkData[];
};

// Adds each "other" endpoint as a node so edges never dangle, and dedupes
// links by `source|relation|target`.
export function buildChatGraph(
  entities: ReadonlyArray<EntityUsed>,
): ChatGraphData {
  const nodes: GraphNodeData[] = [];
  const seenNodes = new Map<string, GraphNodeData>();

  function pushNode(node: GraphNodeData) {
    const existing = seenNodes.get(node.id);
    if (existing) {
      // Prefer richer data when the same node turns up again.
      if (!existing.description && node.description)
        existing.description = node.description;
      if (existing.type === "Concept" && node.type !== "Concept")
        existing.type = node.type;
      return;
    }
    seenNodes.set(node.id, node);
    nodes.push(node);
  }

  // Primary entities first so they win the richer-data tie-break above.
  for (const e of entities) {
    pushNode({
      id: e.name,
      name: e.name,
      type: e.type || "Concept",
      description: e.description ?? "",
      document_ids: [],
    });
  }

  const links: GraphLinkData[] = [];
  const seenLinks = new Set<string>();

  for (const e of entities) {
    for (const rel of e.relations) {
      if (!rel.other) continue;

      pushNode({
        id: rel.other,
        name: rel.other,
        type: rel.other_type || "Concept",
        description: rel.other_description ?? "",
        document_ids: [],
      });

      const [source, target] =
        rel.direction === "in"
          ? [rel.other, e.name]
          : [e.name, rel.other];

      const key = `${source}|${rel.relation}|${target}`;
      if (seenLinks.has(key)) continue;
      seenLinks.add(key);
      links.push({ source, target, relation: rel.relation });
    }
  }

  return { nodes, links };
}

// Entity ids whose names appear verbatim in the answer (case-insensitive).
export function findHighlightedEntities(
  answer: string,
  entities: ReadonlyArray<EntityUsed>,
): Set<string> {
  if (!answer) return new Set();
  const haystack = answer.toLowerCase();
  const result = new Set<string>();
  for (const e of entities) {
    const needle = e.name.toLowerCase();
    if (needle.length < 3) continue;
    if (haystack.includes(needle)) {
      result.add(e.name);
    }
  }
  return result;
}

export function chatToGraphProps(response: ChatResponse): {
  data: ChatGraphData;
  highlighted: Set<string>;
  hasGraph: boolean;
  citationDocIds: ReadonlyArray<string>;
} {
  const entities = (response.entities_used ?? []) as EntityUsed[];
  const data = buildChatGraph(entities);
  const highlighted = findHighlightedEntities(response.answer, entities);
  const citationDocIds: ReadonlyArray<string> = Array.from(
    new Set((response.citations ?? []).map((c: ChatCitation) => c.document_id)),
  );
  return {
    data,
    highlighted,
    hasGraph:
      response.used_graph === true &&
      data.nodes.length > 0,
    citationDocIds,
  };
}
