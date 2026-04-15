from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ConnectionCreate(BaseModel):
    name: str
    host: str | None = None
    port: int | None = 5258
    database_name: str | None = None
    description: str | None = None
    schema_ddl: str | None = None


class ConnectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    schema_ddl: str | None = None
    is_active: bool | None = None


class ConnectionResponse(BaseModel):
    id: str
    name: str
    host: str | None
    port: int | None
    database_name: str | None
    description: str | None
    is_active: bool
    has_schema: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj) -> "ConnectionResponse":
        return cls(
            id=obj.id,
            name=obj.name,
            host=obj.host,
            port=obj.port,
            database_name=obj.database_name,
            description=obj.description,
            is_active=obj.is_active,
            has_schema=bool(obj.schema_ddl),
            created_at=obj.created_at,
        )
