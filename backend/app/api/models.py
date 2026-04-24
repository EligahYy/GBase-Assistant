"""Model configuration API: expose available models from models.yaml."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/models", tags=["models"])


class ModelInfo(BaseModel):
    id: str
    name: str
    task_type: str
    primary: bool = False


@router.get("", response_model=list[ModelInfo])
async def list_models():
    """Return all available models from config."""
    settings = get_settings()
    cfg = settings.models_config
    models_cfg = cfg.get("models", {})

    result: list[ModelInfo] = []
    seen: set[str] = set()

    for task_type, task_cfg in models_cfg.items():
        primary = task_cfg.get("primary", "")
        if primary and primary not in seen:
            seen.add(primary)
            result.append(ModelInfo(
                id=primary,
                name=primary.split("/")[-1].replace("-", " ").title(),
                task_type=task_type,
                primary=True,
            ))
        for fallback in task_cfg.get("fallback", []):
            if fallback not in seen:
                seen.add(fallback)
                result.append(ModelInfo(
                    id=fallback,
                    name=fallback.split("/")[-1].replace("-", " ").title(),
                    task_type=task_type,
                    primary=False,
                ))

    return result
