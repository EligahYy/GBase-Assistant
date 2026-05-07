from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConnectionCreate(BaseModel):
    name: str
    host: str | None = None
    port: int | None = 5258
    database_name: str | None = None
    username: str | None = None
    password: str | None = None
    driver_type: str = "manual"
    description: str | None = None
    schema_ddl: str | None = None


class ConnectionUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    password: str | None = None
    driver_type: str | None = None
    description: str | None = None
    schema_ddl: str | None = None
    is_active: bool | None = None


class TableSchemaResponse(BaseModel):
    table_name: str
    columns: list[str]
    ddl: str
    description: str = ""


class ConnectionResponse(BaseModel):
    id: str
    name: str
    host: str | None
    port: int | None
    database_name: str | None
    username: str | None
    driver_type: str
    connection_tested: bool
    last_synced_at: datetime | None
    description: str | None
    is_active: bool
    has_schema: bool
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj) -> ConnectionResponse:
        return cls(
            id=obj.id,
            name=obj.name,
            host=obj.host,
            port=obj.port,
            database_name=obj.database_name,
            username=obj.username,
            driver_type=obj.driver_type,
            connection_tested=obj.connection_tested,
            last_synced_at=obj.last_synced_at,
            description=obj.description,
            is_active=obj.is_active,
            has_schema=bool(obj.schema_ddl),
            created_at=obj.created_at,
        )


class TestConnectionResponse(BaseModel):
    status: str
    message: str
    driver: str


class SyncSchemaResponse(BaseModel):
    tables: int
    synced_at: datetime


class QueryRequest(BaseModel):
    sql: str = Field(..., min_length=1)
    max_rows: int | None = Field(1000, ge=1, le=5000)


class QueryResultResponse(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int
    execution_time_ms: float
    truncated: bool
