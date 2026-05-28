import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { GraphLinkData, GraphNodeData } from "@/lib/graph-api";

// Replace the canvas-heavy library with a transparent stub that exposes the
// data passed in. happy-dom can't render canvas, so we assert on inputs.
vi.mock("react-force-graph-2d", () => ({
  default: (props: {
    graphData: { nodes: unknown[]; links: unknown[] };
    onNodeClick?: (n: unknown) => void;
  }) => (
    <div
      data-testid="force-graph-stub"
      data-node-count={props.graphData.nodes.length}
      data-link-count={props.graphData.links.length}
    >
      <pre data-testid="kg-json">{JSON.stringify(props.graphData)}</pre>
      <button
        type="button"
        data-testid="kg-click"
        onClick={() =>
          props.onNodeClick?.((props.graphData.nodes as { id: string }[])[0])
        }
      >
        click first node
      </button>
    </div>
  ),
}));

// `next/dynamic` resolves to the actual factory's default export at runtime.
// In vitest we stub it to just call the factory and use its default.
vi.mock("next/dynamic", () => ({
  default: (factory: () => Promise<{ default: unknown }>) => {
    let Component: unknown = null;
    factory().then((mod) => {
      Component = mod.default;
    });
    const Wrapped = (props: unknown) => {
      if (!Component) {
        // Render a stand-in to keep the tree mounted while the factory resolves.
        return <div data-testid="kg-loading" />;
      }
      const C = Component as React.ComponentType<unknown>;
      return <C {...(props as object)} />;
    };
    return Wrapped;
  },
}));

import { KnowledgeGraph } from "./knowledge-graph";

const sampleNodes: GraphNodeData[] = [
  {
    id: "Qdrant",
    name: "Qdrant",
    type: "Technology",
    description: "vector DB",
    document_ids: ["d1"],
  },
  {
    id: "Cosine Distance",
    name: "Cosine Distance",
    type: "Concept",
    description: "similarity metric",
    document_ids: ["d1"],
  },
  {
    id: "Jugal Gajjar",
    name: "Jugal Gajjar",
    type: "Person",
    description: "",
    document_ids: ["d1"],
  },
];

const sampleLinks: GraphLinkData[] = [
  { source: "Qdrant", target: "Cosine Distance", relation: "uses" },
];

describe("<KnowledgeGraph />", () => {
  it("shows the empty state when there are no nodes", () => {
    render(<KnowledgeGraph nodes={[]} links={[]} />);

    expect(screen.getByTestId("kg-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("knowledge-graph")).not.toBeInTheDocument();
  });

  it("renders the force-graph and passes node/link counts through", async () => {
    render(<KnowledgeGraph nodes={sampleNodes} links={sampleLinks} />);

    const stub = await screen.findByTestId("force-graph-stub");
    expect(stub.getAttribute("data-node-count")).toBe("3");
    expect(stub.getAttribute("data-link-count")).toBe("1");
  });

  it("attaches a color to each node based on its type", async () => {
    render(<KnowledgeGraph nodes={sampleNodes} links={sampleLinks} />);

    await screen.findByTestId("force-graph-stub");
    const json = screen.getByTestId("kg-json");
    const data = JSON.parse(json.textContent ?? "{}") as {
      nodes: { id: string; color: string }[];
    };

    const qdrant = data.nodes.find((n) => n.id === "Qdrant");
    const cosine = data.nodes.find((n) => n.id === "Cosine Distance");
    const person = data.nodes.find((n) => n.id === "Jugal Gajjar");

    expect(qdrant?.color).toBeDefined();
    expect(cosine?.color).toBeDefined();
    expect(person?.color).toBeDefined();
    // Different types must produce different colors.
    expect(qdrant?.color).not.toBe(cosine?.color);
    expect(person?.color).not.toBe(qdrant?.color);
  });

  it("marks highlighted nodes when the highlighted set contains their id", async () => {
    render(
      <KnowledgeGraph
        nodes={sampleNodes}
        links={sampleLinks}
        highlighted={new Set(["Qdrant"])}
      />,
    );

    await screen.findByTestId("force-graph-stub");
    const json = screen.getByTestId("kg-json");
    const data = JSON.parse(json.textContent ?? "{}") as {
      nodes: { id: string; highlighted: boolean }[];
    };

    expect(data.nodes.find((n) => n.id === "Qdrant")?.highlighted).toBe(true);
    expect(data.nodes.find((n) => n.id === "Cosine Distance")?.highlighted).toBe(
      false,
    );
  });

  it("renders the legend with only types present in the data", async () => {
    render(<KnowledgeGraph nodes={sampleNodes} links={sampleLinks} />);

    const legend = await screen.findByTestId("kg-legend");
    expect(legend).toBeInTheDocument();
    // Types that are present in nodes
    expect(legend).toHaveTextContent(/Technology/);
    expect(legend).toHaveTextContent(/Concept/);
    expect(legend).toHaveTextContent(/Person/);
    // Types that are NOT in the data
    expect(legend).not.toHaveTextContent(/Location/);
    expect(legend).not.toHaveTextContent(/Event/);
  });

  it("hides the legend when showLegend=false", async () => {
    render(
      <KnowledgeGraph
        nodes={sampleNodes}
        links={sampleLinks}
        showLegend={false}
      />,
    );

    await screen.findByTestId("force-graph-stub");
    expect(screen.queryByTestId("kg-legend")).not.toBeInTheDocument();
  });

  it("invokes onNodeClick with the original node shape (no internal fields)", async () => {
    const onClick = vi.fn();
    render(
      <KnowledgeGraph
        nodes={sampleNodes}
        links={sampleLinks}
        onNodeClick={onClick}
      />,
    );

    const click = await screen.findByTestId("kg-click");
    click.click();

    expect(onClick).toHaveBeenCalledTimes(1);
    const arg = onClick.mock.calls[0][0];
    expect(arg.id).toBe("Qdrant");
    expect(arg.type).toBe("Technology");
    // Internal "color" / "highlighted" fields should not be exposed to consumers.
    expect(arg).not.toHaveProperty("color");
    expect(arg).not.toHaveProperty("highlighted");
  });

  it("gives every link a stable id to keep React keys happy", async () => {
    render(<KnowledgeGraph nodes={sampleNodes} links={sampleLinks} />);

    await screen.findByTestId("force-graph-stub");
    const json = screen.getByTestId("kg-json");
    const data = JSON.parse(json.textContent ?? "{}") as {
      links: { id: string }[];
    };
    expect(data.links[0].id).toMatch(/Qdrant.*uses.*Cosine/);
  });
});
