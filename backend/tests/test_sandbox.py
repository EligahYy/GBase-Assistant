"""SQL 执行沙箱安全测试。"""

from __future__ import annotations

import pytest

from app.sql.sandbox import SQLSandbox, SQLSandboxError


class TestSandboxReadonly:
    """只读拦截测试。"""

    def setup_method(self):
        self.sandbox = SQLSandbox()

    def test_select_allowed(self):
        """SELECT 应通过验证。"""
        self.sandbox._validate_readonly("SELECT * FROM users")
        self.sandbox._validate_readonly("SELECT id, name FROM orders WHERE status = 1")

    def test_insert_blocked(self):
        """INSERT 应被拒绝。"""
        with pytest.raises(SQLSandboxError, match="INSERT"):
            self.sandbox._validate_readonly("INSERT INTO users VALUES (1, 'test')")

    def test_update_blocked(self):
        """UPDATE 应被拒绝。"""
        with pytest.raises(SQLSandboxError, match="UPDATE"):
            self.sandbox._validate_readonly("UPDATE users SET name = 'test' WHERE id = 1")

    def test_delete_blocked(self):
        """DELETE 应被拒绝。"""
        with pytest.raises(SQLSandboxError, match="DELETE"):
            self.sandbox._validate_readonly("DELETE FROM users WHERE id = 1")

    def test_drop_blocked(self):
        """DROP 应被拒绝。"""
        with pytest.raises(SQLSandboxError, match="DROP"):
            self.sandbox._validate_readonly("DROP TABLE users")

    def test_alter_blocked(self):
        """ALTER 应被拒绝。"""
        with pytest.raises(SQLSandboxError, match="ALTER"):
            self.sandbox._validate_readonly("ALTER TABLE users ADD COLUMN age INT")

    def test_create_blocked(self):
        """CREATE 应被拒绝。"""
        with pytest.raises(SQLSandboxError, match="CREATE"):
            self.sandbox._validate_readonly("CREATE TABLE test (id INT)")

    def test_truncate_blocked(self):
        """TRUNCATE 应被拒绝。"""
        with pytest.raises(SQLSandboxError, match="TRUNCATE"):
            self.sandbox._validate_readonly("TRUNCATE TABLE users")

    def test_grant_blocked(self):
        """GRANT 应被拒绝。"""
        with pytest.raises(SQLSandboxError, match="GRANT"):
            self.sandbox._validate_readonly("GRANT SELECT ON users TO test_user")

    def test_show_describe_allowed(self):
        """SHOW 和 DESCRIBE 应通过验证。"""
        self.sandbox._validate_readonly("SHOW TABLES")
        self.sandbox._validate_readonly("DESCRIBE users")

    def test_multiline_select_allowed(self):
        """多行 SELECT 应通过。"""
        sql = """
            SELECT u.name, o.amount
            FROM users u
            JOIN orders o ON u.id = o.user_id
            WHERE u.status = 1
        """
        self.sandbox._validate_readonly(sql)
