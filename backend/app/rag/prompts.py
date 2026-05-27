"""Prompt templates for retrieval-augmented chat."""

from app.rag.retrieval import RetrievedChunk

SYSTEM_PROMPT = (
    "You are a precise research assistant for the user's uploaded documents. "
    "Answer the user's question using ONLY the numbered context passages below. "
    "Cite the passages you rely on inline using [N] markers matching the "
    "passage numbers. If the context does not contain enough information to "
    "answer, say so explicitly — do not invent facts."
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


def build_user_message(query: str, chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return query
    return f"Context passages:\n\n{build_context_block(chunks)}\n\nQuestion: {query}"
