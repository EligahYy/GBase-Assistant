"""Prompt 模板管理。使用 f-string 构建，保持简单可维护。"""

from __future__ import annotations

from app.protocols import KnowledgeChunk, SQLExample, TableSchema

# ── SQL 生成 ────────────────────────────────────────────────────────────────────

SQL_SYSTEM_BASE = """你是 GBase 8a MPP 分析数据库的 SQL 专家。根据用户的自然语言描述，生成正确的 GBase 8a SQL。

## GBase 8a 方言约束（必须严格遵守）

### 不支持的特性（不要生成以下语法）
{unsupported_rules}

### 语法差异
{syntax_rules}

### 函数兼容性
{function_rules}

### 系统监控查询（GBase 8a 系统表）
当用户询问数据库运行状态时，可查询以下系统表：
- information_schema.PROCESSLIST — 当前连接和正在执行的查询
- information_schema.TABLES — 表元数据（行数、数据大小、创建时间）
- information_schema.COLUMNS — 列元数据

常用查询模板：
- 当前连接数: SELECT COUNT(*) FROM information_schema.PROCESSLIST
- 运行时间: SELECT DATEDIFF(NOW(), MIN(create_time)) AS running_days FROM information_schema.TABLES
- 慢查询(>10s): SELECT id, user, host, db, time, info FROM information_schema.PROCESSLIST WHERE time > 10
- 表大小排行: SELECT TABLE_NAME, TABLE_ROWS, ROUND(DATA_LENGTH/1024/1024,2) AS size_mb FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() ORDER BY DATA_LENGTH DESC
- 数据分布: SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_ROWS DESC

## 输出格式要求
1. 先输出 SQL，用 ```sql 代码块包裹
2. 再用简洁的中文解释 SQL 逻辑（2-5句话）
3. 如果有注意事项（如性能风险、数据量大等），在最后补充说明

不要输出任何其他内容。"""


def _build_turn_index(history: list[dict]) -> str | None:
    """构建对话轮次索引，帮助 LLM 回溯历史版本。不修改原始消息内容。"""
    if not history:
        return None
    lines = []
    turn = 0
    for msg in history:
        if msg["role"] == "user":
            turn += 1
        preview = msg["content"][:50].replace("\n", " ")
        if len(msg["content"]) > 50:
            preview += "..."
        lines.append(f"第{turn}轮 {msg['role']}: {preview}")
    return "对话历史索引（供你回溯定位用，回复时严禁使用此格式）：\n" + "\n".join(lines)


def build_sql_prompt(
    message: str,
    dialect_rules: dict,
    schemas: list[TableSchema],
    examples: list[SQLExample],
    history: list[dict] | None = None,
    business_terms: dict | None = None,
    chart_config: dict | None = None,
) -> list[dict]:
    """构建 SQL 生成的完整消息列表。"""
    unsupported = _format_unsupported(dialect_rules.get("unsupported", []))
    syntax = _format_syntax(dialect_rules.get("syntax", []))
    functions = _format_functions(dialect_rules.get("functions", {}))

    system_content = SQL_SYSTEM_BASE.format(
        unsupported_rules=unsupported,
        syntax_rules=syntax,
        function_rules=functions,
    )

    # 🆕 追加 Schema 信息（含列元数据）
    if schemas:
        schema_section = "\n## 目标数据库 Schema\n"
        for s in schemas:
            schema_section += f"\n-- 表: {s.table_name}"
            if s.description:
                schema_section += f" ({s.description})"
            schema_section += "\n"
            # 显示列角色、标签、枚举值（若可用）
            if s.columns:
                col_lines = []
                for c in s.columns:
                    col_line = f"--   {c.get('name', '?')} {c.get('type', '?')}"
                    if c.get('role') and c['role'] != 'UNKNOWN':
                        col_line += f" [{c['role']}]"
                    if c.get('label'):
                        col_line += f" -- {c['label']}"
                    if c.get('enum_values'):
                        ev = ", ".join(f"{k}={v}" for k, v in c['enum_values'].items())
                        col_line += f" 枚举: {ev}"
                    col_lines.append(col_line)
                schema_section += "\n".join(col_lines) + "\n"
            else:
                # 回退到原始 DDL
                schema_section += f"{s.ddl}\n"
        system_content += schema_section
    else:
        system_content += "\n\n## 注意\n当前未选择数据库，请基于用户描述推断表结构生成通用 SQL。"

    # 🆕 注入业务术语映射
    if business_terms:
        bt_lines = ["\n## 业务术语映射（已知的语义对应关系）"]
        for term, info in business_terms.items():
            if isinstance(info, dict):
                tbl = info.get("table", "")
                col = info.get("column", "")
                tmpl = info.get("sql_template", "")
                line = f"- **{term}** -> {tbl}.{col}"
                if tmpl:
                    line += f" (表达式: {tmpl})"
                bt_lines.append(line)
        system_content += "\n".join(bt_lines)

    # Few-shot 示例
    if examples:
        system_content += "\n\n## 参考示例\n"
        for ex in examples:
            system_content += f"\n用户问题：{ex.question}\n```sql\n{ex.sql}\n```\n"

    # 🆕 图表输出指令
    chart_instruction = (
        "\n\n## 图表输出要求\n"
        "如果你的查询结果适合图表展示，请在 SQL 代码块之后输出一个 JSON 图表配置（用 ```chart_config 代码块包裹）。"
        "格式: {\"type\": \"bar|line|pie|scatter\", \"title\": \"图表标题\", "
        "\"x_axis\": {\"column\": \"列名\", \"label\": \"X轴标签\"}, "
        "\"y_axis\": {\"column\": \"列名\", \"label\": \"Y轴标签\", \"aggregation\": \"SUM|COUNT|AVG\"}}\n"
        "只在结果有明确的维度和度量时输出图表配置，纯列表查询不需要。\n"
    )
    if chart_config:
        chart_instruction += f"\n用户期望的图表类型: {chart_config.get('type', 'bar')}"
    system_content += chart_instruction

    messages: list[dict] = [{"role": "system", "content": system_content}]

    # 注入对话历史：先附加轮次索引（独立 system message），再附加原始消息
    if history:
        index = _build_turn_index(history)
        if index:
            messages.append({"role": "system", "content": index})
        messages.extend(history)

    messages.append({"role": "user", "content": message})
    return messages


# ── 知识问答 ────────────────────────────────────────────────────────────────────

QA_SYSTEM = """你是 GBase 8a 数据库专家助手，专注于回答 GBase 8a 相关的技术问题。

回答要求：
1. 准确、简洁，直接回答问题
2. 如有代码示例，用代码块格式化
3. 如果知识库提供了参考内容，基于参考内容回答并注明来源
4. 如果问题超出 GBase 8a 范围，礼貌说明并尝试提供相关信息

{knowledge_section}"""


def build_qa_prompt(
    message: str,
    knowledge_chunks: list[KnowledgeChunk],
    history: list[dict] | None = None,
) -> list[dict]:
    """构建知识问答的完整消息列表。"""
    if knowledge_chunks:
        knowledge_section = "## 参考知识库\n"
        for chunk in knowledge_chunks:
            knowledge_section += f"\n**来源**: {chunk.source}\n{chunk.content}\n"
    else:
        knowledge_section = ""

    system_content = QA_SYSTEM.format(knowledge_section=knowledge_section)
    messages: list[dict] = [{"role": "system", "content": system_content}]

    if history:
        index = _build_turn_index(history)
        if index:
            messages.append({"role": "system", "content": index})
        messages.extend(history)

    messages.append({"role": "user", "content": message})
    return messages


# ── SQL 自纠错 ──────────────────────────────────────────────────────────────────


def build_sql_correction_prompt(
    original_message: str,
    failed_sql: str,
    errors: list[str],
    existing_messages: list[dict],
) -> list[dict]:
    """在已有消息列表基础上追加纠错指令。"""
    correction = (
        f"上面生成的 SQL 存在以下问题，请修正：\n"
        f"错误的 SQL：\n```sql\n{failed_sql}\n```\n"
        f"问题：\n" + "\n".join(f"- {e}" for e in errors) + "\n\n请重新生成符合 GBase 8a 规范的 SQL。"
    )
    return existing_messages + [{"role": "user", "content": correction}]


# ── General Chat ────────────────────────────────────────────────────────────────

GENERAL_SYSTEM = """你是 GBase 8a 数据库助手。你可以回答一般性问题、进行友好对话。

如果用户的问题涉及数据库查询或技术问题，引导他们描述具体需求（如"我想查询销售额"或"GBase 8a 如何创建分区表"），以便为你提供更精准的帮助。"""


def build_general_prompt(message: str, history: list[dict] | None = None) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": GENERAL_SYSTEM}]
    if history:
        index = _build_turn_index(history)
        if index:
            messages.append({"role": "system", "content": index})
        messages.extend(history)
    messages.append({"role": "user", "content": message})
    return messages


# ── 辅助格式化 ──────────────────────────────────────────────────────────────────


def _format_unsupported(rules: list[dict]) -> str:
    if not rules:
        return "暂无特殊限制记录"
    lines = []
    for r in rules:
        line = f"- **{r.get('feature', '')}**：{r.get('description', '')}"
        if r.get("suggestion"):
            line += f"（建议：{r['suggestion']}）"
        lines.append(line)
    return "\n".join(lines)


def _format_syntax(rules: list[dict]) -> str:
    if not rules:
        return "暂无特殊语法记录"
    lines = []
    for r in rules:
        line = f"- **{r.get('name', '')}**：{r.get('description', '')}"
        if r.get("pattern"):
            line += f"\n  语法：`{r['pattern']}`"
        lines.append(line)
    return "\n".join(lines)


def _format_functions(rules: dict) -> str:
    lines = []
    for fn in rules.get("supported", []):
        lines.append(f"- ✅ {fn.get('name', '')}：{fn.get('note', '支持')}")
    for fn in rules.get("unsupported", []):
        line = f"- ❌ {fn.get('name', '')}：不支持"
        if fn.get("alternative"):
            line += f"，替代方案：{fn['alternative']}"
        lines.append(line)
    return "\n".join(lines) if lines else "暂无函数兼容性记录"
