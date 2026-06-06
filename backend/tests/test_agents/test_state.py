"""AgentState 单元测试 — v3 namespace-isolated state."""

from app.agents.state import AgentState, SupervisorState, SQLAgentState, KnowledgeAgentState


class TestAgentState:
    def test_minimal_state_creation(self):
        """AgentState 应能用最小字段创建。"""
        state = AgentState(
            messages=[],
            conversation_id="test-conv-1",
            model="deepseek/deepseek-chat",
            supervisor={},
            sql={},
            knowledge={},
        )
        assert state["conversation_id"] == "test-conv-1"
        assert state["model"] == "deepseek/deepseek-chat"
        assert state["messages"] == []

    def test_supervisor_state(self):
        """Supervisor 子状态应可设置。"""
        state = AgentState(
            messages=[],
            conversation_id="test-1",
            model="m1",
            supervisor={"delegated_agent": "sql_agent"},
            sql={},
            knowledge={},
        )
        assert state["supervisor"]["delegated_agent"] == "sql_agent"

    def test_sql_agent_state(self):
        """SQL Agent 子状态应可设置。"""
        state = AgentState(
            messages=[],
            conversation_id="test-1",
            model="m1",
            supervisor={},
            sql={"generated_sql": "SELECT 1", "query_result": {"rows": []}},
            knowledge={},
            db_connection_id="conn-1",
        )
        assert state["sql"]["generated_sql"] == "SELECT 1"
        assert state["db_connection_id"] == "conn-1"

    def test_fields_have_no_defaults_for_optional(self):
        """total=False 意味着所有字段可选，未设置时 get 返回 None。"""
        state = AgentState(
            messages=[],
            conversation_id="c1",
            model="m1",
            supervisor={},
            sql={},
            knowledge={},
        )
        assert state.get("final_response") is None
        assert state.get("history") is None
