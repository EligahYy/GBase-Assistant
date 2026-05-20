# backend/tests/test_grep_retriever.py
from __future__ import annotations

import pytest
from app.vector.grep_retriever import QueryRouter


class TestQueryRouter:
    def test_classifies_four_digit_error_code_as_precise(self):
        assert QueryRouter.classify("错误码 1040 是什么意思") == "precise"

    def test_classifies_error_code_with_label_as_precise(self):
        assert QueryRouter.classify("报错 1146 怎么解决") == "precise"

    def test_classifies_sql_keyword_as_precise(self):
        assert QueryRouter.classify("SELECT 语句怎么写") == "precise"
        assert QueryRouter.classify("CREATE TABLE 语法") == "precise"
        assert QueryRouter.classify("INSERT INTO 怎么用") == "precise"

    def test_classifies_backtick_identifier_as_precise(self):
        assert QueryRouter.classify("`max_allowed_packet` 参数") == "precise"

    def test_classifies_gbase_tool_as_precise(self):
        assert QueryRouter.classify("gccli 连接参数") == "precise"
        assert QueryRouter.classify("gcluster 是什么") == "precise"

    def test_classifies_param_query_as_precise(self):
        assert QueryRouter.classify("参数 max_connections 默认值") == "precise"
        assert QueryRouter.classify("配置项 wait_timeout 怎么调整") == "precise"

    def test_classifies_natural_language_as_semantic(self):
        assert QueryRouter.classify("GBase 8a 支持触发器吗") == "semantic"
        assert QueryRouter.classify("怎么优化查询性能") == "semantic"
        assert QueryRouter.classify("分布键应该怎么选") == "semantic"

    def test_classifies_english_question_as_semantic(self):
        assert QueryRouter.classify("how to optimize query performance") == "semantic"

    def test_empty_query_returns_semantic(self):
        assert QueryRouter.classify("") == "semantic"
