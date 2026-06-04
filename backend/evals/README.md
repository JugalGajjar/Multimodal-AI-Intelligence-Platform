# RAG eval suite

A fixed Q&A regression harness for the chat pipeline. Uploads a small static
corpus, asks every question in `dataset.jsonl` against the live HTTP API,
and scores responses on three axes:

| metric | what it measures |
| --- | --- |
| `recall@k` | fraction of expected source documents that appear in the citations the retriever returned |
| `keyword_coverage` | fraction of expected terms that show up (case-insensitive substring) in the generated answer |
| `groundedness` | the verification agent's own score for how well the answer is supported by the cited chunks |

The eval is **not** a pass/fail test — it's a tracking tool. Run it before
and after a retrieval, prompt, or model change and compare the scores.

## Prerequisites

- Backend stack running locally (`docker compose up -d`)
- `GROQ_API_KEY` set in `.env` (the verification agent needs it; if missing,
  groundedness will be `skipped` for every question)
- Python deps installed from `backend/pyproject.toml` (`pip install -e .`)

## Run

From the `backend/` directory:

```bash
python -m evals.run_eval                          # against localhost:8000
python -m evals.run_eval --api-url http://other  # remote stack
python -m evals.run_eval --top-k 3                # tighter retrieval
```

Output:

```
recall@5=0.92 coverage=0.78 groundedness=0.85 (n=12, grounded=12)
```

The full per-question breakdown is written to `evals/report.json`.

## Files

```
evals/
├── README.md           this file
├── corpus/             four short text documents (Kafka, Postgres, React, OTel)
├── dataset.jsonl       12 questions with expected source files + keywords
├── metrics.py          pure scoring functions (recall@k, keyword coverage)
└── run_eval.py         async driver: register → upload → poll → ask → score
```

## Extending

- Add a corpus doc: drop a `.txt` (or `.md`) in `corpus/`. The upload step
  picks it up automatically.
- Add a question: append a line to `dataset.jsonl`:

```json
{"id": "x-1", "question": "...", "expected_filenames": ["foo.txt"], "expected_keywords": ["term1", "term2"]}
```

Each question is independent — the eval driver does not chain conversation
turns, so questions cannot rely on prior context.
