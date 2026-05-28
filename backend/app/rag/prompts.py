"""Prompt templates for retrieval-augmented chat."""

from app.rag.graph_expansion import GraphFact
from app.rag.retrieval import RetrievedChunk

SYSTEM_PROMPT = (
    "You are a precise research assistant for the user's uploaded documents. "
    "Answer the user's question using ONLY the numbered context passages and "
    "the knowledge-graph facts below. Cite passages inline with [N] markers, "
    "and when you rely on a graph fact mention the entity name explicitly. "
    "If the available context does not contain enough information to answer, "
    "say so explicitly — do not invent facts."
)

NO_CONTEXT_FALLBACK_SYSTEM = (
    "You are a research assistant. The user has not uploaded any documents "
    "relevant to their question yet. Tell them so concisely and suggest they "
    "upload supporting material."
)


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    parts: list[str] = []
    for i, c in enumerate(chunks, start=1):
        parts.append(
            f"[{i}] (doc={c.document_id}, chunk={c.chunk_index}, score={c.score:.3f})\n"
            f"{c.text.strip()}"
        )
    return "\n\n".join(parts)


def build_graph_block(facts: list[GraphFact]) -> str:
    """Render a compact bulleted list of entities + their 1-hop relationships."""
    if not facts:
        return ""

    lines: list[str] = []
    for fact in facts:
        header = f"- {fact.name} ({fact.type})"
        if fact.description:
            header += f": {fact.description.strip()}"
        lines.append(header)
        for rel in fact.relations:
            arrow = "→" if rel.direction == "out" else "←"
            lines.append(f"    {arrow} {rel.relation} {rel.other}")
    return "\n".join(lines)


def build_user_message(
    query: str,
    chunks: list[RetrievedChunk],
    facts: list[GraphFact] | None = None,
) -> str:
    if not chunks and not (facts or []):
        return query

    sections: list[str] = []
    if chunks:
        sections.append(f"Context passages:\n\n{build_context_block(chunks)}")
    if facts:
        sections.append(f"Knowledge-graph facts:\n{build_graph_block(facts)}")

    return "\n\n".join(sections) + f"\n\nQuestion: {query}"
