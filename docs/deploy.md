# Deployment

End-to-end deploy of the platform onto strictly **free** managed services.

| component        | service                       | tier              |
| ---------------- | ----------------------------- | ----------------- |
| Frontend         | Vercel                        | Hobby (free)      |
| Backend API      | Hugging Face Spaces (Docker)  | 2 vCPU / 16 GB    |
| Worker           | Hugging Face Spaces (Docker)  | 2 vCPU / 16 GB    |
| Postgres         | Neon                          | free 0.5 GB       |
| Redis (queue)    | Upstash                       | free 10 K cmds/day |
| Object store     | Cloudflare R2                 | free 10 GB        |
| Vector store     | Qdrant Cloud                  | free 1 GB cluster |
| Graph store      | Neo4j AuraDB                  | free 50 K nodes   |
| LLM              | Groq + OpenRouter             | free / metered    |

Total cost: **$0/month** — no card required, no idle-stop.

> Requires the `vercel` CLI and a local `git` with the
> [`huggingface_hub`](https://pypi.org/project/huggingface_hub/) library
> (`pip install huggingface_hub`) for the Space CLI.

---

## 1. Provision the managed data services

### 1a. Postgres (Neon)

1. Sign up at <https://neon.tech>, create a project.
2. Copy the **pooled** connection string from the dashboard:
   `postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/dbname?sslmode=require`
3. Rewrite the scheme for asyncpg and replace `sslmode` with `ssl`:
   `postgresql+asyncpg://user:pass@ep-xxx-pooler.region.aws.neon.tech/dbname?ssl=require`
4. Keep that string handy — it's `DATABASE_URL`.

### 1b. Redis (Upstash)

1. Sign up at <https://upstash.com> → **Create database** → Global.
2. Copy the host, port, and the TLS password from the dashboard.
3. Map to:
   - `REDIS_HOST` = the host
   - `REDIS_PORT` = `6379`
   - `REDIS_PASSWORD` = the password
   - `REDIS_SECURE` = `true`

### 1c. Object storage (Cloudflare R2)

1. Sign up at <https://dash.cloudflare.com> → R2 → **Create bucket**.
2. Name the bucket `mmap-uploads`. Note the **account ID**.
3. **Manage R2 API Tokens** → create token with **Object Read & Write**.
4. Map to:
   - `MINIO_ENDPOINT` = `<account-id>.r2.cloudflarestorage.com` (no scheme)
   - `MINIO_ROOT_USER` = the access key id
   - `MINIO_ROOT_PASSWORD` = the secret access key
   - `MINIO_BUCKET` = `mmap-uploads`
   - `MINIO_SECURE` = `true`

### 1d. Vector store (Qdrant Cloud)

1. Sign up at <https://cloud.qdrant.io>, create a free 1 GB cluster.
2. Map to:
   - `QDRANT_URL` = `https://<id>.<region>.aws.cloud.qdrant.io`
   - `QDRANT_API_KEY` = the cluster key

### 1e. Graph store (Neo4j AuraDB)

1. Sign up at <https://console.neo4j.io>, create a free AuraDB instance.
2. Download the credentials file.
3. Map to:
   - `NEO4J_URI` = `neo4j+s://<id>.databases.neo4j.io`
   - `NEO4J_USER` = `neo4j`
   - `NEO4J_PASSWORD` = from the credentials file

### 1f. LLM keys

- Groq: <https://console.groq.com> → `GROQ_API_KEY`
- OpenRouter: <https://openrouter.ai> → `OPENROUTER_API_KEY`

---

## 2. Deploy the backend (HF Space)

### 2a. Create the Space

In the HF UI (<https://huggingface.co/new-space>):
- Name: `mmap-backend`
- License: pick what fits
- **Space SDK: Docker**
- **Space hardware: CPU basic (free)**

Or with the CLI:

```bash
huggingface-cli login
huggingface-cli repo create mmap-backend --type space --space_sdk docker
```

### 2b. Push the source

The Space lives in its own git repo. Clone it next to this one and copy
the backend tree in:

```bash
# from anywhere outside this repo:
git clone https://huggingface.co/spaces/<your-handle>/mmap-backend
cd mmap-backend

# Copy the backend tree; Dockerfile.prod's COPY paths expect this as the root.
cp -r /path/to/Multimodal-AI-Intelligence-Platform/backend/. .

# HF Spaces expects a Dockerfile at the repo root.
mv Dockerfile.prod Dockerfile
rm -f Dockerfile.worker.prod   # the worker variant isn't needed in this Space

# The Space's README.md drives the Space config (sdk, port, theme, etc.).
cp /path/to/Multimodal-AI-Intelligence-Platform/docs/deploy/space-backend-README.md README.md

git add .
git commit -m "initial backend space"
git push
```

### 2c. Set secrets

In the Space's **Settings → Variables and secrets**, add every value from
section 1 as a **secret**:

```
JWT_SECRET            (openssl rand -base64 48)
BACKEND_CORS_ORIGINS  https://<your-vercel-domain>.vercel.app
DATABASE_URL          postgresql+asyncpg://...?ssl=require
REDIS_HOST            ...
REDIS_PORT            6379
REDIS_PASSWORD        ...
REDIS_SECURE          true
QDRANT_URL            https://...qdrant.io
QDRANT_API_KEY        ...
NEO4J_URI             neo4j+s://...databases.neo4j.io
NEO4J_USER            neo4j
NEO4J_PASSWORD        ...
MINIO_ENDPOINT        <account>.r2.cloudflarestorage.com
MINIO_ROOT_USER       ...
MINIO_ROOT_PASSWORD   ...
MINIO_BUCKET          mmap-uploads
MINIO_SECURE          true
GROQ_API_KEY          ...
OPENROUTER_API_KEY    ...
```

The Space rebuilds on every push and reloads env on every secret change.

### 2d. Smoke-test

```bash
curl -sf https://<your-handle>-mmap-backend.hf.space/api/v1/health
```

The container's `entrypoint.sh` runs `alembic upgrade head` on every boot,
so Neon migrates itself on the first deploy.

## 3. Deploy the worker (HF Space)

Same flow, different Dockerfile and README:

```bash
git clone https://huggingface.co/spaces/<your-handle>/mmap-worker
cd mmap-worker

cp -r /path/to/Multimodal-AI-Intelligence-Platform/backend/. .
mv Dockerfile.worker.prod Dockerfile
rm -f Dockerfile.prod

cp /path/to/Multimodal-AI-Intelligence-Platform/docs/deploy/space-worker-README.md README.md

git add .
git commit -m "initial worker space"
git push
```

In the worker Space's settings, set the same secrets as the backend
(except `BACKEND_CORS_ORIGINS` and `JWT_SECRET` aren't strictly needed).
The worker runs `python -m app.workers.main`, which starts the arq event
loop and a no-op health server on port 7860.

## 4. Deploy the frontend (Vercel)

```bash
cd frontend
vercel link                       # connect this directory to a Vercel project
vercel env add NEXT_PUBLIC_API_URL production
# → enter: https://<your-handle>-mmap-backend.hf.space
vercel --prod
```

Vercel auto-detects Next.js 16 (App Router) and uses `next build`.

## 5. Wire CORS + verify the round-trip

Once Vercel gives you the prod URL, set it on the backend Space:

In the backend Space → Settings → Variables and secrets, update
`BACKEND_CORS_ORIGINS` to the Vercel URL and click **Restart**.

End-to-end check:

1. Visit `https://<your-project>.vercel.app` → register an account.
2. Upload a small `.txt` from `backend/evals/corpus/` → wait for `processed`.
3. Ask a chat question that targets the doc.
4. Confirm the answer cites the uploaded doc and that the verification
   verdict is `verified` or `partial`.

---

## Production checklist

- [ ] `JWT_SECRET` is from `openssl rand -base64 48`
- [ ] `BACKEND_CORS_ORIGINS` is exactly your frontend origin — no `*`
- [ ] Postgres connection uses `?ssl=require`
- [ ] Redis is `rediss://` (TLS) with `REDIS_SECURE=true`
- [ ] Qdrant cluster region is close to where the Space runs (US, EU)
- [ ] `huggingface-cli repo list-files <space>` shows no `.env` or secrets
- [ ] First `/api/v1/chat` round-trip returns 200 with citations
- [ ] Worker Space's logs show `arq worker started`

---

## Rolling back

```bash
# In the Space repo:
git revert HEAD                     # or: git reset --hard <prev-sha>
git push --force                    # the Space rebuilds on push
```

Frontend rollback: one click in the Vercel dashboard → Deployments → the
previous deploy → **Promote to Production**.

## Tear-down

```bash
# Delete both Spaces:
huggingface-cli repo delete mmap-backend --type space
huggingface-cli repo delete mmap-worker  --type space

# Neon, Upstash, Cloudflare R2, Qdrant Cloud, AuraDB: delete from their
# respective web consoles.
vercel project rm mmap
```
