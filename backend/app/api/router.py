from fastapi import APIRouter

from app.api import chat, connections, health, models

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(connections.router)
api_router.include_router(models.router)
