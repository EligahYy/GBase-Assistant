"""SQL 验证：语法检查 + GBase 8a 方言合规 + Schema 交叉引用。"""
from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from app.protocols import TableSchema, ValidationResult
from app.sql.dialect import UNSUPPORTED_KEYWORDS


def validate_sql(sql: str, schemas: list[TableSchema] | None = None) -> ValidationResult:
    """
    三层验证：
    1. sqlglot 语法解析
    2. GBase 8a 方言合规检查（关键词 + AST）
    3. Schema 交叉引用（可选，需传入 schemas）
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ── Layer 1: 语法解析 ────────────────────────────────────────────────────────
    try:
        statements = sqlglot.parse(sql, dialect="mysql")  # 用 mysql 方言解析（最接近 GBase 8a）
        if not statements or statements[0] is None:
            errors.append("SQL 解析失败：语句为空或无法识别")
            return ValidationResult(is_valid=False, errors=errors)
    except sqlglot.errors.ParseError as e:
        errors.append(f"SQL 语法错误：{e}")
        return ValidationResult(is_valid=False, errors=errors)

    statement = statements[0]

    # ── Layer 2: 方言合规 ────────────────────────────────────────────────────────
    sql_upper = sql.upper()

    # 快速关键词预检（大小写不敏感）
    for kw in UNSUPPORTED_KEYWORDS:
        if kw in sql_upper:
            errors.append(f"GBase 8a 不支持 {kw} 语法")

    # AST 级检查
    dialect_errors = _check_dialect_compliance(statement)
    errors.extend(dialect_errors)

    # 安全检查：DML 警告
    safety_warnings = _check_safety(statement)
    warnings.extend(safety_warnings)

    # ── Layer 3: Schema 交叉引用 ────────────────────────────────────────────────
    if schemas:
        schema_errors, schema_warnings = _check_schema_references(statement, schemas)
        errors.extend(schema_errors)
        warnings.extend(schema_warnings)

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def extract_sql_from_markdown(text: str) -> str | None:
    """从 LLM 输出的 markdown 文本中提取 SQL 代码块。"""
    # 匹配 ```sql ... ``` 或 ``` ... ```
    pattern = r"```(?:sql)?\s*\n?([\s\S]*?)```"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # 如果没有代码块，尝试直接提取（以 SELECT/INSERT/UPDATE/DELETE/CREATE 开头）
    sql_pattern = r"((?:SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|WITH)\b[\s\S]+?)(?:\n\n|$)"
    match = re.search(sql_pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _check_dialect_compliance(statement: exp.Expression) -> list[str]:
    """遍历 AST，检查 GBase 8a 不支持的特性。"""
    errors = []

    # 检查 CREATE TRIGGER
    if isinstance(statement, exp.Create):
        kind = statement.args.get("kind", "")
        if str(kind).upper() == "TRIGGER":
            errors.append("GBase 8a 不支持触发器（CREATE TRIGGER）")
        elif str(kind).upper() == "EVENT":
            errors.append("GBase 8a 不支持事件调度器（CREATE EVENT）")

    # 检查 FOR UPDATE / LOCK IN SHARE MODE
    for lock in statement.find_all(exp.Lock):
        errors.append("GBase 8a 不支持 SELECT ... FOR UPDATE / LOCK IN SHARE MODE")

    return errors


def _check_safety(statement: exp.Expression) -> list[str]:
    """安全检查，返回警告（不阻断，但提示用户注意）。"""
    warnings = []

    # DML 警告（Phase 1 只生成 SELECT）
    if isinstance(statement, (exp.Insert, exp.Update, exp.Delete)):
        warnings.append("当前为数据修改语句（DML），请确认执行前已备份数据")

    # DROP 警告
    if isinstance(statement, exp.Drop):
        warnings.append("DROP 语句将永久删除对象，请谨慎执行")

    # SELECT * 警告
    for select in statement.find_all(exp.Select):
        for col in select.expressions:
            if isinstance(col, exp.Star):
                warnings.append("建议避免 SELECT *，明确指定需要的列以提升性能")
                break

    return warnings


def _check_schema_references(
    statement: exp.Expression, schemas: list[TableSchema]
) -> tuple[list[str], list[str]]:
    """交叉引用 SQL 中的表名/列名与已知 schema。"""
    errors = []
    warnings = []

    known_tables = {s.table_name.lower() for s in schemas}

    # 提取 SQL 中引用的表名
    referenced_tables = set()
    for table in statement.find_all(exp.Table):
        if table.name:
            referenced_tables.add(table.name.lower())

    # 检查未知表
    for tbl in referenced_tables:
        if tbl and tbl not in known_tables:
            warnings.append(f"表 '{tbl}' 在当前 Schema 中未找到，请确认表名是否正确")

    return errors, warnings
