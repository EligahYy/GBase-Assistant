"""v3.4 Semantic NL2SQL Graph — structured pipeline with bounded repair.

Graph flow:
  START → resolve → build_context → plan_query → generate_sql → verify
    → [repairable] → refine_sql → verify (bounded loop)
    → execute → build_answer → END
    → [fatal] → fail_answer → END
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

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
ANSWER_BUILDER_PROMPT = """你是 GBase 8a 助手。基于查询结果和取数逻辑向用户展示最终回答。

## 输出格式
1. 用 markdown 简洁展示查询结果
2. 附上"取数逻辑"说明:
   - 指标: ...
   - 维度: ...
   - 过滤: ...
   - 时间范围: ...
   - 关联: ...
3. 中文回答，专业友好
4. 如果查询结果为空，说明可能原因
5. 如果查询失败，诚实说明并提供建议

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
    from app.semantic.planner import QueryPlanner

    llm_client = get_llm_client(task_type="default")
    planner = QueryPlanner(llm_client)
    query_ir = await planner.plan(question, ctx)

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
            focused_desc += ", ".join(f"{c['name']}({c.get('type','')})" for c in t.columns)

    verified_examples = ""
    if ctx and hasattr(ctx, "verified_examples") and ctx.verified_examples:
        for ex in ctx.verified_examples[:2]:
            verified_examples += f"\nQ: {ex.question}\nSQL: {ex.sql}\n"

    prompt = f"""{SQL_GENERATOR_PROMPT}

## 用户问题
{question}

## Query IR
{json.dumps(query_ir_dict, ensure_ascii=False, indent=2)}

## FocusedSchema
{focused_desc}
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

    from app.sql.semantic_validator import SemanticValidator
    from app.sql.validator import validate_sql
    from app.sql.sandbox import SQLSandbox, SQLSandboxError
    from app.sql.error_classifier import ErrorClassifier
    from app.semantic.query_ir import QueryIR

    # 1. Semantic validation
    sv = SemanticValidator()
    query_ir = QueryIR.from_dict(query_ir_dict)
    focused_tables = [t.name for t in (ctx.focused_schema if ctx and hasattr(ctx, "focused_schema") else [])]
    report = sv.validate(sql, query_ir, focused_tables)

    validation = {"valid": report.valid, "errors": [], "warnings": [], "semantic_report": {}}

    if not report.valid:
        validation["semantic_report"] = {
            "valid": False,
            "missing": report.missing_intents,
            "extra": report.extra_intents,
            "repair_hint": report.repair_hint,
        }
    else:
        # 2. Sandbox validation
        try:
            SQLSandbox._validate_first_word(sql)
            SQLSandbox._validate_ast(sql)
            SQLSandbox._validate_single_statement(sql)
            schema_result = validate_sql(sql, schemas=None)
            if not schema_result.is_valid:
                validation["errors"] = schema_result.errors
                validation["valid"] = False
            validation["warnings"] = schema_result.warnings
        except SQLSandboxError as exc:
            validation["errors"] = [str(exc)]
            validation["valid"] = False

    _emit("state_delta", {"path": "sql", "value": {"sql": sql, "validation": validation}})

    # 3. Classify error if failed
    should_retry = False
    if not validation["valid"]:
        error_msg = "; ".join(validation["errors"] + (report.missing_intents + report.extra_intents if not report.valid else []))
        classifier = ErrorClassifier()
        fingerprint = classifier.make_fingerprint(error_msg, sql)

        history = list(state.get("sql_history", []))
        fingerprint_counts = {}
        for h in history:
            fp = h.get("fingerprint", "")
            fingerprint_counts[fp] = fingerprint_counts.get(fp, 0) + 1

        if fingerprint.retry_count < MAX_SAME_ERROR_RETRIES and fingerprint_counts.get(fingerprint.fingerprint, 0) < MAX_SAME_ERROR_RETRIES:
            should_retry = True

        total_candidates = len(history)
        if total_candidates >= MAX_SQL_CANDIDATES:
            should_retry = False

        history[-1].update({
            "status": "validation_failed",
            "fingerprint": fingerprint.fingerprint,
            "error_category": fingerprint.category,
        })
        return {
            "validation_report": validation,
            "should_retry": should_retry,
            "retry_hint": report.repair_hint or error_msg,
            "sql_history": history,
        }

    # Success
    history = list(state.get("sql_history", []))
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
    return {"sql_candidate": refined}


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
    result = await tool.execute(sql=sql)

    _emit("tool_call_start", {"name": "submit_sql", "args": {"sql": sql}, "agent_name": "execute"})
    formatted = tool.format_result(result)
    _emit("tool_call_result", {"name": "submit_sql", "result": formatted})

    if isinstance(result, dict):
        if result.get("status") == "completed":
            _emit("state_delta", {"path": "result", "value": result})
        elif result.get("status") in ("validation_failed", "execution_failed"):
            error_msg = result.get("error", "") or "; ".join(result.get("errors", []))
            _emit("delta", f"SQL 执行失败：{error_msg}")

    _emit("step_finished", {"agent_name": "execute", "phase": "execute"})
    return {"query_result": result}


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
            result_summary = f"查询完成: {result.get('row_count', 0)} 行, {result.get('execution_time_ms', 0)}ms"
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
    response = await _call_llm(llm, [HumanMessage(content=prompt)])
    answer = (response.content or "").strip()

    _emit("delta", answer)
    if isinstance(result, dict) and result.get("status") == "completed":
        _emit("state_delta", {"path": "result", "value": result})
    _emit("state_delta", {"path": "semantic_logic", "value": {"logic": semantic_logic}})
    _emit("step_finished", {"agent_name": "answer", "phase": "answer"})

    return {"final_response": answer, "semantic_logic": semantic_logic}


async def _fail_answer_node(state: dict) -> dict:
    """Build failure answer with diagnostics."""
    _emit("step_started", {"agent_name": "fail", "phase": "fail"})

    validation = state.get("validation_report", {})
    sql = state.get("sql_candidate", "")
    retry_hint = state.get("retry_hint", "")
    question = state.get("resolved_question", "")

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


# ═══════════════════════════════════════════════════════════════════════════════
# Graph builder
# ═══════════════════════════════════════════════════════════════════════════════

def build_nl2sql_graph(db_connection_id: str = "", model: str | None = None):
    """Build v3.4 Semantic NL2SQL Graph."""
    builder = StateGraph(dict)

    # ── Nodes ──
    builder.add_node("resolve", _resolve_conversation_node)
    builder.add_node("build_context", _build_context_node)
    builder.add_node("plan_query", _plan_query_node)
    builder.add_node("clarify", _fail_answer_node)  # placeholder
    builder.add_node("generate_sql", _generate_sql_node)
    builder.add_node("verify_sql", _verify_sql_node)
    builder.add_node("refine_sql", _refine_sql_node)
    builder.add_node("execute_sql", _execute_sql_node)
    builder.add_node("build_answer", _build_answer_node)
    builder.add_node("fail_answer", _fail_answer_node)

    # ── Routing ──

    def route_plan(state: dict) -> str:
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

    # ── Edges ──
    builder.add_edge(START, "resolve")
    builder.add_edge("resolve", "build_context")
    builder.add_edge("build_context", "plan_query")

    builder.add_conditional_edges("plan_query", route_plan, {
        "clarify": "clarify",
        "generate": "generate_sql",
    })
    builder.add_edge("clarify", END)

    builder.add_edge("generate_sql", "verify_sql")

    builder.add_conditional_edges("verify_sql", route_verify, {
        "refine": "refine_sql",
        "execute": "execute_sql",
        "fail": "fail_answer",
    })
    builder.add_edge("refine_sql", "verify_sql")  # bounded loop
    builder.add_edge("execute_sql", "build_answer")
    builder.add_edge("build_answer", END)
    builder.add_edge("fail_answer", END)

    return builder.compile(checkpointer=MemorySaver())


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Runner — shared with graph.py, selectable via feature flag
# ═══════════════════════════════════════════════════════════════════════════════

_MONITORING_PATTERNS = [
    "连接状态", "连接数", "多少条", "sql在跑", "运行了多久",
    "数据库状态", "慢查询", "连接信息", "数据库连接",
    "多少连接", "活跃查询", "表概况", "运行时间",
]
_GREETING_PATTERNS = ["你好", "您好", "hi", "hello", "嗨", "在吗", "谢谢", "感谢", "再见", "拜拜"]


async def _greeting_fast_path(conversation_id: str) -> AsyncIterator[str]:
    yield EventEncoder.run_started(conversation_id)
    yield EventEncoder.text_delta("你好！我是 GBase 8a 数据库助手。有什么可以帮你的？")
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


async def run_agent_with_ag_ui(
    user_message: str, conversation_id: str, model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """Run v3.4 Semantic NL2SQL Graph with AG-UI SSE output."""

    if any(user_message.strip().lower().startswith(p) or user_message.strip() == p for p in _GREETING_PATTERNS):
        async for event in _greeting_fast_path(conversation_id):
            yield event
        return

    if any(p in user_message for p in _MONITORING_PATTERNS):
        async for event in _monitoring_fast_path(db_connection_id):
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
                            yield EventEncoder.tool_call_start(info["name"], info.get("args"), info.get("agent_name", ""))
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

        final_state = await graph.aget_state(config)
        state_values = final_state.values if final_state else {}
        response = state_values.get("final_response", "") if state_values else ""
        if response and not streamed_text:
            yield EventEncoder.text_delta(response)
        yield EventEncoder.run_finished()

    except Exception as e:
        logger.error("NL2SQL agent run failed: %s", e)
        yield EventEncoder.run_error(str(e))
