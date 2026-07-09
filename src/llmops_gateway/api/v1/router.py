from fastapi import APIRouter

from llmops_gateway.api.v1 import admin, chat, embeddings, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(embeddings.router)
api_router.include_router(admin.router)
