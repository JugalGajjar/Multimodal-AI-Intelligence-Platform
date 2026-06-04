---
title: MMAP Worker
emoji: 🤖
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Background worker (OCR, embedding, graph extraction)
---

# MMAP Worker

arq background worker that processes documents enqueued by the MMAP API:
text extraction (RapidOCR / Tesseract / Whisper / vision LLM), chunking,
embedding into Qdrant, and entity/relation extraction into Neo4j.

Exposes a tiny health endpoint at `GET /` on port 7860. HF Spaces requires
a listening port; the rest of the container is the arq event loop.
