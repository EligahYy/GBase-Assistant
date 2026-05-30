"""Tests for Semantic Mapper tools — glossary loading and matching."""
import pytest
from app.agents.semantic_mapper import (
    load_glossary,
    _match_glossary_term,
    build_semantic_mapper_tools,
)


class TestGlossaryLoading:
    def test_load_empty_glossary(self, tmp_path):
        glossary_path = tmp_path / "glossary.yaml"
        glossary_path.write_text("terms: {}", encoding="utf-8")
        glossary = load_glossary(str(glossary_path))
        assert glossary == {}

    def test_load_glossary_with_terms(self, tmp_path):
        glossary_path = tmp_path / "glossary.yaml"
        glossary_path.write_text("""
terms:
  销售额:
    table: product_sale
    column: pay_amount
    synonyms: [销售金额, 营收]
        """, encoding="utf-8")
        glossary = load_glossary(str(glossary_path))
        assert "销售额" in glossary
        assert glossary["销售额"]["table"] == "product_sale"
        assert "销售金额" in glossary["销售额"]["synonyms"]


class TestGlossaryMatching:
    def test_exact_match(self):
        glossary = {"销售额": {"table": "sale", "column": "amount", "synonyms": []}}
        result = _match_glossary_term("查询销售额", glossary)
        assert len(result) == 1
        assert result[0]["term"] == "销售额"
        assert result[0]["table"] == "sale"

    def test_synonym_match(self):
        glossary = {"销售额": {"table": "sale", "column": "amount", "synonyms": ["营收", "收入"]}}
        result = _match_glossary_term("查询本月营收", glossary)
        assert len(result) == 1
        assert result[0]["term"] == "销售额"

    def test_no_match(self):
        glossary = {"销售额": {"table": "sale", "column": "amount", "synonyms": []}}
        result = _match_glossary_term("查询用户列表", glossary)
        assert result == []

    def test_substring_not_matched(self):
        """Verify that '销售' does not match glossary key '销售额渠道'."""
        glossary = {"销售额渠道": {"table": "sale", "column": "channel", "synonyms": []}}
        result = _match_glossary_term("销售额", glossary)
        assert result == []


class TestToolBuilder:
    def test_build_tools_returns_list(self):
        tools = build_semantic_mapper_tools({"test": {"table": "t", "column": "c", "synonyms": []}}, "test_db")
        assert len(tools) == 4

    def test_build_tools_with_empty_glossary(self):
        tools = build_semantic_mapper_tools({}, "test_db")
        assert len(tools) == 4
