# Phase 2: Schema Knowledge Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 GBase DDL 中提取结构化语义元数据，构建 Schema Knowledge Graph（表/列语义索引 + JOIN 关系图），为 Phase 3 的 Schema Grounding Agent 提供多策略检索能力。

**Architecture:** 新增 `app/agents/schema_graph.py` 模块，包含 DDL 语义解析器、Schema Graph 构建器、多策略检索引擎。Schema Graph 以 JSON 持久化到 `backend/data/schema_graph/<db_id>.json`，向量索引用 Qdrant `schema_semantic` 集合。通过 `get_schema_graph()` 工厂函数获取实例。

**Tech Stack:** Python 3.12+, sqlglot, Qdrant, json

---

## 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `backend/app/agents/schema_graph.py` | DDL 语义解析 + Schema Graph 构建 + 多策略检索 | **新建** |
| `backend/tests/test_agents/test_schema_graph.py` | Schema Graph 单元测试 | **新建** |
| `backend/app/agents/graph.py` | schema_grounding_node 接入 Schema Graph | **修改** |

---

### Task 1: DDL 语义解析器

**Files:**
- Create: `backend/app/agents/schema_graph.py`
- Create: `backend/tests/test_agents/test_schema_graph.py`

DDL 语义解析器从 CREATE TABLE 语句中提取：
- 表名、列名、类型、COMMENT
- 列角色推断（PRIMARY_KEY / MEASURE / TIME_DIMENSION / ENUM / FOREIGN_KEY / UNKNOWN）
- 表级信息（DISTRIBUTED BY / REPLICATED）

```python
# 核心数据结构
@dataclass
class ColumnMeta:
    name: str
    data_type: str
    role: str              # PRIMARY_KEY | MEASURE | TIME_DIMENSION | ENUM | FOREIGN_KEY | UNKNOWN
    label: str             # 中文标签（从 COMMENT 提取或推断）
    aliases: list[str]     # 同义词列表
    comment: str           # 原始 COMMENT
    enum_values: dict | None  # ENUM 类型的值映射

@dataclass
class TableMeta:
    name: str
    label: str
    aliases: list[str]
    columns: list[ColumnMeta]
    distribution: str      # DISTRIBUTED BY('col') or REPLICATED
    relationships: list[dict]  # JOIN 关系
```

### Task 2: 别名生成器

从 COMMENT + 列名自动生成中文别名：
- COMMENT 优先（如 `COMMENT '订单金额(元)'` → label="订单金额(元)"）
- 无 COMMENT 时从列名推断（如 `order_amount` → "订单金额"）
- LLM 辅助生成同义词列表（使用 LiteLLM，低 temperature）

### Task 3: 关系推断器

推断表之间的 JOIN 关系：
- 命名约定匹配（`customer_no` → `customer.customer_no`）
- 列名后缀匹配（`_id`, `_no`, `_code`）
- LLM 辅助验证（确认推断的外键关系是否合理）

### Task 4: Schema Graph 存储 + 加载

- 构建后持久化到 `backend/data/schema_graph/<db_id>.json`
- 加载时优先从 JSON 文件读取
- 增量更新机制：DDL 变更时重新构建

### Task 5: 多策略检索引擎

- **L1 精确匹配:** 表名/列名/别名 → 精确字典查找
- **L2 向量语义:** COMMENT 嵌入 → Qdrant 向量搜索
- **L3 关系查找:** 命中表之间的最短 JOIN 路径

### Task 6: 集成到 schema_grounding_node

将 Phase 1 的 `schema_grounding_node` stub 替换为调用 Schema Graph 检索。

---

## 任务列表

### Task 1: ColumnMeta + TableMeta 数据结构 + DDL 解析

### Task 2: 别名生成器（COMMENT + 列名推断 + LLM 同义词）

### Task 3: 关系推断器（命名约定 + LLM 验证）

### Task 4: JSON 持久化 + 加载

### Task 5: 多策略检索 + 集成测试

### Task 6: 接入 graph.py 的 schema_grounding_node
