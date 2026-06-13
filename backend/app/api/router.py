from fastapi import APIRouter

from app.api import health, metrics
from app.auth.router import router as auth_router
from app.chats.router import router as chats_router
from app.documents.router import router as documents_router
from app.graph.router import router as graph_router
from app.rag.router import router as chat_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(metrics.router)
api_router.include_router(auth_router)
api_router.include_router(documents_router)
api_router.include_router(chat_router)
api_router.include_router(chats_router)
api_router.include_router(graph_router)
