"""v3.4 Semantic NL2SQL Graph — structured pipeline with bounded repair.

Graph flow:
  START → resolve → build_context → plan_query → generate_sql → verify
    → [repairable] → refine_sql → verify (bounded loop)
    → execute → build_answer → END
    → [fatal] → fail_answer → END
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.agents.state import AgentState
from app.gateway.ag_ui_encoder import EventEncoder
from app.llm.adapter import LiteLLMChatAdapter

logger = logging.getLogger(__name__)

# ── Repair budget ──
MAX_SQL_CANDIDATES = 4
MAX_SQL_EXECUTIONS = 2
MAX_SAME_ERROR_RETRIES = 2

# ── Semantic SQL Generator prompt ──
SQL_GENERATOR_PROMPT = """你是 GBase 8a SQL 生成专家。根据以下结构化信息生成精确的 SQL。

## 输入
1. 用户问题
2. Query IR（结构化查询计划）
3. FocusedSchema（只包含相关表和列）
4. GBase 8a 方言规则

## 规则
1. **只使用 FocusedSchema 中的表和列**。不要引用超出范围的表或列。
2. **忠实实现 Query IR**：
   - 每个 metric 必须在 SELECT 中出现
   - 每个 dimension 必须在 SELECT 和 GROUP BY 中出现
   - 每个 filter 必须在 WHERE 中出现
   - time_range 必须作为 WHERE 条件
3. **方言约束**：
   - 只支持 SELECT/SHOW/DESCRIBE/EXPLAIN
   - 字符串连接: CONCAT()
   - 日期运算: CURDATE() - INTERVAL 1 MONTH
   - LIMIT 语法: LIMIT n OFFSET m
   - 不支持 WITH RECURSIVE, FULL OUTER JOIN
   - GROUP_CONCAT 而非 STRING_AGG
4. 只输出 SQL，不要任何解释。
"""

# ── Answer builder prompt ──
ANSWER_BUILDER_PROMPT = """你是 GBase 8a 助手。基于查询结果和取数逻辑向用户总结最终回答。

## 输出格式
1. 先用一到三句话总结关键结论、对比或趋势
2. 不要输出 markdown 表格、逐行数据清单、JSON 或 SQL；查询结果会由界面单独展示
3. 数据量较多时，只总结最重要的发现，不要复述全部数据
4. 附上简洁的"取数逻辑"说明:
   - 指标: ...
   - 维度: ...
   - 过滤: ...
   - 时间范围: ...
   - 关联: ...
5. 中文回答，专业友好
6. 如果查询结果为空，说明可能原因
7. 如果查询失败，诚实说明并提供建议
8. 不得声称结果已排序、过滤、分组或限制条数，除非取数逻辑或 SQL 明确包含对应操作

## 取数逻辑
{semantic_logic}

## 查询结果
{query_result}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _emit(key: str, value: Any) -> None:
    try:
        get_stream_writer()([{key: value}])
    except RuntimeError:
        pass


async def _call_llm(model: Any, messages: list[BaseMessage]) -> AIMessage:
    if hasattr(model, "_agenerate"):
        result = await model._agenerate(messages)
        if result.generations and result.generations[0]:
            return result.generations[0].message
        return AIMessage(content="")
    else:
        dict_msgs = []
        for m in messages:
            role = "system" if isinstance(m, SystemMessage) else "user"
            if hasattr(m, "type"):
                role = "assistant" if m.type == "ai" else ("system" if m.type == "system" else "user")
            dict_msgs.append({"role": role, "content": str(m.content)})
        content, _, _ = await model.llm_client.complete(dict_msgs, tools=None)
        return AIMessage(content=content or "")


def _to_llm_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    result = []
    for message in messages:
        role = "assistant" if message.type == "ai" else ("system" if message.type == "system" else "user")
        result.append({"role": role, "content": str(message.content)})
    return result


async def _stream_llm_text(model: Any, messages: list[BaseMessage]) -> AsyncIterator[str]:
    """Stream plain text when supported, with a non-streaming adapter fallback."""
    llm_client = getattr(model, "llm_client", None)
    if llm_client is not None and hasattr(llm_client, "stream"):
        async for chunk in llm_client.stream(_to_llm_messages(messages)):
            if chunk:
                yield chunk
        return

    response = await _call_llm(model, messages)
    content = str(response.content or "")
    if content:
        yield content


def _build_conversation_messages(history: list[dict], current_message: str) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in history:
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        role = item.get("role")
        messages.append(AIMessage(content=content) if role == "assistant" else HumanMessage(content=content))
    if not messages or not isinstance(messages[-1], HumanMessage) or messages[-1].content != current_message:
        messages.append(HumanMessage(content=current_message))
    return messages


# ═══════════════════════════════════════════════════════════════════════════════
# Graph nodes
# ═══════════════════════════════════════════════════════════════════════════════


async def _resolve_conversation_node(state: dict) -> dict:
    """Resolve conversation context — merge multi-turn references."""
    _emit("step_started", {"agent_name": "resolve", "phase": "resolve"})
    msgs = state.get("messages", [])
    question = ""
    for m in reversed(msgs):
        if isinstance(m, HumanMessage):
            question = str(m.content) if hasattr(m, "content") else str(m)
            break
    _emit("step_finished", {"agent_name": "resolve", "phase": "resolve"})
    return {"resolved_question": question}


async def _build_context_node(state: dict) -> dict:
    """Build semantic context from the question + database."""
    _emit("step_started", {"agent_name": "context", "phase": "context"})
    _emit("thinking_start", {})
    _emit("thinking_delta", "分析语义上下文...")
    _emit("thinking_end", {})

    question = state.get("resolved_question", "")
    db_id = state.get("db_connection_id", "")

    from app.database import async_session_factory
    from app.semantic.context_builder import SemanticContextBuilder

    async with async_session_factory() as session:
        builder = SemanticContextBuilder(session)
        ctx = await builder.build(question, db_id)

    _emit("step_finished", {"agent_name": "context", "phase": "context"})
    return {"semantic_context": ctx}


async def _plan_query_node(state: dict) -> dict:
    """Plan query — convert NL + SemanticContext → Query IR."""
    _emit("step_started", {"agent_name": "plan", "phase": "plan"})
    _emit("thinking_start", {})
    _emit("thinking_delta", "规划查询结构...")
    _emit("thinking_end", {})

    ctx = state.get("semantic_context")
    question = state.get("resolved_question", "")

    from app.dependencies import get_llm_client
    from app.semantic.planner import QueryPlanner, QueryPlanningError

    llm_client = get_llm_client(task_type="default")
    planner = QueryPlanner(llm_client)
    try:
        query_ir = await planner.plan(question, ctx)
    except QueryPlanningError as exc:
        _emit("step_finished", {"agent_name": "plan", "phase": "plan"})
        return {"planning_error": str(exc), "should_clarify": False}

    _emit("step_finished", {"agent_name": "plan", "phase": "plan"})

    # If unresolved ambiguities, route to clarification
    should_clarify = bool(query_ir.unresolved)
    return {"query_ir": query_ir.to_dict(), "should_clarify": should_clarify}


async def _generate_sql_node(state: dict) -> dict:
    """Generate SQL from Query IR + FocusedSchema."""
    _emit("step_started", {"agent_name": "sql_gen", "phase": "sql_gen"})
    _emit("thinking_start", {})
    _emit("thinking_delta", "生成 GBase 8a SQL...")
    _emit("thinking_end", {})

    ctx = state.get("semantic_context")
    query_ir_dict = state.get("query_ir", {})
    question = state.get("resolved_question", "")

    # Build prompt context
    focused_desc = ""
    if ctx and hasattr(ctx, "focused_schema"):
        for t in ctx.focused_schema:
            focused_desc += f"\n表 {t.name}: "
            focused_desc += ", ".join(f"{c['name']}({c.get('type', '')})" for c in t.columns)

    verified_examples = ""
    if ctx and hasattr(ctx, "verified_examples") and ctx.verified_examples:
        for ex in ctx.verified_examples[:2]:
            verified_examples += f"\nQ: {ex.question}\nSQL: {ex.sql}\n"

    verified_joins = ""
    if ctx and hasattr(ctx, "verified_joins") and ctx.verified_joins:
        verified_joins = "\n".join(
            f"- {join.left_table} ↔ {join.right_table}: {join.condition}" for join in ctx.verified_joins
        )

    prompt = f"""{SQL_GENERATOR_PROMPT}

## 用户问题
{question}

## Query IR
{json.dumps(query_ir_dict, ensure_ascii=False, indent=2)}

## FocusedSchema
{focused_desc}
## Verified JOINs
{verified_joins or "（无可信 JOIN，禁止生成 JOIN）"}
{"## Verified Examples" + verified_examples if verified_examples else ""}

请生成 SQL:"""

    from app.dependencies import get_llm_client
    from app.llm.adapter import LiteLLMChatAdapter

    llm = LiteLLMChatAdapter(get_llm_client(task_type="sql_generation"))
    response = await _call_llm(llm, [HumanMessage(content=prompt)])
    sql = (response.content or "").strip()
    # Strip markdown fences
    if sql.startswith("```"):
        sql = "\n".join(sql.split("\n")[1:])
    if sql.endswith("```"):
        sql = sql[:-3]
    sql = sql.strip()

    _emit("state_delta", {"path": "sql", "value": {"sql": sql}})
    _emit("step_finished", {"agent_name": "sql_gen", "phase": "sql_gen"})

    # Track history
    history = list(state.get("sql_history", []))
    history.append({"sql": sql, "status": "generated"})
    return {"sql_candidate": sql, "sql_history": history}


async def _verify_sql_node(state: dict) -> dict:
    """Verify SQL against Query IR + Sandbox."""
    _emit("step_started", {"agent_name": "verify", "phase": "verify"})
    _emit("thinking_start", {})
    _emit("thinking_delta", "验证 SQL...")
    _emit("thinking_end", {})

    sql = state.get("sql_candidate", "")
    query_ir_dict = state.get("query_ir", {})
    ctx = state.get("semantic_context")

    from app.protocols import TableSchema
    from app.semantic.query_ir import QueryIR
    from app.sql.error_classifier import ErrorClassifier
    from app.sql.sandbox import SQLSandbox, SQLSandboxError
    from app.sql.semantic_validator import SemanticValidator
    from app.sql.validator import validate_sql

    # 1. Semantic validation
    sv = SemanticValidator()
    query_ir = QueryIR.from_dict(query_ir_dict)
    focused_tables = [t.name for t in (ctx.focused_schema if ctx and hasattr(ctx, "focused_schema") else [])]
    verified_joins = [join.condition for join in (ctx.verified_joins if ctx and hasattr(ctx, "verified_joins") else [])]
    report = sv.validate(sql, query_ir, focused_tables, verified_joins)

    validation = {"valid": report.valid, "errors": [], "warnings": [], "semantic_report": {}}
    has_schema_reference_errors = False

    if not report.valid:
        validation["semantic_report"] = {
            "valid": False,
            "missing": report.missing_intents,
            "extra": report.extra_intents,
            "unsafe_joins": getattr(report, "unsafe_joins", []),
            "repair_hint": report.repair_hint,
        }
    else:
        # 2. Sandbox validation
        try:
            SQLSandbox._validate_first_word(sql)
            SQLSandbox._validate_ast(sql)
            SQLSandbox._validate_single_statement(sql)
            schema_catalog = ctx.schema_catalog if ctx and hasattr(ctx, "schema_catalog") else {}
            schemas = [
                TableSchema(table_name=table_name, ddl="", columns=columns)
                for table_name, columns in schema_catalog.items()
            ]
            if not schemas:
                schemas = [
                    TableSchema(
                        table_name=table.name,
                        ddl="",
                        columns=[column["name"] for column in table.columns],
                    )
                    for table in (ctx.focused_schema if ctx and hasattr(ctx, "focused_schema") else [])
                ]
            schema_result = validate_sql(sql, schemas=schemas or None)
            if not schema_result.is_valid:
                validation["errors"] = schema_result.errors
                validation["valid"] = False
            validation["warnings"] = schema_result.warnings
            schema_reference_errors = [
                warning
                for warning in schema_result.warnings
                if "当前 Schema 中未找到" in warning or "在表" in warning and "不存在" in warning
            ]
            if schema_reference_errors:
                validation["errors"].extend(schema_reference_errors)
                validation["valid"] = False
                has_schema_reference_errors = True
        except SQLSandboxError as exc:
            validation["errors"] = [str(exc)]
            validation["valid"] = False

    _emit("state_delta", {"path": "sql", "value": {"sql": sql, "validation": validation}})

    # 3. Classify error if failed
    should_retry = False
    if not validation["valid"]:
        semantic_errors = (
            report.missing_intents + report.extra_intents + getattr(report, "unsafe_joins", [])
            if not report.valid
            else []
        )
        error_msg = "; ".join(validation["errors"] + semantic_errors)
        classifier = ErrorClassifier()
        fingerprint = classifier.make_fingerprint(error_msg, sql)

        history = list(state.get("sql_history", []))
        if not history:
            history.append({"sql": sql, "status": "generated"})
        fingerprint_counts = {}
        for h in history:
            fp = h.get("fingerprint", "")
            if fp:
                fingerprint_counts[fp] = fingerprint_counts.get(fp, 0) + 1

        if (
            not has_schema_reference_errors
            and fingerprint_counts.get(fingerprint.fingerprint, 0) < MAX_SAME_ERROR_RETRIES
        ):
            should_retry = True

        total_candidates = len(history)
        if total_candidates >= MAX_SQL_CANDIDATES:
            should_retry = False

        history[-1].update(
            {
                "status": "validation_failed",
                "fingerprint": fingerprint.fingerprint,
                "error_category": fingerprint.category,
            }
        )
        return {
            "validation_report": validation,
            "should_retry": should_retry,
            "retry_hint": report.repair_hint or error_msg,
            "sql_history": history,
        }

    # Success
    history = list(state.get("sql_history", []))
    if not history:
        history.append({"sql": sql, "status": "generated"})
    history[-1]["status"] = "verified"
    _emit("step_finished", {"agent_name": "verify", "phase": "verify"})
    return {"validation_report": validation, "should_retry": False, "sql_history": history}


async def _refine_sql_node(state: dict) -> dict:
    """Refine SQL based on verification errors."""
    _emit("step_started", {"agent_name": "refine", "phase": "refine"})
    _emit("thinking_start", {})
    _emit("thinking_delta", "修正 SQL...")
    _emit("thinking_end", {})

    sql = state.get("sql_candidate", "")
    retry_hint = state.get("retry_hint", "")
    question = state.get("resolved_question", "")

    prompt = f"""修正以下 SQL 以解决验证错误。

## 用户问题
{question}

## 当前 SQL
```sql
{sql}
```

## 验证错误
{retry_hint}

请输出修正后的 SQL（只输出 SQL，不要解释）:"""

    from app.dependencies import get_llm_client
    from app.llm.adapter import LiteLLMChatAdapter

    llm = LiteLLMChatAdapter(get_llm_client(task_type="sql_generation"))
    response = await _call_llm(llm, [HumanMessage(content=prompt)])
    refined = (response.content or "").strip()
    if refined.startswith("```"):
        refined = "\n".join(refined.split("\n")[1:])
    if refined.endswith("```"):
        refined = refined[:-3]
    refined = refined.strip()

    _emit("state_delta", {"path": "sql", "value": {"sql": refined}})
    _emit("step_finished", {"agent_name": "refine", "phase": "refine"})
    history = list(state.get("sql_history", []))
    history.append({"sql": refined, "status": "refined"})
    return {"sql_candidate": refined, "sql_history": history}


async def _execute_sql_node(state: dict) -> dict:
    """Execute verified SQL."""
    _emit("step_started", {"agent_name": "execute", "phase": "execute"})
    _emit("thinking_start", {})
    _emit("thinking_delta", "执行 SQL 查询...")
    _emit("thinking_end", {})

    sql = state.get("sql_candidate", "")
    db_id = state.get("db_connection_id", "")

    from app.agents.tools.sql_tools import SubmitSQLTool

    tool = SubmitSQLTool(db_connection_id=db_id)
    _emit("tool_call_start", {"name": "submit_sql", "args": {"sql": sql}, "agent_name": "execute"})
    result = await tool.execute(sql=sql)

    formatted = tool.format_result(result)
    _emit("tool_call_result", {"name": "submit_sql", "result": formatted})
    _emit("tool_call_end", {"name": "submit_sql"})

    execution_count = int(state.get("execution_count", 0)) + 1
    should_retry = False
    retry_hint = ""
    history = list(state.get("sql_history", []))
    if isinstance(result, dict):
        if result.get("status") == "completed":
            _emit("state_delta", {"path": "result", "value": result})
        elif result.get("status") in ("validation_failed", "execution_failed"):
            error_msg = result.get("error", "") or "; ".join(result.get("errors", []))
            retry_hint = f"数据库执行或提交失败: {error_msg}"
            from app.sql.error_classifier import ErrorClassifier

            fingerprint = ErrorClassifier().make_fingerprint(error_msg, sql)
            same_error_count = sum(1 for item in history if item.get("fingerprint") == fingerprint.fingerprint)
            should_retry = (
                execution_count < MAX_SQL_EXECUTIONS
                and len(history) < MAX_SQL_CANDIDATES
                and same_error_count < MAX_SAME_ERROR_RETRIES
                and fingerprint.category != "execution_error"
            )
            if history:
                history[-1].update(
                    {
                        "status": result.get("status"),
                        "fingerprint": fingerprint.fingerprint,
                        "error_category": fingerprint.category,
                    }
                )

    _emit("step_finished", {"agent_name": "execute", "phase": "execute"})
    return {
        "query_result": result,
        "execution_count": execution_count,
        "should_retry": should_retry,
        "retry_hint": retry_hint,
        "sql_history": history,
    }


async def _build_answer_node(state: dict) -> dict:
    """Build final answer with result + semantic logic."""
    _emit("step_started", {"agent_name": "answer", "phase": "answer"})

    result = state.get("query_result", {})
    query_ir_dict = state.get("query_ir", {})
    question = state.get("resolved_question", "")

    # Build semantic logic card
    from app.semantic.query_ir import QueryIR

    query_ir = QueryIR.from_dict(query_ir_dict) if query_ir_dict else None
    semantic_logic = query_ir.to_natural_language() if query_ir else "（无可用的查询结构）"

    # Build result summary
    result_summary = ""
    if isinstance(result, dict):
        if result.get("status") == "completed":
            result_summary = json.dumps(
                {
                    "columns": result.get("columns", []),
                    "rows": result.get("rows", [])[:20],
                    "row_count": result.get("row_count", 0),
                    "execution_time_ms": result.get("execution_time_ms", 0),
                    "truncated": result.get("truncated", False),
                },
                ensure_ascii=False,
                default=str,
            )[:12000]
        elif result.get("status") == "validation_failed":
            result_summary = f"SQL 验证失败: {'; '.join(result.get('errors', []))}"
        elif result.get("status") == "execution_failed":
            result_summary = f"执行失败: {result.get('error', '')}"
        else:
            result_summary = json.dumps(result, ensure_ascii=False)[:500]
    else:
        result_summary = str(result)[:500]

    prompt = ANSWER_BUILDER_PROMPT.format(
        semantic_logic=semantic_logic,
        query_result=result_summary,
    )
    prompt += f"\n## 用户问题\n{question}"

    from app.dependencies import get_llm_client
    from app.llm.adapter import LiteLLMChatAdapter

    llm = LiteLLMChatAdapter(get_llm_client(task_type="general"))
    answer_chunks = []
    async for chunk in _stream_llm_text(llm, [HumanMessage(content=prompt)]):
        answer_chunks.append(chunk)
        _emit("delta", chunk)
    answer = "".join(answer_chunks).strip()

    if isinstance(result, dict) and result.get("status") == "completed":
        _emit("state_delta", {"path": "result", "value": result})
    _emit("state_delta", {"path": "semantic_logic", "value": {"logic": semantic_logic}})
    _emit("step_finished", {"agent_name": "answer", "phase": "answer"})

    return {"final_response": answer, "semantic_logic": semantic_logic}


async def _fail_answer_node(state: dict) -> dict:
    """Build failure answer with diagnostics."""
    _emit("step_started", {"agent_name": "fail", "phase": "fail"})

    sql = state.get("sql_candidate", "")
    retry_hint = state.get("retry_hint", "")
    question = state.get("resolved_question", "")
    result = state.get("query_result", {})
    planning_error = state.get("planning_error", "")

    if planning_error:
        msg = f"查询计划生成服务暂时不可用，本次未生成或执行 SQL。请稍后重试。\n\n错误类型：{planning_error}"
        _emit("delta", msg)
        _emit("step_finished", {"agent_name": "fail", "phase": "fail"})
        return {"final_response": msg}

    if isinstance(result, dict) and result.get("status") in ("validation_failed", "execution_failed"):
        error = result.get("error", "") or "; ".join(result.get("errors", []))
        msg = f"""SQL 执行未能成功，且已达到本轮自动修复预算。

## 用户问题
{question}

## 最后生成的 SQL
```sql
{sql}
```

## 数据库返回
{error or retry_hint}

请检查数据库连接、Schema 或查询条件后重试。"""
        _emit("delta", msg)
        _emit("step_finished", {"agent_name": "fail", "phase": "fail"})
        return {"final_response": msg}

    msg = f"""SQL 生成未能通过验证。已尝试修正但仍有问题。

## 用户问题
{question}

## 最后生成的 SQL
```sql
{sql}
```

## 验证错误
{retry_hint}

## 建议
- 请尝试用更具体的方式描述您的查询需求
- 或检查数据库表结构是否与查询匹配"""

    _emit("delta", msg)
    _emit("step_finished", {"agent_name": "fail", "phase": "fail"})
    return {"final_response": msg}


async def _clarify_node(state: dict) -> dict:
    """Ask the user to resolve planner ambiguities before generating SQL."""
    _emit("step_started", {"agent_name": "clarify", "phase": "clarify"})

    unresolved = state.get("query_ir", {}).get("unresolved", [])
    questions = []
    for item in unresolved:
        question = str(item.get("question", "")).strip()
        candidates = [str(candidate) for candidate in item.get("candidates", []) if candidate]
        if question:
            questions.append(f"- {question}")
        if candidates:
            questions.append(f"  可选项：{'、'.join(candidates)}")

    if questions:
        msg = "为了准确生成查询，请先确认以下信息：\n\n" + "\n".join(questions)
    else:
        msg = "当前问题的信息不足以生成可靠查询，请补充要查询的指标、维度或时间范围。"

    _emit("delta", msg)
    _emit("step_finished", {"agent_name": "clarify", "phase": "clarify"})
    return {"final_response": msg}


# ═══════════════════════════════════════════════════════════════════════════════
# Graph builder
# ═══════════════════════════════════════════════════════════════════════════════


def build_nl2sql_graph(db_connection_id: str = "", model: str | None = None):
    """Build v3.4 Semantic NL2SQL Graph."""
    builder = StateGraph(AgentState)

    # ── Nodes ──
    builder.add_node("resolve", _resolve_conversation_node)
    builder.add_node("build_context", _build_context_node)
    builder.add_node("plan_query", _plan_query_node)
    builder.add_node("clarify", _clarify_node)
    builder.add_node("generate_sql", _generate_sql_node)
    builder.add_node("verify_sql", _verify_sql_node)
    builder.add_node("refine_sql", _refine_sql_node)
    builder.add_node("execute_sql", _execute_sql_node)
    builder.add_node("build_answer", _build_answer_node)
    builder.add_node("fail_answer", _fail_answer_node)

    # ── Routing ──

    def route_plan(state: dict) -> str:
        if state.get("planning_error"):
            return "fail"
        if state.get("should_clarify"):
            return "clarify"
        return "generate"

    def route_verify(state: dict) -> str:
        if state.get("should_retry"):
            return "refine"
        validation = state.get("validation_report", {})
        if validation.get("valid"):
            return "execute"
        return "fail"

    def route_execute(state: dict) -> str:
        result = state.get("query_result", {})
        if isinstance(result, dict) and result.get("status") == "completed":
            return "answer"
        if state.get("should_retry"):
            return "refine"
        return "fail"

    # ── Edges ──
    builder.add_edge(START, "resolve")
    builder.add_edge("resolve", "build_context")
    builder.add_edge("build_context", "plan_query")

    builder.add_conditional_edges(
        "plan_query",
        route_plan,
        {
            "clarify": "clarify",
            "generate": "generate_sql",
            "fail": "fail_answer",
        },
    )
    builder.add_edge("clarify", END)

    builder.add_edge("generate_sql", "verify_sql")

    builder.add_conditional_edges(
        "verify_sql",
        route_verify,
        {
            "refine": "refine_sql",
            "execute": "execute_sql",
            "fail": "fail_answer",
        },
    )
    builder.add_edge("refine_sql", "verify_sql")  # bounded loop
    builder.add_conditional_edges(
        "execute_sql",
        route_execute,
        {
            "answer": "build_answer",
            "refine": "refine_sql",
            "fail": "fail_answer",
        },
    )
    builder.add_edge("build_answer", END)
    builder.add_edge("fail_answer", END)

    return builder.compile()


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Runner — shared with graph.py, selectable via feature flag
# ═══════════════════════════════════════════════════════════════════════════════

_MONITORING_PATTERNS = [
    "连接状态",
    "连接数",
    "多少条",
    "sql在跑",
    "运行了多久",
    "数据库状态",
    "慢查询",
    "连接信息",
    "数据库连接",
    "多少连接",
    "活跃查询",
    "表概况",
    "运行时间",
]
_GREETING_PATTERNS = ["你好", "您好", "hi", "hello", "嗨", "在吗", "谢谢", "感谢", "再见", "拜拜"]
_KNOWLEDGE_PATTERNS = [
    "如何",
    "怎么",
    "什么是",
    "为什么",
    "语法",
    "支持",
    "参数",
    "配置",
    "安装",
    "部署",
    "原理",
    "区别",
    "手册",
    "报错",
    "错误",
    "版本",
]
_NL2SQL_PATTERNS = [
    "查询",
    "统计",
    "汇总",
    "排名",
    "趋势",
    "明细",
    "列出",
    "展示",
    "查看",
    "多少",
    "总数",
    "平均",
    "最大",
    "最小",
    "哪些",
    "销售额",
    "订单量",
    "取数",
    "SQL",
    "sql",
]


GENERAL_CHAT_PROMPT = """你是 GBase 数据助手。自然、简洁地回应用户的问候、感谢或轻量闲聊。

限制：
1. 不要声称已查询数据库、看到了数据或执行了 SQL。
2. 不要编造 GBase 产品能力、数据库状态或业务数据。
3. 若用户开始询问数据查询或产品知识，引导其直接描述问题，不要自行虚构答案。
4. 通常回复一到三句话，避免固定话术和冗长自我介绍。
"""


async def _greeting_fast_path(user_message: str, conversation_id: str, model: str) -> AsyncIterator[str]:
    yield EventEncoder.run_started(conversation_id)
    from app.dependencies import get_llm_client

    llm = LiteLLMChatAdapter(get_llm_client(model=model, task_type="greeting"))
    streamed_answer = False
    try:
        async with asyncio.timeout(4):
            async for chunk in _stream_llm_text(
                llm,
                [SystemMessage(content=GENERAL_CHAT_PROMPT), HumanMessage(content=user_message)],
            ):
                streamed_answer = True
                yield EventEncoder.text_delta(chunk)
    except TimeoutError:
        logger.warning("General chat exceeded the greeting latency budget")
    except Exception as exc:
        logger.error("General chat failed: %s", exc)
    if not streamed_answer:
        yield EventEncoder.text_delta("你好，请告诉我你想了解的数据库问题或查询需求。")
    yield EventEncoder.run_finished()


async def _monitoring_fast_path(db_connection_id: str | None) -> AsyncIterator[str]:
    if not db_connection_id:
        yield EventEncoder.text_delta("当前未选择数据库连接。")
        yield EventEncoder.run_finished()
        return
    from app.agents.tools.status_tool import GetDatabaseStatusTool

    tool = GetDatabaseStatusTool(db_connection_id=db_connection_id)
    raw_result = await tool.execute()
    try:
        status_data = raw_result if isinstance(raw_result, dict) else json.loads(raw_result)
        lines = ["**数据库状态概览**\n"]
        for label, data in status_data.items():
            if isinstance(data, dict) and "error" in data:
                lines.append(f"### {label}\n> 错误: {data['error']}")
            elif isinstance(data, dict) and data.get("rows") and data["rows"]:
                cols = data["columns"]
                line = f"### {label}"
                if len(cols) == 1 and data["row_count"] == 1:
                    line += f"\n{cols[0]}: **{data['rows'][0][0]}**"
                else:
                    line += f"\n| {' | '.join(cols)} |\n|{'|'.join(['---' for _ in cols])}|"
                    for row in data["rows"][:20]:
                        line += f"\n| {' | '.join(str(c) for c in row)} |"
                lines.append(line)
            else:
                lines.append(f"### {label}\n> 无数据")
        formatted = "\n\n".join(lines)
    except (json.JSONDecodeError, TypeError):
        formatted = f"数据库状态查询结果:\n{raw_result}"
    yield EventEncoder.text_delta(formatted)
    yield EventEncoder.run_finished()


def _classify_user_intent(user_message: str, db_connection_id: str | None) -> str:
    """Conservatively route only explicit data questions into NL2SQL."""
    if any(pattern in user_message for pattern in _KNOWLEDGE_PATTERNS):
        return "knowledge"
    if any(pattern in user_message for pattern in _NL2SQL_PATTERNS):
        return "nl2sql"
    if "gbase" in user_message.lower() or any(
        pattern in user_message for pattern in ("介绍一下", "介绍下", "你是谁", "能做什么")
    ):
        return "knowledge"
    # With an active database, short business nouns such as "订单状态" or
    # "库存余额" should enter schema linking instead of unrelated knowledge QA.
    if db_connection_id:
        return "nl2sql"
    return "knowledge"


async def _missing_connection_fast_path(conversation_id: str) -> AsyncIterator[str]:
    yield EventEncoder.run_started(conversation_id)
    yield EventEncoder.text_delta("请先选择一个数据库连接，再进行数据查询。")
    yield EventEncoder.run_finished()


async def _knowledge_fast_path(
    user_message: str,
    conversation_id: str,
    model: str,
) -> AsyncIterator[str]:
    """Run grounded knowledge QA without entering the NL2SQL graph."""
    from app.agents.agents.knowledge_agent import (
        KNOWLEDGE_QA_PROMPT,
        _build_knowledge_section,
        expand_knowledge_query,
        merge_knowledge_chunks,
    )
    from app.dependencies import get_knowledge_retriever, get_llm_client

    yield EventEncoder.run_started(conversation_id)
    streamed_answer = False
    try:
        retriever = get_knowledge_retriever()
        chunks = await retriever.retrieve(user_message)
        expanded_query = expand_knowledge_query(user_message)
        if expanded_query != user_message:
            chunks = merge_knowledge_chunks(await retriever.retrieve(expanded_query), chunks)

        knowledge_section, source_names, status = _build_knowledge_section(chunks)
        prompt = KNOWLEDGE_QA_PROMPT.format(
            knowledge_section=knowledge_section,
            retrieval_status=status,
        )
        prompt += f"\n## 用户问题\n{user_message}"

        llm = LiteLLMChatAdapter(get_llm_client(model=model, task_type="general"))
        answer_chunks = []
        async for chunk in _stream_llm_text(llm, [HumanMessage(content=prompt)]):
            answer_chunks.append(chunk)
            streamed_answer = True
            yield EventEncoder.text_delta(chunk)
        answer = "".join(answer_chunks).strip()
    except Exception as exc:
        logger.error("Knowledge QA failed: %s", exc)
        answer = "知识库检索或模型调用失败，请稍后重试。"
        source_names = []
        status = "error"

    if not answer:
        answer = "知识库中未找到该信息，建议查阅 GBase 8a 官方手册。"
    if not streamed_answer:
        yield EventEncoder.text_delta(answer)
    yield EventEncoder.state_delta("sources", {"sources": source_names, "status": status})
    yield EventEncoder.run_finished()


async def run_agent_with_ag_ui(
    user_message: str,
    conversation_id: str,
    model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """Run v3.4 Semantic NL2SQL Graph with AG-UI SSE output."""

    normalized_message = user_message.strip().lower().strip("，。！？,.!?~～ ")
    if normalized_message in _GREETING_PATTERNS:
        async for event in _greeting_fast_path(user_message, conversation_id, model):
            yield event
        return

    if any(p in user_message for p in _MONITORING_PATTERNS):
        async for event in _monitoring_fast_path(db_connection_id):
            yield event
        return

    intent = _classify_user_intent(user_message, db_connection_id)
    if intent == "knowledge":
        async for event in _knowledge_fast_path(user_message, conversation_id, model):
            yield event
        return

    if not db_connection_id:
        async for event in _missing_connection_fast_path(conversation_id):
            yield event
        return

    history = []
    if conversation_id:
        try:
            from sqlalchemy import select

            from app.database import async_session_factory
            from app.models.conversation import Conversation
            from app.services.conversation_service import build_context

            async with async_session_factory() as session:
                result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
                conv = result.scalar_one_or_none()
                if conv:
                    ctx = await build_context(session, conv)
                    history = ctx.history or []
        except Exception:
            pass

    graph = build_nl2sql_graph(db_connection_id=db_connection_id or "", model=model)

    initial_state = {
        "messages": _build_conversation_messages(history, user_message),
        "db_connection_id": db_connection_id,
        "sql_history": [],
    }

    yield EventEncoder.run_started(conversation_id)
    config = {"configurable": {"thread_id": conversation_id}}
    streamed_text = False
    latest_state = dict(initial_state)

    try:
        async for mode, events in graph.astream(initial_state, config=config, stream_mode=["custom", "updates"]):
            if mode == "custom":
                for ev in events:
                    if isinstance(ev, dict):
                        if "thinking_start" in ev:
                            yield EventEncoder.thinking_start()
                        elif "thinking_delta" in ev:
                            yield EventEncoder.thinking_delta(ev["thinking_delta"])
                        elif "thinking_end" in ev:
                            yield EventEncoder.thinking_end()
                        elif "step_started" in ev:
                            info = ev["step_started"]
                            yield EventEncoder.step_started(info.get("agent_name", ""), 0)
                        elif "step_finished" in ev:
                            yield EventEncoder.step_finished(ev["step_finished"].get("agent_name", ""))
                        elif "tool_call_start" in ev:
                            info = ev["tool_call_start"]
                            yield EventEncoder.tool_call_start(
                                info["name"], info.get("args"), info.get("agent_name", "")
                            )
                        elif "tool_call_result" in ev:
                            info = ev["tool_call_result"]
                            yield EventEncoder.tool_call_result(info["name"], info.get("result", {}))
                        elif "tool_call_end" in ev:
                            yield EventEncoder.tool_call_end(ev["tool_call_end"].get("name", ""))
                        elif "delta" in ev:
                            yield EventEncoder.text_delta(ev["delta"])
                            streamed_text = True
                        elif "state_delta" in ev:
                            info = ev["state_delta"]
                            yield EventEncoder.state_delta(info["path"], info["value"])
            elif mode == "updates" and isinstance(events, dict):
                for update in events.values():
                    if isinstance(update, dict):
                        latest_state.update(update)

        response = latest_state.get("final_response", "")
        if response and not streamed_text:
            yield EventEncoder.text_delta(response)
        yield EventEncoder.run_finished()

    except Exception as e:
        logger.error("NL2SQL agent run failed: %s", e)
        yield EventEncoder.run_error(str(e))
