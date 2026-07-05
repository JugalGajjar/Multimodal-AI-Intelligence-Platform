"""Curated list of chat-answer models the user can pick from Settings.

All entries are served through the Groq client (`app.rag.groq_chat`).
`ChatModelChoice.id` is passed straight to Groq — it must match Groq's model
catalog. `null` in a user's `chat_model` column means "use the server default"
(`settings.groq_reasoning_model`, which is `openai/gpt-oss-120b`).
"""

from typing import Literal

from pydantic import BaseModel

ChatModelCategory = Literal["open-source"]


class ChatModelChoice(BaseModel):
    id: str
    label: str
    provider: str
    category: ChatModelCategory
    notes: str
    is_default: bool = False


# Deliberately narrow — only models we've validated end-to-end with strict
# JSON verification. Extend after evaluating additional Groq offerings.
CHAT_MODELS: list[ChatModelChoice] = [
    ChatModelChoice(
        id="openai/gpt-oss-120b",
        label="GPT-OSS 120B",
        provider="Groq",
        category="open-source",
        notes="Larger model, stronger reasoning. The current default.",
        is_default=True,
    ),
    ChatModelChoice(
        id="openai/gpt-oss-20b",
        label="GPT-OSS 20B",
        provider="Groq",
        category="open-source",
        notes="Smaller sibling; lower latency but weaker on hard prompts.",
    ),
    ChatModelChoice(
        id="qwen/qwen3-32b",
        label="Qwen3 32B",
        provider="Groq",
        category="open-source",
        notes="Alternative model family; strong general reasoning.",
    ),
]

CHAT_MODEL_IDS = {m.id for m in CHAT_MODELS}


def is_valid_chat_model(model_id: str | None) -> bool:
    """True when `model_id` is None (use default) or matches an entry in
    the curated registry."""
    return model_id is None or model_id in CHAT_MODEL_IDS
