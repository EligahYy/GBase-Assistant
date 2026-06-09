from fastapi import APIRouter

from app.api import admin, chat, connections, health, knowledge, models, semantic_models, tools

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(connections.router)
api_router.include_router(models.router)
api_router.include_router(tools.router)
api_router.include_router(admin.router)
api_router.include_router(knowledge.router)
api_router.include_router(semantic_models.router)
