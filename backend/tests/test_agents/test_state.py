"""AgentState 单元测试。"""

from app.agents.state import AgentStateType


class TestAgentState:
    def test_minimal_state_creation(self):
        """AgentState 应能用最小字段创建。"""
        state = AgentStateType(
            messages=[],
            conversation_id="test-conv-1",
            model="deepseek/deepseek-chat",
        )
        assert state["conversation_id"] == "test-conv-1"
        assert state["model"] == "deepseek/deepseek-chat"
        assert state["messages"] == []

    def test_sql_path_state(self):
        """SQL 路径相关字段应可设置。"""
        state = AgentStateType(
            messages=[{"role": "user", "content": "查询订单"}],
            intent="sql",
            db_connection_id="conn-1",
            conversation_id="test-conv-2",
            model="deepseek/deepseek-chat",
        )
        assert state["intent"] == "sql"
        assert state["db_connection_id"] == "conn-1"
        assert state.get("grounding") is None
        assert state.get("generated_sql") is None

    def test_grounding_fields(self):
        """Grounding 相关字段应独立存在。"""
        grounding = {
            "tables": ["order_main", "product"],
            "columns": {"order_main": ["order_amount", "order_time"], "product": ["name"]},
            "join_paths": ["order_main.product_code = product.product_code"],
            "confidence": 0.92,
        }
        state = AgentStateType(
            messages=[],
            intent="sql",
            grounding=grounding,
            conversation_id="c1",
            model="m1",
        )
        assert state["grounding"]["tables"] == ["order_main", "product"]
        assert state["grounding"]["confidence"] == 0.92

    def test_fields_have_no_defaults_for_optional(self):
        """total=False 意味着所有字段可选，未设置时 get 返回 None。"""
        state = AgentStateType(
            messages=[],
            conversation_id="c1",
            model="m1",
        )
        assert state.get("intent") is None
        assert state.get("generated_sql") is None
        assert state.get("query_result") is None
