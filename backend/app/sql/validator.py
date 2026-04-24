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

    # ── Layer 2b: GROUP BY / JOIN 检查 ─────────────────────────────────────────
    warnings.extend(_check_group_by_compliance(statement))
    warnings.extend(_check_join_conditions(statement))

    # ── Layer 2c: GBase 8a DDL 特有规则 ────────────────────────────────────────
    ddl_errors, ddl_warnings = _check_gbase_ddl(sql)
    errors.extend(ddl_errors)
    warnings.extend(ddl_warnings)

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


def _check_group_by_compliance(statement: exp.Expression) -> list[str]:
    """检查 GROUP BY 合规性：非聚合列必须出现在 GROUP BY 中。"""
    warnings = []
    for select in statement.find_all(exp.Select):
        group = select.args.get("group")
        if not group:
            continue
        group_cols = set()
        for gcol in group.expressions:
            if isinstance(gcol, exp.Column):
                group_cols.add(gcol.name.lower())
        for expr in select.expressions:
            if isinstance(expr, (exp.AggFunc, exp.Count)):
                continue
            if isinstance(expr, exp.Alias):
                inner = expr.this
                if isinstance(inner, (exp.AggFunc, exp.Count)):
                    continue
                if isinstance(inner, exp.Column):
                    if inner.name.lower() not in group_cols:
                        warnings.append(f"GROUP BY 中缺少非聚合列 '{inner.name}'")
            elif isinstance(expr, exp.Column):
                if expr.name.lower() not in group_cols:
                    warnings.append(f"GROUP BY 中缺少非聚合列 '{expr.name}'")
    return warnings


def _check_join_conditions(statement: exp.Expression) -> list[str]:
    """检查 JOIN 是否有 ON / USING 条件（提醒可能的笛卡尔积）。"""
    warnings = []
    for join in statement.find_all(exp.Join):
        on_clause = join.args.get("on")
        using_clause = join.args.get("using")
        if not on_clause and not using_clause:
            warnings.append("JOIN 缺少 ON/USING 条件，可能产生笛卡尔积")
    return warnings


def _check_gbase_ddl(sql: str) -> tuple[list[str], list[str]]:
    """检查 GBase 8a 特有 DDL 规则（DISTRIBUTED BY / REPLICATED）。"""
    errors = []
    warnings = []
    sql_upper = sql.upper()

    has_replicated = "REPLICATED" in sql_upper
    has_distributed = "DISTRIBUTED BY" in sql_upper

    if has_replicated and has_distributed:
        errors.append("REPLICATED 和 DISTRIBUTED BY 不能同时使用")

    if has_distributed:
        dist_match = re.search(r"DISTRIBUTED\s+BY\s*\(?(?:['\"])?([^')\"]+)(?:['\"])?\)?", sql, re.IGNORECASE)
        if dist_match:
            dist_col = dist_match.group(1).strip().lower()
            cols_match = re.search(r"CREATE\s+TABLE\s+[^\(]+\(([^)]+)\)", sql, re.IGNORECASE | re.DOTALL)
            if cols_match:
                cols_text = cols_match.group(1)
                create_cols = set()
                for line in cols_text.split(","):
                    parts = line.strip().split()
                    if parts:
                        col_name = parts[0].strip("`\"'").lower()
                        if col_name and col_name not in ("primary", "unique", "index", "constraint", "foreign"):
                            create_cols.add(col_name)
                if dist_col not in create_cols:
                    errors.append(f"DISTRIBUTED BY 列 '{dist_col}' 不存在于表定义中")

    return errors, warnings


def _check_schema_references(
    statement: exp.Expression, schemas: list[TableSchema]
) -> tuple[list[str], list[str]]:
    """交叉引用 SQL 中的表名/列名与已知 schema。"""
    errors = []
    warnings = []

    known_tables = {s.table_name.lower(): s for s in schemas}

    # 提取 SQL 中引用的表名
    referenced_tables = set()
    for table in statement.find_all(exp.Table):
        if table.name:
            referenced_tables.add(table.name.lower())

    # 检查未知表
    for tbl in referenced_tables:
        if tbl and tbl not in known_tables:
            warnings.append(f"表 '{tbl}' 在当前 Schema 中未找到，请确认表名是否正确")

    # ── 列名交叉引用 ──────────────────────────────────────────────────────────
    # 构建别名 -> 实际表名映射
    alias_to_table: dict[str, str] = {}
    for table in statement.find_all(exp.Table):
        if table.name and table.alias:
            alias_to_table[table.alias.lower()] = table.name.lower()

    # 收集所有已知列（按表）
    table_columns: dict[str, set[str]] = {}
    for s in schemas:
        if s.columns:
            table_columns[s.table_name.lower()] = {c.lower() for c in s.columns}

    for col in statement.find_all(exp.Column):
        col_name = col.name.lower() if col.name else None
        if not col_name:
            continue

        # 跳过函数参数中的列（如 COUNT(*)）
        parent = col.parent
        if isinstance(parent, exp.Alias):
            parent = parent.parent
        if isinstance(parent, exp.Func):
            continue

        table_ref = col.table.lower() if col.table else None

        if table_ref:
            # 有表前缀：u.name
            real_table = alias_to_table.get(table_ref, table_ref)
            cols = table_columns.get(real_table, set())
            if cols and col_name not in cols:
                warnings.append(f"列 '{col_name}' 在表 '{real_table}' 中不存在")
        else:
            # 无表前缀：检查是否存在于任何引用的表中
            all_ref_cols: set[str] = set()
            for tbl in referenced_tables:
                all_ref_cols.update(table_columns.get(tbl, set()))
            if all_ref_cols and col_name not in all_ref_cols:
                warnings.append(f"列 '{col_name}' 在已知 Schema 中未找到")

    return errors, warnings
