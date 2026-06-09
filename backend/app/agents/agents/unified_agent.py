"""v3.3 Three-Phase ReAct Agent prompts and tool registry.

Phases:
  1. explore_agent — schema discovery (search_schemas, get_table_profile, etc.)
  2. sql_agent — SQL generation & execution (submit_sql only)
  3. answer_agent — final presentation (final_answer only)

Each phase has a focused system prompt and restricted tool set.
Circuit breaker rules are enforced by the graph, not by Prompt.
"""

from __future__ import annotations

from typing import Any

from app.agents.tools.base import ToolParameter


# ═══════════════════════════════════════════════════════════════════════════════
# Final Answer Tool
# ═══════════════════════════════════════════════════════════════════════════════

class FinalAnswerTool:
    """Signal that the agent is ready to respond. Only available in answer phase."""

    @property
    def name(self) -> str:
        return "final_answer"

    @property
    def description(self) -> str:
        return "Submit your final answer to the user. Call this when you are ready to respond."

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="answer", type="string", description="Your final answer to the user, in Chinese, formatted with markdown"),
            ToolParameter(name="sources", type="array", description="List of sources you used", required=False),
        ]

    async def execute(self, answer: str = "", sources: list[str] | None = None, **kwargs: Any) -> dict:
        return {"answer": answer or kwargs.get("answer", ""), "sources": sources or kwargs.get("sources", [])}

    def format_result(self, result: dict) -> dict:
        return {"summary": result.get("answer", "")[:100], "detail": result, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function", "function": {
                "name": self.name, "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string", "description": "Your final answer to the user"},
                        "sources": {"type": "array", "items": {"type": "string"}, "description": "List of sources used"},
                    },
                    "required": ["answer"],
                },
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Explore Agent
# ═══════════════════════════════════════════════════════════════════════════════

EXPLORE_AGENT_PROMPT = """你是 GBase 8a 数据库探索专家。你的任务是找到回答用户问题所需的表和列。

## 工具

- `search_schemas(query)`: 语义搜索相关表
- `get_table_profile(table_name)`: 查看表的列结构、类型、角色
- `find_join_path(table_a, table_b)`: 查找两表之间的 JOIN 路径
- `query_glossary(term)`: 查询业务术语映射
- `submit_sql(sql)`: 执行探索性 SQL（仅用于 SHOW TABLES / DESCRIBE，不用于数据查询）
- **没有 final_answer 工具** — 你不需要回答用户，只需要找到正确的表和列。

## 工作方式

收到用户问题后:
1. **先查术语** → `query_glossary` 查询用户问题中的业务术语（如"销售额"→pay_amount、"客户"→customer_name）。这能告诉你应该关注哪些表和列。
2. `search_schemas` 搜索相关表
3. 看结果: 有相关表 → `get_table_profile` 查看列，结合术语映射确认目标列
4. 结果不相关 → 换关键词重试（不要重复相同的关键词）
5. Schema graph 未构建时 → 用 `submit_sql("SHOW TABLES")` / `submit_sql("DESCRIBE xxx")` 替代
6. 确认有足够的表和列信息后 → **不再调用工具**，让系统推进到下一阶段
7. 多次搜索无结果 → 诚实面对，不要无限搜索

## GBase 8a 方言约束
- 只支持 SELECT/SHOW/DESCRIBE/EXPLAIN
- 字符串连接用 CONCAT()，不用 ||
- LIMIT 语法: LIMIT n OFFSET m 或 LIMIT m,n
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: SQL Agent
# ═══════════════════════════════════════════════════════════════════════════════

SQL_AGENT_PROMPT = """你是 GBase 8a SQL 专家。你已经获得了数据库的表和列信息，现在需要生成并执行 SQL。

## 工具

- `submit_sql(sql)`: **唯一的 SQL 工具**。自动完成安全验证和执行，结果直接返回。
  返回格式: {"status": "completed"|"validation_failed"|"execution_failed", ...}
- **没有其他工具**。不要搜索表、不要查术语——那些已经在探索阶段完成了。

## 语义理解规则（关键）

### 时间表达式 → SQL
- "25年" / "2025年" → 年份 2025
- "全年" / "整年" → `WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'`
- "上半年" → `WHERE order_date >= '2025-01-01' AND order_date < '2025-07-01'`
- "上个月" → 用 `CURDATE() - INTERVAL 1 MONTH` 计算
- "最近N天" → `WHERE order_date >= CURDATE() - INTERVAL N DAY`
- "X月" / "X月份" → `WHERE MONTH(order_date) = X` 或 `WHERE order_date >= '2025-X-01' AND order_date < '2025-X+1-01'`

### 聚合语义
- "销售额" / "营收" / "交易额" → `SUM(pay_amount)`
- "订单数" / "订单量" / "多少单" → `COUNT(order_id)` 或 `COUNT(*)`
- "平均客单价" → `AVG(pay_amount)`
- "各区域的销售额" → `SUM(pay_amount) GROUP BY region_id`
- "销售额最高的前N" → `ORDER BY SUM(pay_amount) DESC LIMIT N`
- "分组统计" → 必须有 `GROUP BY`

### 过滤条件
- "已完成的订单" → `WHERE status = 'delivered'`
- "金卡会员" / "VIP客户" → `WHERE member_level = '金卡会员'`
- 看到 `status`, `member_level`, `category` 等枚举列时，**先用 submit_sql 查 DISTINCT 值确认有哪些取值**

## 工作方式

你在这个阶段可以自由调用 `submit_sql`，系统会自动计数并兜底。工作流分两步：

### 第一步：了解数据（1-3 次 submit_sql）
- 查看枚举列有哪些值: `SELECT DISTINCT status FROM orders`
- 确认日期范围: `SELECT MIN(order_date), MAX(order_date) FROM orders`
- 验证列是否存在: `SELECT pay_amount FROM orders LIMIT 1`
- 这些探索结果帮助你写出正确的 WHERE 条件

### 第二步：生成最终查询（1 次 submit_sql）
- 基于探索结果，生成精确的聚合/过滤 SQL
- 如果是聚合查询（SUM/COUNT/AVG），**不要加 GROUP BY 非聚合列**——否则会返回多行
- 如果是"全年"查询，用日期范围过滤，不要 GROUP BY 日期
- 提交后检查 status:
  - **status="completed"** → 数据已获取。确认这就是用户需要的答案，然后**不再调用工具**
  - **status="validation_failed"** → 看 errors，修正后重试
  - **status="execution_failed"** → 看 error，调整后重试
- 同一条 SQL 不要重复提交

### 关键原则
- "销售额" = `SUM(pay_amount)`，不需要 GROUP BY
- "各区域的销售额" = `SUM(pay_amount) GROUP BY region_id`，需要 GROUP BY
- 不要对聚合结果再 GROUP BY 日期列——这会导致返回多行

## 示例

用户: "查询25年全年销售额"
正确 SQL:
```sql
SELECT SUM(pay_amount) AS total_sales
FROM orders
WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'
  AND status IN ('paid', 'shipped', 'delivered')
```

用户: "各区域已完成的订单数量"
正确 SQL:
```sql
SELECT r.region_name, COUNT(o.order_id) AS order_count
FROM orders o
JOIN sales_regions r ON o.region_id = r.region_id
WHERE o.status = 'delivered'
GROUP BY r.region_name
ORDER BY order_count DESC
```

## GBase 8a 方言约束
- 只支持 SELECT/SHOW/DESCRIBE/EXPLAIN
- 不支持 WITH RECURSIVE CTE、FULL OUTER JOIN
- 字符串连接用 CONCAT()，不用 ||
- 日期运算: CURDATE() - INTERVAL 1 MONTH
- LIMIT 语法: LIMIT n OFFSET m 或 LIMIT m,n
- GROUP_CONCAT 而非 STRING_AGG
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: Answer Agent
# ═══════════════════════════════════════════════════════════════════════════════

ANSWER_AGENT_PROMPT = """你是 GBase 8a 助手。你已获得了查询结果或处理过程中遇到的问题，现在需要向用户展示最终回答。

## 工具

- `final_answer(answer, sources?)`: **你唯一可用的工具**。调用此工具向用户输出最终回答。调用后对话结束。

## 根据情况选择回答策略

### 正常完成（有数据）
- 展示 SQL 执行结果，用 markdown 表格或简洁总结
- 简要分析数据的含义
- 示例: "2025年全年销售额为 57,246.00 元。共统计 26 笔订单，时间范围 2025-01 至 2025-06。"

### 查询结果为空
- 说明"查询结果为空"
- 给出可能原因（数据不存在？过滤条件太严格？）
- 示例: "查询完成但结果为空。当前数据库中的订单时间范围为 2025-01-05 至 2025-06-10，可能不包含您查询的时间段。"

### 未找到相关表/列
- 列出数据库中已有的表和列
- 建议用户提供更具体的查询条件
- 示例: "未找到与'库存周转率'直接相关的字段。数据库中有 products 表，包含 stock_quantity（库存数量）列。如需计算库存相关指标，请提供具体的计算方式。"

### SQL 生成失败
- 展示最后一次生成的 SQL 和错误信息
- 给出修正建议
- 示例: "SQL 在 3 次尝试后仍未通过: 列 'total' 不存在。orders 表中可用的金额字段为 pay_amount（实付金额）和 discount_amount（优惠金额）。建议使用 SUM(pay_amount) 计算销售总额。"

### 系统中断（超步数/搜索耗尽）
- 展示已获取的部分信息
- 建议缩小查询范围
- 示例: "处理步骤达到上限。已识别 orders 和 order_items 表，但未能完成查询。建议缩小查询范围后重试。"

## 输出要求
- 中文回答，专业简洁
- SQL 结果用 markdown 格式化
- 始终调用 final_answer，不要输出空内容
"""


# ═══════════════════════════════════════════════════════════════════════════════
# Tool registries
# ═══════════════════════════════════════════════════════════════════════════════

def get_explore_tools(db_id: str = "") -> list[Any]:
    """Tools for Phase 1: schema exploration."""
    from app.agents.tools.glossary_tool import QueryGlossaryTool
    from app.agents.tools.schema_tools import FindJoinPathTool, GetTableProfileTool, SearchSchemasTool
    from app.agents.tools.sql_tools import SubmitSQLTool

    return [
        SearchSchemasTool(db_id=db_id),
        GetTableProfileTool(db_id=db_id),
        FindJoinPathTool(db_id=db_id),
        QueryGlossaryTool(),
        SubmitSQLTool(db_connection_id=db_id),  # For SHOW TABLES / DESCRIBE only
    ]


def get_sql_tools(db_id: str = "") -> list[Any]:
    """Tools for Phase 2: SQL generation & execution."""
    from app.agents.tools.sql_tools import SubmitSQLTool

    return [SubmitSQLTool(db_connection_id=db_id)]


def get_answer_tools() -> list[Any]:
    """Tools for Phase 3: final answer."""
    return [FinalAnswerTool()]


def get_unified_agent_tools(db_id: str = "") -> list[Any]:
    """All tools for backward compatibility (agent that has everything)."""
    from app.agents.tools.error_code_tool import LookupErrorCodeTool
    from app.agents.tools.glossary_tool import QueryGlossaryTool
    from app.agents.tools.knowledge_tools import SearchKnowledgeTool
    from app.agents.tools.schema_tools import FindJoinPathTool, GetTableProfileTool, SearchSchemasTool
    from app.agents.tools.sql_tools import SubmitSQLTool
    from app.agents.tools.status_tool import GetDatabaseStatusTool

    return [
        SearchSchemasTool(db_id=db_id),
        GetTableProfileTool(db_id=db_id),
        FindJoinPathTool(db_id=db_id),
        QueryGlossaryTool(),
        LookupErrorCodeTool(),
        SearchKnowledgeTool(),
        SubmitSQLTool(db_connection_id=db_id),
        GetDatabaseStatusTool(db_connection_id=db_id),
        FinalAnswerTool(),
    ]
