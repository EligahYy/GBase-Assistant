"""GBase 8a sqlglot 方言定义。继承 MySQL 方言并覆写不支持的特性。"""
from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.dialects.mysql import MySQL


class GBase8A(MySQL):
    """
    GBase 8a MPP 数据库方言。
    声称 MySQL 兼容，但有重要差异：
    - 不支持触发器、存储过程游标、部分 DDL 操作
    - 支持 DISTRIBUTED BY / REPLICATED 建表语法
    - 不支持 LOCK TABLES / SELECT ... FOR UPDATE
    """

    class Tokenizer(MySQL.Tokenizer):
        # GBase 8a 关键字扩展
        KEYWORDS = {
            **MySQL.Tokenizer.KEYWORDS,
            "DISTRIBUTED": sqlglot.tokens.TokenType.VAR,
            "REPLICATED": sqlglot.tokens.TokenType.VAR,
        }

    class Parser(MySQL.Parser):
        pass

    class Generator(MySQL.Generator):
        pass


# 注册方言，允许 sqlglot.transpile(dialect="gbase8a") 调用
sqlglot.dialects.Dialects.GBASE8A = "gbase8a"  # type: ignore[attr-defined]

# 不支持的语句类型（用于验证层检查）
UNSUPPORTED_STATEMENT_TYPES = {
    exp.Create: ["TRIGGER", "PROCEDURE"],  # 不支持触发器；存储过程有限支持
    exp.Transaction: None,  # 事务支持有限
}

# 不支持的子句关键词（字符串匹配，用于快速预检）
UNSUPPORTED_KEYWORDS = frozenset([
    "FOR UPDATE",
    "LOCK IN SHARE MODE",
    "LOCK TABLES",
    "UNLOCK TABLES",
    "CREATE TRIGGER",
    "DROP TRIGGER",
    "ALTER TRIGGER",
    "CREATE EVENT",
])
