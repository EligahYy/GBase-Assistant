"""API integration tests with in-memory SQLite."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import create_app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(TEST_DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with async_session() as session:
        yield session


app = create_app()
app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
async def setup_database():
    import app.models.connection  # noqa: F401
    import app.models.conversation  # noqa: F401
    import app.models.message  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


class TestHealthAPI:
    def test_health_check(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestConnectionAPI:
    def test_create_connection(self):
        response = client.post("/api/connections", json={
            "name": "Test DB",
            "host": "localhost",
            "database_name": "test",
            "schema_ddl": "CREATE TABLE users (id INT, name VARCHAR(20));"
        })
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test DB"
        assert "id" in data

    def test_list_connections(self):
        client.post("/api/connections", json={"name": "DB1", "host": "h1"})
        client.post("/api/connections", json={"name": "DB2", "host": "h2"})
        response = client.get("/api/connections")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2

    def test_update_connection(self):
        create_resp = client.post("/api/connections", json={"name": "Old", "host": "h1"})
        conn_id = create_resp.json()["id"]
        response = client.patch(f"/api/connections/{conn_id}", json={"name": "New"})
        assert response.status_code == 200
        get_resp = client.get(f"/api/connections/{conn_id}")
        assert get_resp.json()["name"] == "New"

    def test_delete_connection(self):
        create_resp = client.post("/api/connections", json={"name": "ToDelete", "host": "h1"})
        conn_id = create_resp.json()["id"]
        response = client.delete(f"/api/connections/{conn_id}")
        assert response.status_code == 204
        get_resp = client.get(f"/api/connections/{conn_id}")
        # Soft delete: still retrievable but not in list
        get_resp = client.get(f"/api/connections/{conn_id}")
        assert get_resp.status_code == 200
        list_resp = client.get("/api/connections")
        assert conn_id not in [c["id"] for c in list_resp.json()]
class TestConversationAPI:
    def test_create_conversation_via_chat(self):
        response = client.post("/api/chat", json={
            "message": "查询用户",
            "db_connection_id": None,
            "conversation_id": None,
            "model": None,
        })
        assert response.status_code == 200
        data = response.json()
        assert "conversation_id" in data
        assert "message" in data

    def test_list_conversations(self):
        client.post("/api/chat", json={"message": "msg1"})
        client.post("/api/chat", json={"message": "msg2"})
        response = client.get("/api/chat/conversations")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_get_conversation(self):
        chat_resp = client.post("/api/chat", json={"message": "test msg"})
        conv_id = chat_resp.json()["conversation_id"]
        response = client.get(f"/api/chat/conversations/{conv_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == conv_id
        assert len(data["messages"]) >= 2

    def test_update_conversation(self):
        chat_resp = client.post("/api/chat", json={"message": "test"})
        conv_id = chat_resp.json()["conversation_id"]
        response = client.patch(f"/api/chat/conversations/{conv_id}", json={"title": "New Title"})
        assert response.status_code == 200
        get_resp = client.get(f"/api/chat/conversations/{conv_id}")
        assert get_resp.json()["title"] == "New Title"

    def test_delete_conversation(self):
        chat_resp = client.post("/api/chat", json={"message": "to delete"})
        conv_id = chat_resp.json()["conversation_id"]
        response = client.delete(f"/api/chat/conversations/{conv_id}")
        assert response.status_code == 200
        get_resp = client.get(f"/api/chat/conversations/{conv_id}")
        assert get_resp.status_code == 404
