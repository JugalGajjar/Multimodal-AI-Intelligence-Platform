"""Reranker pipeline tests. The CrossEncoder model is mocked because loading
it pulls a ~280 MB checkpoint from Hugging Face."""

from unittest.mock import MagicMock, patch

from app.rag import reranker as rr
from app.rag.retrieval import RetrievedChunk


def _chunk(text: str, *, idx: int = 0, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c{idx}",
        document_id="d0",
        chunk_index=idx,
        score=score,
        text=text,
    )


def test_rerank_empty_returns_empty():
    assert rr.rerank("q", [], top_k=5) == []


def test_rerank_orders_by_cross_encoder_score():
    a, b, c = _chunk("alpha", idx=0), _chunk("beta", idx=1), _chunk("gamma", idx=2)
    model = MagicMock()
    # Reverse order of input: gamma first, beta, alpha last.
    model.predict.return_value = [0.1, 0.5, 0.9]

    with patch.object(rr, "get_reranker", return_value=model):
        out = rr.rerank("q", [a, b, c], top_k=2)

    assert [c.chunk_id for c in out] == ["c2", "c1"]
    # Scores replaced with reranker scores for transparency.
    assert out[0].score == 0.9
    assert out[1].score == 0.5


def test_rerank_falls_back_to_input_order_on_model_failure():
    a, b = _chunk("alpha", idx=0, score=0.42), _chunk("beta", idx=1, score=0.30)
    with patch.object(rr, "get_reranker", side_effect=RuntimeError("model down")):
        out = rr.rerank("q", [a, b], top_k=5)

    assert [c.chunk_id for c in out] == ["c0", "c1"]
    # Vector scores preserved when reranker is unavailable.
    assert out[0].score == 0.42


def test_single_candidate_is_returned_without_calling_model():
    a = _chunk("only one", idx=0)
    with patch.object(rr, "get_reranker") as fake:
        out = rr.rerank("q", [a], top_k=5)
    assert out == [a]
    fake.assert_not_called()
