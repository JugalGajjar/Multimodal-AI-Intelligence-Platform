"""Unit tests for the embedding wrapper. Mocks the heavy SentenceTransformer
so this suite is independent of the ML stack."""

from unittest.mock import MagicMock, patch

from app.workers.embeddings import (
    EMBEDDING_DIM,
    EMBEDDING_MODEL_NAME,
    embed_texts,
)


class _FakeVector:
    """Stand-in for a numpy array — has .tolist() like ndarray."""

    def __init__(self, data: list[float]) -> None:
        self._data = data

    def tolist(self) -> list[float]:
        return self._data


def test_constants_match_collection_design():
    # If either changes, the Qdrant collection name/size must change too.
    assert EMBEDDING_DIM == 384
    assert EMBEDDING_MODEL_NAME == "BAAI/bge-small-en-v1.5"


def test_empty_input_returns_empty_without_loading_model():
    # Must not trigger the lazy import of sentence_transformers.
    with patch("app.workers.embeddings.get_embedding_model") as get_model:
        out = embed_texts([])

    assert out == []
    get_model.assert_not_called()


def test_returns_list_of_lists_with_correct_dim():
    fake_model = MagicMock()
    fake_model.encode.return_value = [
        _FakeVector([0.1] * EMBEDDING_DIM),
        _FakeVector([0.2] * EMBEDDING_DIM),
        _FakeVector([0.3] * EMBEDDING_DIM),
    ]

    with patch("app.workers.embeddings.get_embedding_model", return_value=fake_model):
        out = embed_texts(["a", "b", "c"])

    assert len(out) == 3
    assert all(isinstance(v, list) for v in out)
    assert all(len(v) == EMBEDDING_DIM for v in out)
    assert all(isinstance(x, float) for x in out[0])


def test_encode_called_with_normalize_true():
    fake_model = MagicMock()
    fake_model.encode.return_value = [_FakeVector([0.0] * EMBEDDING_DIM)]

    with patch("app.workers.embeddings.get_embedding_model", return_value=fake_model):
        embed_texts(["only"])

    _, kwargs = fake_model.encode.call_args
    assert kwargs["normalize_embeddings"] is True
    assert kwargs["show_progress_bar"] is False
    assert kwargs["convert_to_numpy"] is True


def test_encode_called_with_exact_input_texts():
    fake_model = MagicMock()
    fake_model.encode.return_value = [
        _FakeVector([0.0] * EMBEDDING_DIM),
        _FakeVector([0.0] * EMBEDDING_DIM),
    ]

    with patch("app.workers.embeddings.get_embedding_model", return_value=fake_model):
        embed_texts(["first", "second"])

    args, _ = fake_model.encode.call_args
    assert args[0] == ["first", "second"]
