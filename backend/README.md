# MMAP Backend

FastAPI backend for the Multimodal AI Intelligence Platform.

## Local dev

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Tests

```bash
pytest
```

## Docker

Built and run via root `docker-compose.yml`.
