import { describe, expect, it } from "vitest";

import type { ChatResponse } from "./chat-api";
import {
  buildChatGraph,
  chatToGraphProps,
  findHighlightedEntities,
  type EntityUsed,
} from "./graph-from-chat";

function ent(
  name: string,
  type: string,
  relations: EntityUsed["relations"] = [],
  description = "",
): EntityUsed {
  return { name, type, description, relations };
}

describe("buildChatGraph", () => {
  it("returns empty data for empty input", () => {
    expect(buildChatGraph([])).toEqual({ nodes: [], links: [] });
  });

  it("creates one node per primary entity", () => {
    const data = buildChatGraph([
      ent("Qdrant", "Technology"),
      ent("Cosine Distance", "Concept"),
    ]);

    expect(data.nodes).toHaveLength(2);
    expect(data.nodes.map((n) => n.id)).toEqual(["Qdrant", "Cosine Distance"]);
    expect(data.links).toEqual([]);
  });

  it("adds 'other' endpoints as nodes when they aren't in entities_used", () => {
    const data = buildChatGraph([
      ent("Platform", "Product", [
        {
          relation: "uses",
          direction: "out",
          other: "Qdrant",
          other_type: "Technology",
          other_description: "vector DB",
        },
      ]),
    ]);

    expect(data.nodes.map((n) => n.id).sort()).toEqual(["Platform", "Qdrant"]);
    const qdrant = data.nodes.find((n) => n.id === "Qdrant");
    expect(qdrant?.type).toBe("Technology");
    expect(qdrant?.description).toBe("vector DB");
    expect(data.links).toEqual([
      { source: "Platform", target: "Qdrant", relation: "uses" },
    ]);
  });

  it("respects in/out direction when building links", () => {
    const data = buildChatGraph([
      ent("Person", "Person", [
        { relation: "developed by", direction: "in", other: "Project" },
      ]),
    ]);

    expect(data.links).toEqual([
      { source: "Project", target: "Person", relation: "developed by" },
    ]);
  });

  it("dedupes identical links", () => {
    const data = buildChatGraph([
      ent("A", "Concept", [
        { relation: "uses", direction: "out", other: "B" },
        { relation: "uses", direction: "out", other: "B" },
      ]),
    ]);

    expect(data.links).toHaveLength(1);
  });

  it("does not lose richer data when primary entity is added before its 'other' twin", () => {
    // Primary entry has the type "Technology" + a real description; later
    // appearing as a related "other" with a stub Concept type should NOT
    // demote the data.
    const data = buildChatGraph([
      ent("Qdrant", "Technology", [], "vector DB"),
      ent("Platform", "Product", [
        {
          relation: "uses",
          direction: "out",
          other: "Qdrant",
          other_type: "Concept",
          other_description: "",
        },
      ]),
    ]);

    const qdrant = data.nodes.find((n) => n.id === "Qdrant");
    expect(qdrant?.type).toBe("Technology");
    expect(qdrant?.description).toBe("vector DB");
  });

  it("skips relations with empty 'other' fields", () => {
    const data = buildChatGraph([
      ent("A", "Concept", [
        { relation: "uses", direction: "out", other: "" },
      ]),
    ]);
    expect(data.links).toEqual([]);
  });
});

describe("findHighlightedEntities", () => {
  it("returns names that appear (case-insensitive) in the answer", () => {
    const result = findHighlightedEntities(
      "The platform uses Qdrant and Cosine Distance internally.",
      [
        ent("Qdrant", "Technology"),
        ent("Cosine Distance", "Concept"),
        ent("Neo4j", "Technology"),
      ],
    );

    expect(result.has("Qdrant")).toBe(true);
    expect(result.has("Cosine Distance")).toBe(true);
    expect(result.has("Neo4j")).toBe(false);
  });

  it("ignores entity names shorter than 3 chars", () => {
    const result = findHighlightedEntities("ai is everywhere", [
      ent("AI", "Concept"),
    ]);
    expect(result.size).toBe(0);
  });

  it("returns an empty set for an empty answer", () => {
    expect(findHighlightedEntities("", [ent("Qdrant", "Technology")])).toEqual(
      new Set(),
    );
  });
});

describe("chatToGraphProps", () => {
  function chatResponse(over: Partial<ChatResponse> = {}): ChatResponse {
    return {
      answer: "",
      citations: [],
      entities_used: [],
      model: "m",
      used_context: false,
      used_graph: false,
      ...over,
    };
  }

  it("hasGraph is false when used_graph is false", () => {
    const props = chatToGraphProps(
      chatResponse({
        used_graph: false,
        entities_used: [ent("X", "Concept")],
      }),
    );
    expect(props.hasGraph).toBe(false);
  });

  it("hasGraph is false when entities are empty", () => {
    const props = chatToGraphProps(
      chatResponse({ used_graph: true, entities_used: [] }),
    );
    expect(props.hasGraph).toBe(false);
  });

  it("hasGraph is true when used_graph=true and entities present", () => {
    const props = chatToGraphProps(
      chatResponse({
        used_graph: true,
        entities_used: [ent("Qdrant", "Technology")],
      }),
    );
    expect(props.hasGraph).toBe(true);
    expect(props.data.nodes).toHaveLength(1);
  });

  it("derives highlighted from the answer", () => {
    const props = chatToGraphProps(
      chatResponse({
        answer: "Qdrant is fast.",
        used_graph: true,
        entities_used: [
          ent("Qdrant", "Technology"),
          ent("Neo4j", "Technology"),
        ],
      }),
    );
    expect(props.highlighted.has("Qdrant")).toBe(true);
    expect(props.highlighted.has("Neo4j")).toBe(false);
  });

  it("dedupes document_ids from citations", () => {
    const props = chatToGraphProps(
      chatResponse({
        citations: [
          {
            chunk_id: "c1",
            document_id: "d1",
            chunk_index: 0,
            score: 0.7,
            text_preview: "",
          },
          {
            chunk_id: "c2",
            document_id: "d1",
            chunk_index: 1,
            score: 0.6,
            text_preview: "",
          },
        ],
      }),
    );
    expect(props.citationDocIds).toEqual(["d1"]);
  });
});
