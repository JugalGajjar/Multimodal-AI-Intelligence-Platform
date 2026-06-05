"""Push values from .env.prod to a Hugging Face Space.

API keys / passwords → Secrets (encrypted).
Hosts / ports / model names → Variables (visible in build logs).

    HF_TOKEN=hf_... python scripts/push_space_secrets.py <user>/<space>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from huggingface_hub import HfApi

SECRETS = {
    "JWT_SECRET",
    "DATABASE_URL",
    "REDIS_PASSWORD",
    "QDRANT_API_KEY",
    "NEO4J_PASSWORD",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
}

VARIABLES = {
    "APP_ENV",
    "APP_DEBUG",
    "BACKEND_HOST",
    "BACKEND_PORT",
    "BACKEND_CORS_ORIGINS",
    "JWT_ALGORITHM",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_SECURE",
    "QDRANT_URL",
    "NEO4J_URI",
    "NEO4J_USER",
    "MINIO_ENDPOINT",
    "MINIO_BUCKET",
    "MINIO_SECURE",
    "GROQ_WHISPER_MODEL",
    "GROQ_REASONING_MODEL",
    "GROQ_EXTRACTION_MODEL",
    "OPENROUTER_VISION_MODEL",
    "OPENROUTER_REASONING_MODEL",
    "OTEL_ENABLED",
    "OTEL_SERVICE_NAME",
}


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.split("#", 1)[0].strip().strip('"').strip("'")
        out[key.strip()] = val
    return out


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: push_space_secrets.py <user>/<space>", file=sys.stderr)
        return 1
    space_id = sys.argv[1]
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("error: HF_TOKEN not set", file=sys.stderr)
        return 1

    env_path = Path(".env.prod")
    if not env_path.exists():
        print("error: .env.prod not found in the current directory", file=sys.stderr)
        return 1

    env = parse_env(env_path)
    api = HfApi(token=token)

    pushed_s: list[str] = []
    pushed_v: list[str] = []
    skipped: list[str] = []
    for k in sorted(env):
        v = env[k]
        if not v:
            skipped.append(f"{k}(empty)")
            continue
        if k in SECRETS:
            api.add_space_secret(space_id, key=k, value=v)
            pushed_s.append(k)
        elif k in VARIABLES:
            api.add_space_variable(space_id, key=k, value=v)
            pushed_v.append(k)
        else:
            skipped.append(f"{k}(not in scope)")

    print(f"→ {space_id}")
    print(f"  {len(pushed_s):>2} secrets  : {', '.join(pushed_s)}")
    print(f"  {len(pushed_v):>2} variables: {', '.join(pushed_v)}")
    if skipped:
        print(f"  {len(skipped):>2} skipped  : {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
