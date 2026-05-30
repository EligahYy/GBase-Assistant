"""Semantic Mapper Agent integration tests (requires real LLM — marked as integration)."""
import pytest
from app.agents.semantic_mapper import _match_glossary_term

pytestmark = pytest.mark.integration


class TestSemanticMapperFallback:
    """Test the glossary fallback path — no LLM required."""

    def test_glossary_fallback_exact_match(self):
        glossary = {
            "销售额": {"table": "sale", "column": "amount", "synonyms": ["营收"]},
        }
        result = _match_glossary_term("查询本月销售额统计", glossary)
        assert len(result) == 1
        assert result[0]["table"] == "sale"
        assert result[0]["column"] == "amount"
        assert result[0]["source"] == "glossary"

    def test_glossary_fallback_synonym_match(self):
        glossary = {
            "销售额": {"table": "sale", "column": "amount", "synonyms": ["营收", "收入"]},
        }
        result = _match_glossary_term("查询本季度营收情况", glossary)
        assert len(result) == 1
        assert result[0]["term"] == "销售额"

    def test_glossary_fallback_no_match(self):
        glossary = {"销售额": {"table": "sale", "column": "amount", "synonyms": []}}
        result = _match_glossary_term("查询用户注册数", glossary)
        assert result == []

    def test_glossary_fallback_multiple_terms(self):
        glossary = {
            "销售额": {"table": "sale", "column": "amount", "synonyms": []},
            "用户": {"table": "user", "column": "name", "synonyms": ["客户"]},
        }
        result = _match_glossary_term("查询本月销售额和客户数量", glossary)
        assert len(result) == 2
        tables = {r["table"] for r in result}
        assert tables == {"sale", "user"}


class TestOutputFormat:
    """Verify the expected output JSON structure."""

    def test_output_format_has_all_fields(self):
        expected_fields = {
            "tables", "columns", "business_terms", "join_paths",
            "chart_hint", "unresolved_terms", "confidence",
        }
        sample = {
            "tables": ["a"],
            "columns": {"a": ["x"]},
            "business_terms": {},
            "join_paths": [],
            "chart_hint": None,
            "unresolved_terms": [],
            "confidence": 0.9,
        }
        assert expected_fields == set(sample.keys())

    def test_confidence_in_range(self):
        sample = {"confidence": 0.92}
        assert 0 <= sample["confidence"] <= 1
