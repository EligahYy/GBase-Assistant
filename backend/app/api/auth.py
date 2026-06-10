"""Shared authorization dependencies for management APIs."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request

from app.config import get_settings


def require_admin(request: Request) -> None:
    """Require X-Admin-Token, allowing tokenless access only in debug mode."""
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token:
        if get_settings().debug:
            return
        raise HTTPException(status_code=403, detail="需要管理权限")
    if request.headers.get("X-Admin-Token", "") != admin_token:
        raise HTTPException(status_code=403, detail="需要管理权限")
