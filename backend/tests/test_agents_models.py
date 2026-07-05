"""Curated chat-model registry (app.agents.models)."""

from app.agents.models import CHAT_MODEL_IDS, CHAT_MODELS, is_valid_chat_model


class TestChatModelsRegistry:
    def test_registry_is_non_empty_and_has_exactly_one_default(self):
        assert len(CHAT_MODELS) >= 1
        defaults = [m for m in CHAT_MODELS if m.is_default]
        assert len(defaults) == 1

    def test_each_entry_has_required_fields(self):
        for m in CHAT_MODELS:
            assert m.id and isinstance(m.id, str)
            assert m.label and isinstance(m.label, str)
            assert m.provider and isinstance(m.provider, str)
            assert m.category == "open-source"
            assert m.notes

    def test_ids_are_unique(self):
        ids = [m.id for m in CHAT_MODELS]
        assert len(ids) == len(set(ids))

    def test_ids_set_matches_the_list(self):
        assert {m.id for m in CHAT_MODELS} == CHAT_MODEL_IDS


class TestIsValidChatModel:
    def test_none_is_valid_means_use_default(self):
        assert is_valid_chat_model(None) is True

    def test_curated_ids_are_valid(self):
        for m in CHAT_MODELS:
            assert is_valid_chat_model(m.id) is True

    def test_unknown_ids_are_rejected(self):
        assert is_valid_chat_model("not-a-model") is False
        assert is_valid_chat_model("") is False
        # An id that looks Groq-shaped but isn't in the registry.
        assert is_valid_chat_model("meta-llama/llama-3.1-70b") is False
