"""Orchestrator Agent 单元测试。"""

import pytest
from app.agents.state import AgentStateType
from app.agents.orchestrator import classify_intent_v2, route_after_intent


class TestClassifyIntentV2:
    def test_sql_keywords_map_to_sql_intent(self):
        """包含查询关键词的文本应映射为 sql intent。"""
        assert classify_intent_v2("查询所有订单") == "sql"
        assert classify_intent_v2("统计上个月的销售额") == "sql"
        assert classify_intent_v2("列出最近30天的数据") == "sql"
        assert classify_intent_v2("分析各部门绩效") == "sql"

    def test_qa_keywords_map_to_qa_intent(self):
        """包含知识问答关键词的文本应映射为 qa intent。"""
        assert classify_intent_v2("GBase 8a 支持窗口函数吗") == "qa"
        assert classify_intent_v2("怎么创建分布表") == "qa"
        assert classify_intent_v2("错误码 1001 是什么意思") == "qa"

    def test_general_fallback(self):
        """无特殊关键词的文本应映射为 general intent。"""
        assert classify_intent_v2("你好") == "general"
        assert classify_intent_v2("今天天气不错") == "general"
        assert classify_intent_v2("你会唱歌吗") == "general"

    def test_mixed_keywords_prioritize_sql(self):
        """同时包含 SQL 和 QA 关键词时，SQL 优先。"""
        assert classify_intent_v2("查询怎么建表") == "sql"


class TestRouteAfterIntent:
    def test_sql_intent_routes_to_semantic_mapper(self):
        state = AgentStateType(
            messages=[],
            intent="sql",
            conversation_id="c1",
            model="m1",
        )
        assert route_after_intent(state) == "semantic_mapper"

    def test_qa_intent_routes_to_knowledge_specialist(self):
        state = AgentStateType(
            messages=[],
            intent="qa",
            conversation_id="c1",
            model="m1",
        )
        assert route_after_intent(state) == "knowledge_specialist"

    def test_general_intent_routes_to_general_specialist(self):
        state = AgentStateType(
            messages=[],
            intent="general",
            conversation_id="c1",
            model="m1",
        )
        assert route_after_intent(state) == "general_specialist"

    def test_clarify_intent_routes_to_response_formatter(self):
        state = AgentStateType(
            messages=[],
            intent="clarify",
            conversation_id="c1",
            model="m1",
        )
        assert route_after_intent(state) == "response_formatter"

    def test_missing_intent_defaults_to_general(self):
        """未设置 intent 时应默认 general。"""
        state = AgentStateType(
            messages=[],
            conversation_id="c1",
            model="m1",
        )
        assert route_after_intent(state) == "general_specialist"
