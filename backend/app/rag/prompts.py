"""Prompt templates for retrieval-augmented chat."""

from app.rag.graph_expansion import GraphFact
from app.rag.retrieval import RetrievedChunk
from app.rag.tavily import WebResult

SYSTEM_PROMPT = (
    "You are a precise research assistant for the user's uploaded documents. "
    "Answer the user's question using ONLY the numbered context passages and "
    "the knowledge-graph facts below. Cite passages inline with [N] markers, "
    "and when you rely on a graph fact mention the entity name explicitly. "
    "If web results are provided they are additional citable context — cite "
    "them inline with [W#] markers. "
    "If the available context does not contain enough information to answer, "
    "say so explicitly — do not invent facts."
)

REGULAR_MODE_SYSTEM = (
    "You are a research assistant for the user's uploaded documents. Prefer "
    "the numbered context passages and knowledge-graph facts below; cite "
    "passages inline with [N] markers and web results with [W#] markers. "
    "You may supplement with your own knowledge when the context is thin — "
    "do not attach citation markers to statements that come from your own "
    "knowledge, and never invent citations."
)

PURE_KNOWLEDGE_SYSTEM = (
    "You are a knowledgeable research assistant. The user has chosen to "
    "answer this question from your general knowledge without document "
    "retrieval. Answer directly and be explicit about uncertainty — do not "
    "fabricate specifics you are unsure of."
)

WEB_ONLY_SYSTEM = (
    "You are a research assistant with access to fresh web search results. "
    "Answer the user's question using the numbered web results below, "
    "supplemented by your own knowledge where helpful. Cite web results "
    "inline with [W#] markers; do not attach markers to statements from "
    "your own knowledge."
)

NO_CONTEXT_FALLBACK_SYSTEM = (
    "You are a research assistant. The user has not uploaded any documents "
    "relevant to their question yet. Tell them so concisely and suggest they "
    "upload supporting material."
)

STRICT_REFUSAL_MESSAGE = (
    "I can't answer this confidently from your documents — strict mode "
    "requires high-confidence grounding. Switch to regular mode in Settings "
    "or rephrase your question."
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
    """Render a compact bulleted list of entities + their multi-hop chains.

    For 1-hop facts:               "→ uses Cosine Distance"   (← for incoming)
    For 2+-hop (distance>1):       "↝ uses → part of Vector Math   (2-hop)"
    """
    if not facts:
        return ""

    lines: list[str] = []
    for fact in facts:
        header = f"- {fact.name} ({fact.type})"
        if fact.description:
            header += f": {fact.description.strip()}"
        lines.append(header)
        for rel in fact.relations:
            if rel.distance > 1:
                chain = " → ".join(rel.relation_chain) if rel.relation_chain else rel.relation
                tail = f"   ({rel.distance}-hop)"
                lines.append(f"    ↝ {chain} {rel.other}{tail}")
            else:
                arrow = "→" if rel.direction == "out" else "←"
                lines.append(f"    {arrow} {rel.relation} {rel.other}")
    return "\n".join(lines)


def build_web_block(results: list[WebResult]) -> str:
    parts: list[str] = []
    for i, r in enumerate(results, start=1):
        content = r.content if len(r.content) <= 1000 else r.content[:1000] + "…"
        parts.append(f"[W{i}] {r.title}\n{r.url}\n{content}")
    return "\n\n".join(parts)


def build_summaries_block(summaries: list[dict]) -> str:
    if not summaries:
        return ""
    lines: list[str] = []
    for s in summaries:
        name = s.get("filename") or s.get("id") or "document"
        lines.append(f"- {name}")
        tldr = (s.get("tldr") or "").strip()
        if tldr:
            lines.append(f"    {tldr}")
        for p in (s.get("key_points") or [])[:5]:
            lines.append(f"    • {p}")
    return "\n".join(lines)


def build_user_message(
    query: str,
    chunks: list[RetrievedChunk],
    facts: list[GraphFact] | None = None,
    summaries: list[dict] | None = None,
    web_results: list[WebResult] | None = None,
) -> str:
    if not chunks and not (facts or []) and not (summaries or []) and not (web_results or []):
        return query

    sections: list[str] = []
    if chunks:
        sections.append(f"Context passages:\n\n{build_context_block(chunks)}")
    if facts:
        sections.append(f"Knowledge-graph facts:\n{build_graph_block(facts)}")
    if summaries:
        sections.append(f"Document summaries:\n{build_summaries_block(summaries)}")
    if web_results:
        sections.append(f"Web results:\n\n{build_web_block(web_results)}")

    return "\n\n".join(sections) + f"\n\nQuestion: {query}"
