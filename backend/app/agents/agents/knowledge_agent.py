"""Knowledge Agent — search→answer pipeline (NOT ReAct, no tools for LLM).

Design:
- HybridKnowledgeRetriever: Qdrant vector + ripgrep + RRF fusion
- Keyword fallback: auto-extract domain terms and retry if results sparse
- Structured status: found / partial / not_found for anti-hallucination
- No tool calls exposed to LLM, no ReAct loop
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.config import get_stream_writer

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════════
# Knowledge QA prompt
# ═══════════════════════════════════════════════════════════════════════════════════

KNOWLEDGE_QA_PROMPT = """你是 GBase 8a 数据库专家助手。根据以下知识库内容回答用户问题。

## 知识库内容
{knowledge_section}

## 检索状态: {retrieval_status}

## 回答规则

1. **基于知识库回答**：只使用上方"知识库内容"中的信息。
2. **检索状态为 not_found 时**：直接回复"知识库中未找到该信息，建议查阅 GBase 8a 官方手册。"，**严禁编造任何内容**。
3. **检索状态为 partial 时**：只回答有明确依据的部分，推测部分必须标注"[推测]"。
4. **检索状态为 found 时**：综合所有相关来源给出完整回答。
5. **注明来源**：每条信息注明来自哪个文档（[文档名称]）。
6. **代码示例**：必须来自知识库原文，用 ```sql 代码块格式化。禁止自行编写未在知识库中出现的 GBase 8a 语法。
7. **严禁编造**：不要编造知识库中没有的功能、语法、版本号或参数。
8. **多段引用**：如果多个来源回答了问题的不同方面，综合呈现。
9. **保持简洁**：直接回答问题，不需要额外说明搜索过程。
"""

# ═══════════════════════════════════════════════════════════════════════════════════
# Query expansion — GBase domain terminology
# ═══════════════════════════════════════════════════════════════════════════════════

_KNOWLEDGE_QUERY_EXPANSIONS: dict[str, str] = {
    "创建": "table_options CREATE TABLE 随机分布表 DDL 建表语句",
    "分布": "分布表 分布方式 DISTRIBUTED 随机分布 HASH",
    "分区": "分区表 分区键 PARTITION CREATE TABLE",
    "随机": "随机分布 RANDOM DISTRIBUTION 分布表",
    "hash": "HASH 哈希 分布键 分布表 随机分布",
}


def expand_knowledge_query(query: str) -> str:
    """Append domain terms found inside a natural-language query."""
    lowered = query.lower()
    expansions = [
        expansion
        for term, expansion in _KNOWLEDGE_QUERY_EXPANSIONS.items()
        if term in lowered
    ]
    return f"{query} {' '.join(expansions)}".strip() if expansions else query


# ═══════════════════════════════════════════════════════════════════════════════════
# Chunk merging — dedup across retrieval passes
# ═══════════════════════════════════════════════════════════════════════════════════

def merge_knowledge_chunks(*groups: list[Any], limit: int = 5) -> list[Any]:
    """Merge and dedup chunk groups, keeping the first `limit` unique chunks."""
    merged: list[Any] = []
    seen: set[str] = set()
    for group in groups:
        for chunk in group:
            key = f"{chunk.source}|{' '.join(chunk.content.split())[:240]}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(chunk)
            if len(merged) >= limit:
                return merged
    return merged


# ═══════════════════════════════════════════════════════════════════════════════════
# Retrieval status
# ═══════════════════════════════════════════════════════════════════════════════════

def _classify_retrieval_status(chunks: list[Any]) -> str:
    """Classify retrieval quality so the LLM can adjust its answer confidence.

    Returns:
        "found"   — sufficient content (>2 unique chunks)
        "partial" — some content but sparse (1-2 chunks)
        "not_found" — no content retrieved
    """
    if not chunks:
        return "not_found"
    if len(chunks) <= 2:
        return "partial"
    return "found"


def _build_knowledge_section(chunks: list[Any], max_per_chunk: int = 3000) -> tuple[str, list[str], str]:
    """Build the knowledge context block for the QA prompt.

    Returns:
        (knowledge_section_text, source_names, status)
    """
    source_names: list[str] = []
    if not chunks:
        return "（未找到相关文档）", source_names, "not_found"

    knowledge_lines: list[str] = []
    seen_contents: set[str] = set()
    for i, chunk in enumerate(chunks[:5]):
        src = chunk.source or "未知来源"
        dedup_key = chunk.content[:80] if chunk.content else ""
        if dedup_key in seen_contents:
            continue
        seen_contents.add(dedup_key)
        if src not in source_names:
            source_names.append(src)
        content = (chunk.content or "")[:max_per_chunk]
        if content:
            knowledge_lines.append(f"**来源 {len(knowledge_lines) + 1}: [{src}]**\n{content}\n")

    section = "\n".join(knowledge_lines) if knowledge_lines else "（未找到相关文档）"
    status = _classify_retrieval_status(knowledge_lines)
    return section, source_names, status


# ═══════════════════════════════════════════════════════════════════════════════════
# LLM call (self-contained — no dependency on graph.py helpers)
# ═══════════════════════════════════════════════════════════════════════════════════

async def _qa_call_llm(model: Any, messages: list) -> str:
    """Call LLM for QA — no tools, text-only response."""
    if hasattr(model, "_agenerate"):
        result = await model._agenerate(messages)
        if result.generations and result.generations[0]:
            msg = result.generations[0].message
            content = msg.content if hasattr(msg, "content") else str(msg)
            return str(content).strip() if content else ""
        return ""
    else:
        dict_msgs = [{"role": "user", "content": str(m.content)} for m in messages]
        content, _, _ = await model.llm_client.complete(dict_msgs, tools=None)
        return str(content).strip() if content else ""


# ═══════════════════════════════════════════════════════════════════════════════════
# Event emitter (self-contained — same pattern as graph.py's _emit)
# ═══════════════════════════════════════════════════════════════════════════════════

def _emit(key: str, value: Any) -> None:
    """Emit a custom event through LangGraph's stream writer."""
    try:
        writer = get_stream_writer()
        writer([{key: value}])
    except RuntimeError:
        pass


# ═══════════════════════════════════════════════════════════════════════════════════
# Node factory
# ═══════════════════════════════════════════════════════════════════════════════════

def make_knowledge_node(model: Any):
    """Create the Knowledge Agent node — auto-search → LLM formats answer.

    Pipeline (no ReAct loop, no tool calls exposed to LLM):
    1. Hybrid retrieval (Qdrant + ripgrep + RRF)
    2. Keyword expansion fallback
    3. Classify retrieval status (found / partial / not_found)
    4. Build grounded QA prompt with status injected
    5. LLM generates answer constrained by status
    """

    async def node_fn(state: dict) -> dict:
        from app.dependencies import get_knowledge_retriever

        _emit("step_started", {"agent_name": "knowledge_agent", "step_index": 0})

        # ── Extract user message ──
        msgs = state.get("messages", [])
        user_msg: str = ""
        for m in reversed(msgs):
            if isinstance(m, HumanMessage):
                user_msg = str(m.content) if hasattr(m, "content") else str(m)
                break
        if not user_msg:
            user_msg = str(msgs[-1].content) if msgs else ""

        # ── Phase 1: Hybrid retrieval ──
        _emit("thinking_start", {})
        _emit("thinking_delta", "检索 GBase 8a 知识库")
        _emit("thinking_end", {})

        retriever = get_knowledge_retriever()
        chunks = await retriever.retrieve(user_msg)

        # Domain expansion fallback
        expanded_query = expand_knowledge_query(user_msg)
        if expanded_query != user_msg:
            expanded_chunks = await retriever.retrieve(expanded_query)
            chunks = merge_knowledge_chunks(expanded_chunks, chunks)

        # ── Phase 2: Build knowledge context with status ──
        knowledge_section, source_names, status = _build_knowledge_section(chunks)

        _emit("tool_call_start", {
            "name": "search_knowledge",
            "args": {"query": user_msg[:100]},
            "agent_name": "knowledge_agent",
        })
        _emit("tool_call_result", {
            "name": "search_knowledge",
            "result": {
                "summary": f"检索到 {len(chunks)} 条相关文档 (状态: {status})",
                "status": status,
            },
        })
        _emit("tool_call_end", {"name": "search_knowledge"})

        # ── Phase 3: Build grounded QA prompt ──
        status_label = {"found": "充分", "partial": "部分相关", "not_found": "未找到"}
        prompt_text = KNOWLEDGE_QA_PROMPT.format(
            knowledge_section=knowledge_section,
            retrieval_status=status_label.get(status, status),
        )
        prompt_text += f"\n## 用户问题\n{user_msg}"

        messages = [HumanMessage(content=prompt_text)]

        # ── Phase 4: LLM generates answer ──
        try:
            answer = await _qa_call_llm(model, messages)
            if not answer:
                answer = "知识库中未找到相关信息，建议查阅 GBase 8a 官方手册。"
        except Exception as e:
            logger.error("Knowledge agent LLM call failed: %s", e)
            answer = f"知识检索处理出错: {e}"

        _emit("delta", answer)
        _emit("state_delta", {"path": "sources", "value": {"sources": source_names, "status": status}})
        _emit("step_finished", {"agent_name": "knowledge_agent"})
        return {
            "knowledge": {
                "knowledge_sources": source_names,
                "answer": answer,
                "status": status,
            },
            "messages": [AIMessage(content=answer)],
        }

    return node_fn
