# Deployment

End-to-end deploy of the platform onto free / cheap managed services:

| component       | managed service                  | tier         |
| --------------- | -------------------------------- | ------------ |
| Frontend        | Vercel                           | Hobby (free) |
| Backend API     | Fly.io Machine                   | shared-cpu-1x, ~$2/mo idle |
| Worker          | Fly.io Machine                   | shared-cpu-2x, ~$5/mo always-on |
| Postgres        | Neon                             | free 0.5 GB |
| Redis (queue)   | Upstash (Fly Marketplace)        | free 10 K cmds/day |
| Object store    | Tigris (Fly Marketplace)         | free 5 GB |
| Vector store    | Qdrant Cloud                     | free 1 GB cluster |
| Graph store     | Neo4j AuraDB                     | free 50 K nodes |
| LLM             | Groq + OpenRouter                | free / metered |

Total monthly cost lands around **$5–15** when both Fly machines are warm.

> All steps assume you have local `gh`, `flyctl`, `vercel` CLIs installed and
> are logged into each.

---

## 1. Provision the managed data services

### 1a. Postgres (Neon)

1. Sign up at <https://neon.tech>, create a project.
2. Copy the **pooled** connection string from the dashboard:
   `postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/dbname?sslmode=require`
3. Rewrite the scheme for asyncpg and replace `sslmode` with `ssl`:
   `postgresql+asyncpg://user:pass@ep-xxx-pooler.region.aws.neon.tech/dbname?ssl=require`
4. Keep that string handy — you'll set it as `DATABASE_URL` later.

### 1b. Redis (Upstash via Fly Marketplace)

```bash
fly redis create --name mmap-redis --region iad --no-replicas
fly redis status mmap-redis        # shows the private URL: rediss://default:TOKEN@...
```

The connection is TLS-only. You'll split it into three env vars:

- `REDIS_HOST` = the host portion
- `REDIS_PASSWORD` = the token (after `default:`)
- `REDIS_SECURE` = `true`

### 1c. Object storage (Tigris on Fly)

```bash
fly storage create --name mmap-uploads --region iad
```

The command prints `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and
`AWS_ENDPOINT_URL_S3` (e.g. `https://fly.storage.tigris.dev`). Map these to:

- `MINIO_ENDPOINT` = `fly.storage.tigris.dev` (no `https://`)
- `MINIO_ROOT_USER` = the access key
- `MINIO_ROOT_PASSWORD` = the secret key
- `MINIO_BUCKET` = `mmap-uploads`
- `MINIO_SECURE` = `true`

### 1d. Vector store (Qdrant Cloud)

1. Sign up at <https://cloud.qdrant.io>, create a free 1 GB cluster.
2. Copy the cluster URL (`https://<id>.<region>.aws.cloud.qdrant.io`) and the
   generated API key.
3. Map to:
   - `QDRANT_URL` = the full https URL
   - `QDRANT_API_KEY` = the cluster key

### 1e. Graph store (Neo4j AuraDB)

1. Sign up at <https://console.neo4j.io>, create a free AuraDB instance.
2. Download the credentials file — it contains the bolt+s URI and the
   generated password.
3. Map to:
   - `NEO4J_URI` = `neo4j+s://<id>.databases.neo4j.io`
   - `NEO4J_USER` = `neo4j` (default)
   - `NEO4J_PASSWORD` = from the credentials file

### 1f. LLM keys

- Groq: <https://console.groq.com> → `GROQ_API_KEY`
- OpenRouter: <https://openrouter.ai> → `OPENROUTER_API_KEY`

---

## 2. Deploy the backend (Fly)

```bash
cd backend
fly apps create mmap-backend

# Set every secret at once. Replace the placeholder values with the strings
# you collected in section 1.
fly secrets set --app mmap-backend \
  JWT_SECRET="$(openssl rand -base64 48)" \
  BACKEND_CORS_ORIGINS="https://mmap.vercel.app" \
  DATABASE_URL="postgresql+asyncpg://USER:PASS@HOST/DB?ssl=require" \
  REDIS_HOST="HOST" REDIS_PORT="6379" \
  REDIS_PASSWORD="TOKEN" REDIS_SECURE="true" \
  QDRANT_URL="https://CLUSTER.aws.cloud.qdrant.io" \
  QDRANT_API_KEY="KEY" \
  NEO4J_URI="neo4j+s://ID.databases.neo4j.io" \
  NEO4J_USER="neo4j" NEO4J_PASSWORD="PASS" \
  MINIO_ENDPOINT="fly.storage.tigris.dev" \
  MINIO_ROOT_USER="ACCESS" MINIO_ROOT_PASSWORD="SECRET" \
  MINIO_BUCKET="mmap-uploads" MINIO_SECURE="true" \
  GROQ_API_KEY="..." OPENROUTER_API_KEY="..."

fly deploy --config fly.toml
```

The container's `entrypoint.sh` runs `alembic upgrade head` on every boot,
so the Neon schema migrates itself on first deploy.

Smoke-test:

```bash
curl -sf https://mmap-backend.fly.dev/api/v1/health
```

## 3. Deploy the worker (Fly)

```bash
cd backend
fly apps create mmap-worker

# Reuse the same secrets — worker needs every cloud connection too.
fly secrets set --app mmap-worker \
  $(fly secrets list --app mmap-backend --json | jq -r '.[].Name' | \
    while read k; do printf '%s="%s" ' "$k" "$(fly ssh console -a mmap-backend -C "printenv $k" 2>/dev/null)"; done)
# ↑ if that one-liner is too clever, just paste the same `fly secrets set`
#   block from section 2 with --app mmap-worker swapped in.

fly deploy --config fly.worker.toml
```

Watch the first deploy — it has to download `BAAI/bge-small-en-v1.5` from
Hugging Face before it can process uploads (~100 MB; the prod image bakes
it in already, but the first job confirms it's hot).

## 4. Deploy the frontend (Vercel)

```bash
cd frontend
vercel link                       # connect this directory to a Vercel project
vercel env add NEXT_PUBLIC_API_URL production
# → enter: https://mmap-backend.fly.dev
vercel --prod
```

Vercel auto-detects Next.js 16 (App Router) and uses `next build`. The
existing `output: "standalone"` in `next.config.ts` is a no-op on Vercel
but stays in place for self-hosted images.

## 5. Wire CORS + verify the round-trip

Once Vercel gives you the production URL (e.g.
`https://mmap.vercel.app`), update the backend's CORS allowlist:

```bash
fly secrets set --app mmap-backend \
  BACKEND_CORS_ORIGINS="https://mmap.vercel.app"
fly machines restart --app mmap-backend
```

End-to-end check:

1. Visit `https://mmap.vercel.app` → register an account.
2. Upload a small `.txt` from `backend/evals/corpus/` → wait for `processed`.
3. Ask a chat question that targets the doc.
4. Confirm the answer cites the uploaded doc and that the verification
   verdict is `verified` or `partial`.

---

## Production checklist

Before pointing anything real at this:

- [ ] `JWT_SECRET` is from `openssl rand -base64 48`, not the dev default
- [ ] `BACKEND_CORS_ORIGINS` is exactly your frontend origin — no `*`
- [ ] Postgres connection uses `?ssl=require`
- [ ] Redis is `rediss://` (TLS) with `REDIS_SECURE=true`
- [ ] Qdrant cluster is region-matched to the Fly primary region for latency
- [ ] AuraDB instance is on the same continent as the Fly region
- [ ] `fly secrets list` shows no plaintext values you'd be unhappy to leak
- [ ] `fly logs --app mmap-backend` is clean on first health check after deploy
- [ ] First `/api/v1/chat` round-trip returns 200 with citations

---

## Rolling back

```bash
fly releases --app mmap-backend            # list deploys
fly releases rollback v123 --app mmap-backend
```

Frontend rollback is one click in the Vercel dashboard → Deployments → the
previous deploy → **Promote to Production**.

## Tear-down

```bash
fly apps destroy mmap-backend
fly apps destroy mmap-worker
fly redis destroy mmap-redis
fly storage destroy mmap-uploads
# Neon, Qdrant Cloud, Aura: delete from their respective web consoles.
vercel project rm mmap
```
