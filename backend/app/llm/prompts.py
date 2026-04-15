"""Prompt 模板管理。使用 f-string 构建，保持简单可维护。"""
from __future__ import annotations

from app.protocols import KnowledgeChunk, SQLExample, TableSchema

# ── 意图分类 ────────────────────────────────────────────────────────────────────

INTENT_SYSTEM = """你是一个意图分类器。根据用户输入，判断其意图并返回 JSON。

意图类型：
- "sql"：用户想查询数据、生成 SQL、分析数据（如"查询..."、"统计..."、"列出..."）
- "qa"：用户在咨询 GBase 8a 数据库的知识、语法、特性、错误（如"支持...吗"、"怎么..."、"什么是..."）
- "general"：其他（问候、闲聊、超出范围的问题）

只返回 JSON，格式：{"intent": "sql"} 或 {"intent": "qa"} 或 {"intent": "general"}

示例：
用户："查询每个部门的员工数" → {"intent": "sql"}
用户："GBase 8a 支持窗口函数吗" → {"intent": "qa"}
用户："你好" → {"intent": "general"}
用户："统计最近30天的订单" → {"intent": "sql"}
用户："创建触发器会报错吗" → {"intent": "qa"}"""


# ── SQL 生成 ────────────────────────────────────────────────────────────────────

SQL_SYSTEM_BASE = """你是 GBase 8a MPP 分析数据库的 SQL 专家。根据用户的自然语言描述，生成正确的 GBase 8a SQL。

## GBase 8a 方言约束（必须严格遵守）

### 不支持的特性（不要生成以下语法）
{unsupported_rules}

### 语法差异
{syntax_rules}

### 函数兼容性
{function_rules}

## 输出格式要求
1. 先输出 SQL，用 ```sql 代码块包裹
2. 再用简洁的中文解释 SQL 逻辑（2-5句话）
3. 如果有注意事项（如性能风险、数据量大等），在最后补充说明

不要输出任何其他内容。"""


def build_sql_prompt(
    message: str,
    dialect_rules: dict,
    schemas: list[TableSchema],
    examples: list[SQLExample],
    history: list[dict] | None = None,
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

    # 追加 Schema 信息
    if schemas:
        schema_section = "\n## 目标数据库 Schema\n"
        for s in schemas:
            schema_section += f"\n-- 表: {s.table_name}"
            if s.description:
                schema_section += f" ({s.description})"
            schema_section += f"\n{s.ddl}\n"
        system_content += schema_section
    else:
        system_content += "\n\n## 注意\n当前未选择数据库，请基于用户描述推断表结构生成通用 SQL。"

    # Few-shot 示例
    if examples:
        system_content += "\n\n## 参考示例\n"
        for ex in examples:
            system_content += f"\n用户问题：{ex.question}\n```sql\n{ex.sql}\n```\n"

    messages: list[dict] = [{"role": "system", "content": system_content}]

    # 注入对话历史（最近 6 轮）
    if history:
        messages.extend(history[-12:])  # 最多 6 轮，每轮 2 条

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
        messages.extend(history[-12:])

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
        f"问题：\n"
        + "\n".join(f"- {e}" for e in errors)
        + "\n\n请重新生成符合 GBase 8a 规范的 SQL。"
    )
    return existing_messages + [{"role": "user", "content": correction}]


# ── General Chat ────────────────────────────────────────────────────────────────

GENERAL_SYSTEM = """你是 GBase 8a 数据库助手。你的主要功能是帮助用户生成 SQL 和解答 GBase 8a 相关问题。

如果用户的问题与数据库相关，引导他们描述具体需求；如果是问候或闲聊，简短友好地回应并引导回正题。"""


def build_general_prompt(message: str, history: list[dict] | None = None) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": GENERAL_SYSTEM}]
    if history:
        messages.extend(history[-6:])
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
