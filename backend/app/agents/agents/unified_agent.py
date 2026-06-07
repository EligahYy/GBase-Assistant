"""Unified Agent — single ReAct agent with all tools (v3.2).

Replaces the Supervisor-router + multi-Specialist architecture with a single
agent that holds every tool and decides autonomously which to use.

Design principles (inspired by Codex CLI):
- No separate intent router — the prompt + tools IS the routing mechanism
- Plan-then-Act: think before calling tools, don't blindly explore
- Explicit termination: call final_answer to signal completion
- Anti-hallucination: search_knowledge returns status, LLM must respect it
- Loop prevention: same tool + same args ≤ 2 calls
"""

from __future__ import annotations

from typing import Any

from app.agents.tools.base import ToolParameter

# ═══════════════════════════════════════════════════════════════════════════════════
# Final Answer Tool — explicit termination signal
# ═══════════════════════════════════════════════════════════════════════════════════


class FinalAnswerTool:
    """Signal that the agent has gathered enough information and is ready to respond.

    This is the ONLY way to end the agent's turn. The agent MUST call this tool
    (rather than outputting text directly) so the system knows the task is complete.
    """

    @property
    def name(self) -> str:
        return "final_answer"

    @property
    def description(self) -> str:
        return (
            "Submit your final answer to the user. Call this tool when you have "
            "gathered sufficient information and are ready to respond. "
            "This is the ONLY way to finish — do not output text directly."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="answer",
                type="string",
                description="Your final answer to the user, in Chinese, formatted with markdown",
            ),
            ToolParameter(
                name="sources",
                type="array",
                description="List of sources you used (table names, document names, etc.)",
                required=False,
            ),
        ]

    async def execute(self, answer: str = "", sources: list[str] | None = None, **kwargs: Any) -> dict:
        return {"answer": answer or kwargs.get("answer", ""), "sources": sources or kwargs.get("sources", [])}

    def format_result(self, result: dict) -> dict:
        return {"summary": result.get("answer", "")[:100], "detail": result, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string", "description": "Your final answer to the user"},
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of sources used",
                        },
                    },
                    "required": ["answer"],
                },
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════════
# Unified Agent System Prompt
# ═══════════════════════════════════════════════════════════════════════════════════

UNIFIED_AGENT_SYSTEM = """你是 GBase 8a MPP 数据库专家助手。你拥有数据库 Schema 探索、SQL 生成执行、知识库检索和日常对话的全部能力。

## ⚠️ 核心规则（违反将导致错误）

### 终止规则
- **你必须调用 `final_answer` 来结束**：当你准备好回答用户时，调用 `final_answer` 输出最终回复。
  不要直接输出文本而不调用 `final_answer`——系统需要这个信号来确认任务完成。
- **不要过早终止**：在收集到足够信息之前不要调用 `final_answer`。

### 工作流程：先规划，再行动

收到用户请求后，按以下步骤进行：

1. **分析意图**（不调工具）：判断用户需要什么——数据查询？技术知识？两者兼有？
2. **制定计划**（不调工具）：决定需要调用哪些工具、以什么顺序
3. **执行探索**（调工具）：按计划调用工具收集信息
4. **验证充分性**：确认收集的信息足以回答问题
5. **输出回答**：调用 `final_answer`

### 循环禁令
- **同一工具 + 同一参数最多调用 2 次**。如果 2 次都没得到满意结果，说明信息不可得，请基于已有信息回答。
- 如果你发现自己连续 3 轮都在调用工具但没有进展，立即调用 `final_answer` 给出你能提供的最好回答。

---

## 场景指南

### 场景 A：数据查询（SQL 生成）

用户要求查询数据、统计、报表时：

1. `search_schemas` 搜索相关表
2. `get_table_profile` 查看表结构和列信息
3. 必要时 `query_glossary` 查业务术语映射
4. 多表查询时 `find_join_path` 查关联路径
5. 生成 GBase 8a 兼容 SQL
6. `submit_sql` 提交验证和执行
7. 收到验证错误后定向修复（最多 3 轮）
8. 执行成功后调用 `final_answer` 展示结果

**禁止行为**：
- 未查看表结构就生成 SQL
- search_schemas 返回空后不换关键词直接放弃
- 在不确定列名时猜测列名

### 场景 B：GBase 8a 技术知识

用户询问 GBase 8a 的功能、语法、配置、错误码时：

1. `search_knowledge` 检索官方文档
2. 检查返回结果的 `status` 字段：
   - **status="found"**：基于检索内容综合回答
   - **status="partial"**：只回答有明确依据的部分，推测标注"[推测]"
   - **status="not_found"**：诚实说"知识库中未找到该信息"，**严禁编造**
3. 错误码问题额外使用 `lookup_error`
4. `final_answer` 输出回答，注明来源文档

**严禁**：编造知识库中没有的功能、语法、版本号、参数、配置项。
代码示例必须来自知识库原文。

### 场景 C：日常对话

问候、感谢、闲聊时：
- 直接调用 `final_answer` 友好回复
- 不需要调用任何探索工具
- 短暂回复后，如果用户提出具体需求，再按场景 A/B 处理

### 场景 D：混合意图

用户同时要求数据查询 + 知识解释时（如"查询销售额前10的客户，并解释窗口函数用法"）：
- 可以先完成数据查询部分，再检索知识
- 也可以并行思路处理
- 最后调用一次 `final_answer` 整合所有结果

---

## GBase 8a 方言约束

- 只支持只读查询（SELECT/SHOW/DESCRIBE/EXPLAIN）
- 不支持 UPDATE/DELETE/INSERT/DROP/ALTER/TRUNCATE/CREATE
- 不支持 WITH RECURSIVE CTE
- 不支持 WINDOW 子句的 RANGE/ROWS 帧定义
- LIMIT 语法: `LIMIT n OFFSET m` 或 `LIMIT m,n`
- 字符串连接用 `CONCAT()`，不用 `||`
- 日期运算用 `CURDATE() - INTERVAL 1 MONTH`，不用 `DATE_SUB`
- 不支持 FULL OUTER JOIN
- 使用 `GROUP_CONCAT` 而非 `STRING_AGG`

## 输出要求

- 用中文回答，专业简洁
- SQL 结果用表格或代码块展示
- 技术回答注明来源文档
- 不确定的信息标注"[推测]"或直接说不知道
"""


# ═══════════════════════════════════════════════════════════════════════════════════
# Tool registry
# ═══════════════════════════════════════════════════════════════════════════════════


def get_unified_agent_tools(db_id: str = "") -> list[Any]:
    """All tools available to the unified agent.

    The agent decides autonomously which tools to call based on user intent.
    No separate router or specialist delegation is needed.
    """
    from app.agents.tools.error_code_tool import LookupErrorCodeTool
    from app.agents.tools.glossary_tool import QueryGlossaryTool
    from app.agents.tools.knowledge_tools import SearchKnowledgeTool
    from app.agents.tools.schema_tools import FindJoinPathTool, GetTableProfileTool, SearchSchemasTool
    from app.agents.tools.sql_tools import ExecuteSQLTool, SubmitSQLTool
    from app.agents.tools.status_tool import GetDatabaseStatusTool

    tools: list[Any] = [
        # Schema exploration
        SearchSchemasTool(db_id=db_id),
        GetTableProfileTool(db_id=db_id),
        FindJoinPathTool(db_id=db_id),
        # Utility
        QueryGlossaryTool(),
        LookupErrorCodeTool(),
        # Knowledge retrieval
        SearchKnowledgeTool(),
        # SQL
        SubmitSQLTool(),
        ExecuteSQLTool(db_connection_id=db_id),
        # Monitoring
        GetDatabaseStatusTool(db_connection_id=db_id),
        # Termination
        FinalAnswerTool(),
    ]
    return tools


def get_unified_agent_prompt() -> str:
    """Get the unified agent system prompt."""
    return UNIFIED_AGENT_SYSTEM
