"""AgentState namespace contracts."""

from app.agents.state import AgentState


def test_agent_state_supports_collaboration_namespaces():
    state = AgentState(
        messages=[],
        supervisor={"pending_tasks": [{"type": "sql", "query": "查询订单"}]},
        sql={"generated_sql": "SELECT 1", "phase": "proposed"},
        knowledge={"knowledge_sources": ["manual"]},
        db_connection_id="conn-1",
    )

    assert state["supervisor"]["pending_tasks"][0]["type"] == "sql"
    assert state["sql"]["generated_sql"] == "SELECT 1"
    assert state["knowledge"]["knowledge_sources"] == ["manual"]
