from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[UUID] | None = None


class Citation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    chunk_index: int
    score: float
    text_preview: str


class GraphRelationEdge(BaseModel):
    relation: str
    direction: str = "out"  # "out" | "in" — semantic for 1-hop; "out" for multi-hop
    other: str
    other_type: str = ""
    other_description: str = ""
    distance: int = 1
    relation_chain: list[str] = []


class EntityUsed(BaseModel):
    name: str
    type: str = "Concept"
    description: str = ""
    relations: list[GraphRelationEdge] = []


class VerificationInfo(BaseModel):
    """Groundedness verdict from the Phase 5.2 verification agent.

    `verdict`:
      verified    — every atomic claim is supported by the cited context.
      partial     — at least one claim is unsupported but the score is above
                    the partial threshold.
      unsupported — the answer is mostly unsupported by the context.
      skipped     — verification didn't run (disabled, no context, or LLM
                    error). `skip_reason` carries the cause for debugging.
    """

    verdict: str = "skipped"
    groundedness_score: float = 0.0
    total_claims: int = 0
    supported_claims: int = 0
    unsupported_claims: list[str] = []
    skip_reason: str = ""


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    entities_used: list[EntityUsed] = []
    model: str
    used_context: bool
    used_graph: bool = False
    verification: VerificationInfo = Field(default_factory=VerificationInfo)
