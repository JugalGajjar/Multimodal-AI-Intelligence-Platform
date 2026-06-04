"""End-to-end eval driver — uploads corpus, runs dataset.jsonl, scores
recall@k / keyword coverage / groundedness. See evals/README.md."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .metrics import keyword_coverage, mean, recall_at_k

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_DIR = EVAL_DIR / "corpus"
DATASET_PATH = EVAL_DIR / "dataset.jsonl"

PROCESS_POLL_INTERVAL_SEC = 5.0
PROCESS_POLL_MAX_ATTEMPTS = 60  # ≈ 5 minutes per document


@dataclass
class QuestionResult:
    id: str
    question: str
    recall: float
    coverage: float
    groundedness: float | None
    verdict: str
    intent: str
    answer_preview: str
    retrieved_doc_ids: list[str] = field(default_factory=list)


@dataclass
class EvalSummary:
    n_questions: int
    top_k: int
    avg_recall_at_k: float
    avg_keyword_coverage: float
    avg_groundedness: float | None
    n_grounded: int


def load_dataset() -> list[dict[str, Any]]:
    with DATASET_PATH.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


async def register_and_login(client: httpx.AsyncClient) -> str:
    # pydantic's EmailStr rejects .local/.test/.example as reserved.
    email = f"eval-{secrets.token_hex(4)}@evalbot.io"
    password = "EvalUserP@ssw0rd!"  # noqa: S105
    reg = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    if reg.status_code not in (201, 409):
        reg.raise_for_status()
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    login.raise_for_status()
    return login.json()["access_token"]


async def upload_corpus(client: httpx.AsyncClient) -> dict[str, str]:
    """Upload every corpus file. Returns filename → document_id."""
    mapping: dict[str, str] = {}
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        with path.open("rb") as fh:
            resp = await client.post(
                "/api/v1/documents",
                files={"file": (path.name, fh, "text/plain")},
            )
        resp.raise_for_status()
        mapping[path.name] = resp.json()["id"]
        print(f"  uploaded {path.name} → {mapping[path.name]}", file=sys.stderr)
    return mapping


async def wait_for_processing(
    client: httpx.AsyncClient, filename_to_doc_id: dict[str, str]
) -> None:
    """Poll until every document reaches the 'processed' state, or fail."""
    pending = dict(filename_to_doc_id)
    for _ in range(PROCESS_POLL_MAX_ATTEMPTS):
        if not pending:
            return
        for name, doc_id in list(pending.items()):
            resp = await client.get(f"/api/v1/documents/{doc_id}")
            resp.raise_for_status()
            status = resp.json()["status"]
            if status == "processed":
                print(f"  processed {name}", file=sys.stderr)
                pending.pop(name)
            elif status == "failed":
                raise RuntimeError(f"document {name} ({doc_id}) failed to process")
        if pending:
            await asyncio.sleep(PROCESS_POLL_INTERVAL_SEC)
    raise TimeoutError(f"documents still pending after polling: {list(pending.keys())}")


async def score_question(
    client: httpx.AsyncClient,
    question: dict[str, Any],
    filename_to_doc_id: dict[str, str],
    top_k: int,
) -> QuestionResult:
    expected_ids = {
        filename_to_doc_id[fn]
        for fn in question.get("expected_filenames", [])
        if fn in filename_to_doc_id
    }
    resp = await client.post(
        "/api/v1/chat",
        json={"query": question["question"], "top_k": top_k},
    )
    resp.raise_for_status()
    data = resp.json()

    retrieved_ids = [c["document_id"] for c in data.get("citations", [])[:top_k]]
    recall = recall_at_k(expected_ids, retrieved_ids)
    coverage = keyword_coverage(question.get("expected_keywords", []), data["answer"])

    verification = data.get("verification") or {}
    verdict = verification.get("verdict", "skipped")
    grounded = (
        float(verification.get("groundedness_score", 0.0))
        if verdict not in {"skipped", ""}
        else None
    )

    return QuestionResult(
        id=question["id"],
        question=question["question"],
        recall=recall,
        coverage=coverage,
        groundedness=grounded,
        verdict=verdict,
        intent=str(data.get("intent", "chat")),
        answer_preview=data["answer"][:240],
        retrieved_doc_ids=retrieved_ids,
    )


def summarise(results: list[QuestionResult], top_k: int) -> EvalSummary:
    grounded_vals = [r.groundedness for r in results if r.groundedness is not None]
    avg_recall = mean(r.recall for r in results) or 0.0
    avg_coverage = mean(r.coverage for r in results) or 0.0
    avg_grounded = mean(grounded_vals)
    return EvalSummary(
        n_questions=len(results),
        top_k=top_k,
        avg_recall_at_k=avg_recall,
        avg_keyword_coverage=avg_coverage,
        avg_groundedness=avg_grounded,
        n_grounded=len(grounded_vals),
    )


async def run(args: argparse.Namespace) -> int:
    print(f"→ targeting {args.api_url}", file=sys.stderr)
    async with httpx.AsyncClient(base_url=args.api_url, timeout=args.timeout) as client:
        token = await register_and_login(client)
        client.headers["Authorization"] = f"Bearer {token}"

        print("→ uploading corpus", file=sys.stderr)
        filename_to_doc_id = await upload_corpus(client)

        print("→ waiting for ingest pipeline", file=sys.stderr)
        await wait_for_processing(client, filename_to_doc_id)

        dataset = load_dataset()
        print(f"→ scoring {len(dataset)} questions at top_k={args.top_k}", file=sys.stderr)
        results: list[QuestionResult] = []
        for q in dataset:
            r = await score_question(client, q, filename_to_doc_id, args.top_k)
            print(
                f"  [{r.id}] recall={r.recall:.2f} cov={r.coverage:.2f} "
                f"grd={r.groundedness if r.groundedness is None else f'{r.groundedness:.2f}'} "
                f"verdict={r.verdict}",
                file=sys.stderr,
            )
            results.append(r)

    summary = summarise(results, args.top_k)
    report = {
        "summary": asdict(summary),
        "per_question": [asdict(r) for r in results],
    }
    args.output.write_text(json.dumps(report, indent=2))

    avg_g = f"{summary.avg_groundedness:.2f}" if summary.avg_groundedness is not None else "n/a"
    print(
        f"recall@{summary.top_k}={summary.avg_recall_at_k:.2f} "
        f"coverage={summary.avg_keyword_coverage:.2f} "
        f"groundedness={avg_g} "
        f"(n={summary.n_questions}, grounded={summary.n_grounded})"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the RAG eval suite end-to-end.")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the backend API (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Retrieval depth to pass to the chat endpoint (default: 5).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-request HTTP timeout in seconds (default: 120).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/report.json"),
        help="Where to write the full JSON report (default: evals/report.json).",
    )
    return parser.parse_args()


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
