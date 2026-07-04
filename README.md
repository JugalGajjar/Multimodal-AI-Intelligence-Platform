# Multimodal AI Intelligence Platform

[![ci](https://github.com/JugalGajjar/Multimodal-AI-Intelligence-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/JugalGajjar/Multimodal-AI-Intelligence-Platform/actions/workflows/ci.yml)
[![nightly](https://github.com/JugalGajjar/Multimodal-AI-Intelligence-Platform/actions/workflows/nightly.yml/badge.svg)](https://github.com/JugalGajjar/Multimodal-AI-Intelligence-Platform/actions/workflows/nightly.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)](https://nextjs.org/)

Retrieval-augmented chat over text, PDFs, images, audio, and video, with a live knowledge graph extracted from your uploads, optional web-search augmentation, persistent multi-turn chat history, and grounded, cited answers.

Live at **[projectmmap.com](https://projectmmap.com)**.

## What it does

Upload anything readable. The platform extracts the text (OCR for images, Whisper for audio, frame sampling plus transcription for video, native parse for PDFs and text), chunks and embeds it, indexes the chunks in a vector store, pulls entities and relationships into a knowledge graph, and then lets you chat over everything with citations back to the source chunks.

- **Multimodal ingest.** PDFs, images, audio, video, plain text, markdown. One shared vector space. 100 MB upload cap.
- **Vision plus OCR.** RapidOCR plus a vision-language model give every image a searchable, summarized representation.
- **Audio transcription.** Groq Whisper turns recordings into citable, retrievable text.
- **Video understanding.** Adaptive frame sampling (cv2) plus audio extraction (ffmpeg) feed a single fused Nemotron VL call with the Whisper transcript embedded as document context — the model cross-references what's said against what's shown. 5-minute cap.
- **Knowledge graph.** Entities and relationships extracted per document, visualized client-side, and used to ground answers.
- **Cited chat.** Streaming answers with chunk-level citations and a per-answer subgraph highlighting the entities the model used.
- **Citations that hold up.** Hybrid retrieval (BM25 sparse + dense vectors fused via reciprocal-rank in Qdrant) plus a cross-encoder reranker (`bge-reranker-base`) over the top candidates surfaces the chunk that *answers* your question, not just the topically nearest one. Citation previews are query-centered — the snippet shows the part of the chunk that mentions your terms — and a min-length filter at ingest drops sub-80-char OCR fragments before they reach the index.
- **Chat controls.** Per-question RAG and Web toggles: answer from your documents (default), the model's own knowledge, fresh Tavily web results with clickable `[W#]` source citations, or any combination.
- **Strict and regular modes.** Strict (default) fact-checks every answer against your documents and cited web sources, withholding anything below the grounding threshold; regular blends documents with model knowledge. Configurable per account, along with a 1–10 cap on websites searched.
- **Persistent chat history.** Every conversation is saved with an auto-generated title and short summary. The dashboard keeps a live session thread that survives client navigation and resets on hard refresh; the Chats page lets you search across titles, summaries, and full message text, rename or delete saved threads, and read transcripts with citations intact. Follow-up questions see prior turns of the same chat.
- **Verification.** Each answer is checked against retrieved context (and web results when used) and flags unsupported claims.

## Architecture

```
            +---------------------+
            |  Browser (Next.js)  |
            +----------+----------+
                       |
                       v
+---------------------------------------------+
|        FastAPI API  (Hugging Face Space)    |
|  auth, uploads, chat, graph, RAG endpoints  |
+----+-------------------------+--------------+
     |                         |
     | enqueue                 | read
     v                         |
+------------+        +---------+----------+
|   arq      |        | Postgres (Neon)    |
|  worker    |        | Qdrant Cloud       |
| (HF Space) |        | Neo4j AuraDB       |
+-----+------+        | Redis (Upstash)    |
      |               | R2 / MinIO         |
      | OCR, ASR,     +--------------------+
      | vision,
      | video frames,
      | embedding,
      | summarize,
      | graph extract
      v
+--------------------------+
|  OpenRouter (Nemotron    |
|  Nano 2 VL, DeepSeek)    |
|  Groq (Whisper, GPT-OSS) |
|  Tavily (web search)     |
+--------------------------+
```

The API stays light. All heavy lifting (OCR, ASR, embedding, vision, graph extraction) runs in the arq worker process so request latency stays bounded.

## Tech stack

**Backend.** Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Pydantic 2, asyncpg, bcrypt, PyJWT, slowapi, arq, sentence-transformers, fastembed, qdrant-client, neo4j, LangGraph, OpenTelemetry, prometheus-client.

**Frontend.** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui, Zustand, TanStack Query, react-force-graph-2d, Sonner.

**Data plane.** Postgres for users and document metadata, Qdrant for vector search, Neo4j for the entity graph, Redis for the job queue and rate limiting, S3-compatible object storage (Cloudflare R2 in prod, MinIO in dev) for raw uploads.

**Models.** OpenRouter for vision and video (NVIDIA Nemotron Nano 2 VL) and reasoning (DeepSeek). Groq for audio transcription (Whisper Large v3 Turbo), fast reasoning (GPT-OSS 20B), and structured extraction / verification / summarization (GPT-OSS 120B). Tavily for web-search augmentation.

**Tests.** pytest (backend unit and integration), vitest plus Testing Library (frontend), Playwright (end-to-end), with a nightly workflow that spins up the full docker compose stack.

## Quick start (local)

Requires Docker, Docker Compose, and Make-friendly shell tools.

```bash
cp .env.example .env
# Fill in OPENROUTER_API_KEY and GROQ_API_KEY at minimum.
# TAVILY_API_KEY is optional — only needed for the chat "Web" toggle.

docker compose up --build
```

That brings up Postgres, Redis, Qdrant, Neo4j, MinIO, the FastAPI API, the arq worker, and the Next.js frontend behind Traefik. Once healthy:

- App: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>
- MinIO console: <http://localhost:9001>
- Neo4j browser: <http://localhost:7474>
- Qdrant dashboard: <http://localhost:6333/dashboard>

In dev mode, registration returns a `dev_verification_code` in the response so you can verify the account without an email provider configured.

### Running pieces individually

Backend only:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,worker]"
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend only:

```bash
cd frontend
npm install
npm run dev
```

## Configuration

All configuration is driven by environment variables. See [`.env.example`](.env.example) for the full list. Highlights:

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET` | HMAC key for access tokens. Generate with `openssl rand -base64 48`. |
| `DATABASE_URL` | Optional. Overrides the per-field Postgres settings for managed providers (Neon, Supabase). |
| `QDRANT_URL` / `QDRANT_API_KEY` | Qdrant Cloud credentials. Falls back to in-cluster Qdrant. |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | Neo4j connection. AuraDB instances use a non-`neo4j` username. |
| `OPENROUTER_API_KEY` | Required for vision, video, and reasoning. |
| `GROQ_API_KEY` | Required for audio transcription and entity extraction. |
| `TAVILY_API_KEY` | Web search for the chat "Web" toggle. Without it, web-toggled requests return 503. |
| `STRICT_GROUNDEDNESS_THRESHOLD` | Strict-mode gate (default 0.80). Answers scoring below are withheld. |
| `RESEND_API_KEY` / `RESEND_FROM_EMAIL` | Transactional email. When unset, registration returns the verification code in the response (dev only). |
| `RATE_LIMIT_ENABLED` | Per-IP limits on `/auth/*`. Disable in test suites. |
| `OTEL_ENABLED` / `OTEL_ENDPOINT` | OpenTelemetry export. Off in CI. |

## Testing

```bash
# Backend unit + lint + types
cd backend
ruff check . && ruff format --check .
mypy app
pytest -q

# Backend integration (needs docker compose stack running)
pytest -q tests/integration

# Frontend
cd frontend
npm run lint
npm run typecheck
npm test

# End-to-end (Playwright against the local stack)
npx playwright install
npx playwright test
```

CI runs the unit, type, and lint suites on every push and pull request. The nightly workflow brings up the docker compose stack, runs the backend integration suite, and runs the Playwright e2e suite against it.

## Deployment

Production runs entirely on free tiers.

| Layer | Provider |
| --- | --- |
| Frontend | Vercel (custom domain) |
| API + Worker | Hugging Face Spaces (Docker SDK), one Space each |
| Postgres | Neon |
| Vector store | Qdrant Cloud |
| Knowledge graph | Neo4j AuraDB Free |
| Queue + rate limits | Upstash Redis |
| Object storage | Cloudflare R2 |
| Email | Resend |

Production-only quirks worth knowing:

- **Qdrant Cloud needs explicit payload indexes** on `user_id` and `document_id`. The API creates them at startup; do not rely on the self-hosted "auto index" behavior.
- **Neo4j AuraDB instances** ship with a generated username, not the literal `neo4j`. Copy the username from the Aura console into `NEO4J_USER`.
- **slowapi** is configured against sync `redis://` because the limits library's `async+redis` strategy needs `coredis` and the default slowapi strategy isn't compatible with it.

The frontend deploys manually via the Vercel CLI — `vercel --prod` from `frontend/`. Backend redeploys are scripted under `scripts/`.

## Repo layout

```
backend/                FastAPI app, arq worker, Alembic migrations
  app/
    agents/             LangGraph workflows (chat, intent routing, summarization, verification)
    api/                health, metrics, router glue
    auth/               registration, login, email verification, password reset
    chats/              chat history: models, persistence, list/search/rename/delete
    documents/          upload, list, get, chunks, text, summary, reindex
    embeddings/         sentence-transformers client + chunking
    graph/              Neo4j client, entity extraction, graph router
    ingestion/          PDF parse, OCR, vision, transcription pipelines
    ocr/                RapidOCR wrapper
    rag/                retrieval, prompts, OpenRouter/Groq/Tavily clients
    storage/            Qdrant client, R2/MinIO client
    transcription/      Groq Whisper client
    video/              fused-RAG video description (Nemotron VL)
    vision/             vision-language model client
    workers/            arq job definitions (incl. video frame sampling + audio extraction)
  alembic/              database migrations
  evals/                offline eval harness
  tests/                unit + integration suites
frontend/               Next.js 16 app
  src/
    app/                routes (App Router)
    components/         UI components (auth, chat, chats, documents, graph, layout, settings, theme, ui)
    hooks/              cross-cutting hooks (status toasts, etc.)
    lib/                API clients, helpers, color/graph utilities
    store/              Zustand stores (auth, chat session)
e2e/                    Playwright specs
docker-compose.yml      Dev stack (frontend, backend, worker, Postgres, Redis, Qdrant, Neo4j, MinIO, Traefik)
docker-compose.prod.yml Production overlay
scripts/                Deploy helpers (push secrets to HF Spaces)
.github/workflows/      CI (unit) and nightly (integration + e2e)
```

## Security

- Bcrypt-hashed passwords. Account lockout after repeated failed logins.
- Email verification required before login (bcrypt-hashed codes, TTL).
- Password reset via emailed one-time code, also bcrypt-hashed with TTL.
- Disposable email domains rejected at registration.
- JWT access tokens (7-day expiry by default) with auto-redirect on 401.
- Per-IP rate limits on `/auth/*` via slowapi backed by Redis.
- Strict response headers on the frontend (HSTS, CSP, Referrer-Policy, Permissions-Policy, X-Content-Type-Options). The API response set is trimmed to what makes sense for a JSON service (no X-Frame-Options or frame-ancestors since the API is not framed).
- Per-user isolation enforced at every storage layer: Postgres row scope, Qdrant payload filter on `user_id`, Neo4j label/property scoping, object keys namespaced by user id.

## Contributing

Issues and pull requests welcome. Please run the unit, type, and lint suites locally before opening a PR.

## License

MIT. See [LICENSE](LICENSE).

## Author

Built by [Jugal Gajjar](https://www.linkedin.com/in/jugal-gajjar/).
