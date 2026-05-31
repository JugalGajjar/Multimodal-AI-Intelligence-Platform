"""LangGraph-orchestrated agents.

Phase 5.1 ships the foundation: a 2-node `chat_workflow` (retrieve → respond)
that wraps the existing inline chat flow. Subsequent sub-phases add nodes for
verification, summarization, and routing without rewiring the FastAPI surface.
"""
