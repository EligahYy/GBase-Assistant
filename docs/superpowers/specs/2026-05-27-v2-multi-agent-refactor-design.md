# GBase 8a Assistant v2: 多智能体全局架构设计

> **状态:** 已批准 | **分支:** `v2-multi-agent-refactor` | **日期:** 2026-05-27

## 1. 目标

将 GBase 8a 助手从单体链路（意图分类→检索→LLM生成→验证）重构为**多智能体协作系统**，解决两个核心问题：
- NL2SQL 准确率：自然语言→实际库表映射的 Grounding 精度
- 连接状态感知：从轮询改为实时推送（v1 已解决，v2 整合入新架构）

## 2. 架构总览

三层架构：**接入层 → 编排层 → 记忆与知识层**

```
┌──────────────────────────────────────────────────────────────────┐
│                     L1: 接入层 (Gateway)                           │
│                                                                  │
│   Vue 3 Chat UI ←── AG-UI SSE ──→ FastAPI Gateway                │
│                                                                  │
│   协议: AG-UI (Agent-User Interaction Protocol)                   │
│   传输: POST /api/chat/run (发起) + SSE /api/chat/stream (事件流)  │
│   事件: RUN_STARTED, TOOL_CALL_START/END, TEXT_MESSAGE_CONTENT,   │
│         STATE_DELTA, TOOL_CALL_RESULT, RUN_FINISHED               │
│   职责: 认证、流式传输、会话管理、连接状态推送、Agent 过程可见性       │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                  L2: 编排层 (Orchestration)                        │
│                  LangGraph StateGraph + AgentState                │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              Orchestrator Agent (ReAct Loop)                │  │
│  │  Think→Plan→Act→Observe→Decide                             │  │
│  └──────────┬─────────────────────────────────────────────────┘  │
│             │                                                    │
│   ┌─────────┼──────────┬──────────────┐                         │
│   ▼         ▼          ▼              ▼                         │
│ Schema  │  SQL     │ Knowledge   │ General                     │
│ Grounding│ Specialist│ Specialist  │ Specialist                 │
│ Agent   │  Agent   │  Agent      │  Agent                      │
│         │    │     │              │                             │
│         │ ┌──▼──┐  │              │                             │
│         │ │SQL  │  │              │                             │
│         │ │Verif│  │              │                             │
│         │ └──┬──┘  │              │                             │
│         │ ┌──▼──┐  │              │                             │
│         │ │SQL  │  │              │                             │
│         │ │Exec │  │              │                             │
│         │ └─────┘  │              │                             │
└─────────┴──────────┴──────────────┴─────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                   L3: 记忆与知识层 (Memory)                         │
│                                                                  │
│  Session Memory │ Schema Knowledge Graph │ Feedback Learner      │
│  (AgentState)   │ (表/列语义+JOIN图)      │ (持续学习闭环)         │
│                                                                  │
│  存储: SQLite (持久) + Qdrant (向量) + AgentState (会话)          │
└──────────────────────────────────────────────────────────────────┘
```

## 3. 设计原则与借鉴

| 原则 | 借鉴来源 | 说明 |
|------|---------|------|
| Orchestrator-Subagent 模式 | Anthropic Claude Agent SDK | 1 个 Orchestrator 路由到 N 个 Specialist，各自独立上下文 |
| ReAct 循环 | Swiggy Hermes V3 | Think→Plan→Act→Observe→Decide，每步可审计 |
| Plan→Execute→Verify 闭环 | Manus (Meta) | SQL 路径天然适配：规划→生成→验证→执行 |
| Agent as Tool | Manus | Specialist 是可调用工具，非对等对话体，减少通信摩擦 |
| 文件系统即外部记忆 | Manus | Schema Graph 存磁盘，Agent 按需读写，不占 LLM 上下文 |
| 置信度 1-3 级评分 | Hermes V3 | 用户可感知系统对结果的把握程度 |
| 生成假设说明 | Hermes V3 | 展示系统做了哪些假设（如"'销售额'映射为 order_amount"） |
| 反馈驱动持续学习 | Hermes V3 + Hermes Agent (Nous) | 用户行为 → 正/反例 → 更新 Schema Graph → 下次更准 |
| RRF 多策略融合 | 已有 v1 架构 | 精确+语义+关键词三层检索，RRF 融合排序 |
| AG-UI 标准事件协议 | CopilotKit / Google A2A | 标准化 SSE 事件类型，Agent 过程对前端可见，工具调用可追踪 |
| 级联问题防护 | Anthropic | 重试上限、循环检测、成本控制 |

## 4. Agent 定义

### 4.1 Orchestrator Agent

**角色:** 系统大脑，负责 Think→Plan→Act→Observe→Decide 的 ReAct 循环

**职责:**
- **Think:** 理解用户意图，查询 Schema Knowledge Graph 获取相关元数据
- **Plan:** 将复杂问题拆解为子任务 DAG，决定调用哪个 Specialist
- **Act:** 调用 Specialist Agent，传递最小必要上下文
- **Observe:** 接收 Specialist 结果，评估是否满足用户需求
- **Decide:** 满足→交付 / 不满足→补充或重试 / 不确定→反问用户

**关键约束:**
- **不直接生成 SQL 或回答** — 只做决策和路由
- 每次 Act 只调用一个 Specialist（借鉴 Manus 单步执行原则）
- 决策过程记录在 AgentState.task_dag 中，可审计

### 4.2 Schema Grounding Agent

**角色:** 将自然语言映射到实际数据库表/列/关系

**输入:** 用户 NL + Schema Knowledge Graph 引用

**处理流程:**
1. **L1 精确匹配:** 用户文本中出现的词直接匹配表名/列名/别名
2. **L2 语义向量:** 对无精确匹配的词做向量检索（Qdrant COMMENT 向量）
3. **L3 关系推断:** 从 Schema Graph 查找命中表之间的最短 JOIN 路径
4. **L4 上下文补充:** 补全可能相关的过滤列（如 status）

**输出:** `GroundingResult { tables, columns, join_paths, filters, confidence, ambiguities }`

**反问阈值:** confidence < 0.7 时，生成澄清问题反问用户

### 4.3 SQL Specialist Agent

**角色:** 基于已 Grounding 的精准 Schema 上下文生成 GBase SQL

**输入:** GroundingResult + 完整 DDL（仅命中表）+ Few-shot 示例（Schema 感知筛选）

**约束:**
- 只能使用 GroundingResult 中已确认的表和列
- 引用不存在的表/列 → 自纠错循环（最多 3 次）

### 4.4 SQL Verifier Agent

**角色:** 三层验证 — 语法 / 方言合规 / Schema 交叉验证

**验证层次:**
1. **语法层:** sqlglot 解析（dialect=mysql）
2. **方言层:** 不支持特性检测、DISTRIBUTED BY/REPLICATED 互斥验证
3. **Schema 层:** 表/列存在性验证（错误级，非警告），JOIN 列对应检查

**输出:** `{ passed: bool, errors: list[str] }`

### 4.5 SQL Executor Agent

**角色:** 沙箱中安全执行 SQL

**安全防护:**
- 只读强制（AST + 字符串双重检查）
- 超时控制（30s + 5s 缓冲）
- 行数限制（1000 行）
- 单语句强制

### 4.6 Knowledge Specialist Agent

**角色:** GBase 领域知识问答（RAG）

**检索策略:**
- 精确路径（ripgrep）: 错误码、SQL 关键字、参数查询
- 语义路径（Qdrant）: 自然语言问题
- RRF 融合（k=60）

### 4.7 General Specialist Agent

**角色:** 通用对话、元问题（如"你能做什么"）、非 SQL/非知识类问题

## 5. AgentState 设计（上下文隔离）

```python
from typing import TypedDict, Annotated, Literal
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # ── 消息历史（跨 Agent 共享，只增不减） ──
    messages: Annotated[list, add_messages]

    # ── Orchestrator 专属 ──
    intent: Literal["sql", "qa", "general", "clarify"]
    task_dag: list[dict]        # 子任务 DAG
    current_task: str           # 当前执行步骤

    # ── Schema Grounding 专属 ──
    grounding: dict | None      # GroundingResult
    needs_clarification: str | None
    grounding_retry_count: int

    # ── SQL Specialist 专属 ──
    generated_sql: str | None
    sql_retry_count: int

    # ── SQL Verifier 专属 ──
    validation_errors: list[str]
    validation_passed: bool

    # ── SQL Executor 专属 ──
    query_result: dict | None
    execution_error: str | None

    # ── Knowledge Specialist 专属 ──
    retrieved_docs: list[dict]
    knowledge_sources: list[str]

    # ── 输出 ──
    final_response: str | None
    confidence_score: int       # 1-3 (借鉴 Hermes)
    assumptions: list[str]      # 生成假设说明

    # ── 元数据 ──
    conversation_id: str
    db_connection_id: str | None
    model: str
```

**三条铁律防止上下文混乱:**

1. **字段所有权** — 每个 Agent 只写入自己的字段。TypedDict + Pydantic 校验在运行时拦截越界写入
2. **状态不可变追加** — messages 使用 add_messages reducer，只追加不覆盖
3. **敏感字段单次写入** — generated_sql、query_result 等关键字段一次写入后不可修改（Checkpoint 对比）

## 6. LangGraph 图结构

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver


def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    # 注册节点
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("schema_grounding", schema_grounding_node)
    builder.add_node("sql_specialist", sql_specialist_node)
    builder.add_node("sql_verifier", sql_verifier_node)
    builder.add_node("sql_executor", sql_executor_node)
    builder.add_node("knowledge_specialist", knowledge_specialist_node)
    builder.add_node("general_specialist", general_specialist_node)
    builder.add_node("response_formatter", response_formatter_node)

    # 入口 → Orchestrator
    builder.add_edge(START, "orchestrator")

    # Orchestrator 条件路由
    builder.add_conditional_edges("orchestrator", route_orchestrator, {
        "schema_grounding": "schema_grounding",
        "knowledge_specialist": "knowledge_specialist",
        "general_specialist": "general_specialist",
        "response_formatter": "response_formatter",
        "end": END,
    })

    # Schema Grounding → SQL Specialist
    builder.add_edge("schema_grounding", "sql_specialist")

    # SQL Specialist → SQL Verifier
    builder.add_edge("sql_specialist", "sql_verifier")

    # SQL Verifier 条件路由
    builder.add_conditional_edges("sql_verifier", route_verifier, {
        "sql_executor": "sql_executor",
        "sql_specialist": "sql_specialist",      # 自纠错
        "response_formatter": "response_formatter",  # 重试耗尽
    })

    # SQL Executor → Response
    builder.add_edge("sql_executor", "response_formatter")

    # Knowledge/General → Response
    builder.add_edge("knowledge_specialist", "response_formatter")
    builder.add_edge("general_specialist", "response_formatter")

    # Response → END
    builder.add_edge("response_formatter", END)

    return builder.compile(checkpointer=MemorySaver())
```

**路由函数:**

```python
def route_orchestrator(state: AgentState) -> str:
    intent = state.get("intent", "general")
    if intent == "sql":
        return "schema_grounding"
    elif intent == "qa":
        return "knowledge_specialist"
    elif intent == "general":
        return "general_specialist"
    elif intent == "clarify":
        return "response_formatter"  # 反问用户
    return "end"


def route_verifier(state: AgentState) -> str:
    if state.get("validation_passed"):
        return "sql_executor"
    retry = state.get("sql_retry_count", 0)
    if retry < 3:
        state["sql_retry_count"] = retry + 1
        return "sql_specialist"  # 自纠错
    return "response_formatter"  # 重试耗尽，返回带错误的响应
```

## 7. Schema Knowledge Graph（语义知识图谱）

### 7.1 构建流程（连接建立时执行一次）

```
GBase 数据库
    │
    ▼
fetch_schema() — SHOW TABLES + DESCRIBE + SHOW CREATE TABLE
    │
    ▼
DDL 解析器 (sqlglot + regex fallback)
    │
    ├─→ 提取: 表名、列名、类型、COMMENT、DISTRIBUTED BY
    ├─→ 推断: 主键（显式 PRIMARY KEY 或命名约定 *_id）
    ├─→ 推断: 外键关系（命名约定 *_no → customer.customer_no）
    ├─→ 推断: 列角色（MEASURE/TIME_DIMENSION/PRIMARY_KEY/ENUM）
    └─→ 生成: 中文别名/同义词（LLM 辅助，从 COMMENT + 表名 + 列名）
    │
    ▼
Schema Graph（JSON 持久化 + Qdrant 向量索引）
```

### 7.2 Schema Graph 数据结构

```yaml
tables:
  order_main:
    label: "订单主表"
    aliases: [订单, 订单表, order, 主订单]
    distribution: "DISTRIBUTED BY('order_id')"
    columns:
      order_id:
        type: BIGINT
        role: PRIMARY_KEY
        label: "订单ID"
        aliases: [订单号, 订单编号, order id]
      order_amount:
        type: DECIMAL(18,2)
        role: MEASURE
        label: "订单金额(元)"
        aliases: [金额, 订单额, 销售额, 交易额]
        unit: "元"
      order_time:
        type: DATETIME
        role: TIME_DIMENSION
        label: "下单时间"
        aliases: [订单时间, 创建时间, 交易时间]
      status:
        type: TINYINT
        role: ENUM
        label: "订单状态"
        values: {1: "待支付", 2: "已支付", 3: "已取消"}
    relationships:
      - target: customer
        via: customer_no → customer.customer_no
        type: MANY_TO_ONE
        confidence: 0.9
      - target: product
        via: product_code → product.product_code
        type: MANY_TO_ONE
        confidence: 0.85

indexes:
  exact_match:  { "订单": "order_main", "销售额": "order_main.order_amount", ... }
  vector:       Qdrant collection "schema_semantic" (COMMENT 嵌入)
  keyword:      倒排索引 (全文检索表名/列名/别名)
```

### 7.3 多策略检索流程

```
用户输入: "查询上个月销售额最高的前5个产品"

L1 精确匹配:
  "销售额" → order_main.order_amount (别名命中, score=1.0)
  "产品"   → product.name (标签命中, score=1.0)

L2 语义向量:
  "上个月" → order_main.order_time (cos=0.91)

L3 关系推断:
  命中表: [order_main, product]
  JOIN 路径: order_main.product_code = product.product_code (2步, confidence=0.85)

L4 上下文补充:
  order_main.status → 建议过滤条件: "是否排除已取消订单?"

RRF 融合排序 (k=60):
  → 输出: GroundingResult { confidence: 0.92 }
```

## 8. Feedback Learner（反馈持续学习）

### 8.1 学习闭环

```
用户行为
    │
    ├─→ 接受 SQL → 提取 (NL, tables, columns, SQL) → 正例入库
    │        └─→ 更新 Schema Graph 别名权重 ↑
    │        └─→ 作为 Few-shot 示例注入未来查询
    │
    ├─→ 修改 SQL → diff 分析 → 提取 (错误映射, 正确映射)
    │        └─→ 补充缺失别名 → 更新 Schema Graph
    │        └─→ 修正错误关系推断
    │
    └─→ 拒绝 SQL → 标记低质量 Grounding → 触发 LLM 分析
             └─→ 标注根因 (表映射错误/列映射错误/关系错误)
             └─→ 降低对应映射的置信度权重
```

### 8.2 存储

- **正例库:** Qdrant collection `learned_examples`（自动积累，与手动 `sql_examples` 分开）
- **别名权重:** SQLite `semantic_aliases` 表（记录别名→列映射的使用次数和接受率）
- **关系置信度:** 随接受/拒绝动态调整

## 9. 连接状态监测（v1 成果整合）

v1 已实现的 `ConnectionHealthChecker` + SSE 实时推送保持不变，整合入 v2 架构：

- HealthChecker 继续作为独立后台服务运行
- SSE 端点 `/api/connections/status/stream` 保留
- 前端 Pinia Store 集中管理状态（`connStatusMap`）
- 新增：Schema Grounding Agent 在执行前检查目标连接状态，若断连则提示用户

## 10. AG-UI Gateway（标准化事件协议）

### 10.1 设计决策

AG-UI 是 2025-2026 年主流的 Agent-用户交互协议标准，规范化了 SSE 事件类型。当前 GBase 助手使用自定义 SSE 事件（`{type: "text"}`, `{type: "sql"}`），v2 升级为标准 AG-UI 事件类型。

**不引入 Node.js 中间层。** 标准 CopilotKit 架构需要 TypeScript Runtime 作为中间层，但 GBase 前端是 Vue 3（非 React），引入 Node.js 会增加不必要的部署复杂度。采用 **FastAPI 直出 AG-UI + Vue 轻量适配器** 方案：

```
┌─────────────────────────────────────────────────────────────────┐
│                     GBase Gateway (单 FastAPI 进程)               │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │            EventEncoder (Python, ~150行)                   │  │
│  │                                                           │  │
│  │  将 LangGraph Agent 输出编码为标准 AG-UI SSE 事件:           │  │
│  │                                                           │  │
│  │  Orchestrator 决策    → STATE_DELTA                        │  │
│  │  Schema Grounding 调用 → TOOL_CALL_START                   │  │
│  │  SQL 生成 (流式)      → TEXT_MESSAGE_CONTENT                │  │
│  │  SQL 验证通过         → TOOL_CALL_END                      │  │
│  │  SQL 执行结果         → TOOL_CALL_RESULT                   │  │
│  │  Grounding 结果       → STATE_DELTA                        │  │
│  │  任务完成             → RUN_FINISHED                       │  │
│  │  任务失败             → RUN_ERROR                          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  POST /api/chat/run          ← 发起对话 (RunAgentInput)          │
│  GET  /api/chat/stream       ← AG-UI SSE 事件流                  │
│  POST /api/chat/cancel       ← 用户中断                          │
│  /api/connections/*          ← REST (不变)                       │
│  /api/connections/status/stream ← SSE (不变)                     │
│  /api/health                 ← REST (不变)                       │
│  /api/mcp/*                  ← MCP 工具端点 (Phase 4+)           │
└─────────────────────────────────────────────────────────────────┘
         │ AG-UI SSE (标准格式)
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Vue 3 前端                                   │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │         AG-UI 客户端适配器 (~150行)                          │  │
│  │                                                           │  │
│  │  - 解析标准 AG-UI 事件类型 (替代自定义 SSE 解析器)            │  │
│  │  - 维护 Agent 状态机: idle → running → done → error        │  │
│  │  - 工具调用进度渲染 (显示 Schema Grounding 进行中)           │  │
│  │  - STATE_DELTA → Pinia Store 更新                          │  │
│  │  - 用户中断支持 (取消按钮)                                   │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 AG-UI 事件类型定义

| 事件 | 方向 | 说明 | 触发时机 |
|------|------|------|---------|
| `RUN_STARTED` | S→C | 任务开始 | Orchestrator 接收用户输入 |
| `TEXT_MESSAGE_CONTENT` | S→C | 流式文本 | SQL 生成过程、LLM 回复 |
| `TOOL_CALL_START` | S→C | 工具调用开始 | Schema Grounding / SQL Executor 被调用 |
| `TOOL_CALL_END` | S→C | 工具调用完成 | Specialist Agent 完成工作 |
| `TOOL_CALL_RESULT` | S→C | 工具执行结果 | SQL 执行结果返回 |
| `STATE_DELTA` | S→C | 状态变更 | Grounding 结果、验证结果、置信度更新 |
| `RUN_FINISHED` | S→C | 任务完成 | 最终响应生成完毕 |
| `RUN_ERROR` | S→C | 任务失败 | 重试耗尽或不可恢复错误 |

### 10.3 EventEncoder（Python 实现）

```python
# backend/app/gateway/ag_ui_encoder.py

import json
from enum import StrEnum
from dataclasses import dataclass, field


class EventType(StrEnum):
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    TOOL_CALL_END = "TOOL_CALL_END"
    STATE_DELTA = "STATE_DELTA"
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"


class EventEncoder:
    """将 LangGraph Agent 输出编码为 AG-UI 标准 SSE 事件"""

    @staticmethod
    def _encode(event_type: EventType, **kwargs) -> str:
        payload = {"type": event_type.value, **kwargs}
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def run_started(conversation_id: str) -> str:
        return EventEncoder._encode(EventType.RUN_STARTED,
                                    conversation_id=conversation_id)

    @staticmethod
    def text_delta(content: str) -> str:
        return EventEncoder._encode(EventType.TEXT_MESSAGE_CONTENT,
                                    delta=content)

    @staticmethod
    def tool_call_start(tool_name: str, args: dict | None = None) -> str:
        return EventEncoder._encode(EventType.TOOL_CALL_START,
                                    tool_name=tool_name, args=args or {})

    @staticmethod
    def tool_call_end(tool_name: str) -> str:
        return EventEncoder._encode(EventType.TOOL_CALL_END,
                                    tool_name=tool_name)

    @staticmethod
    def tool_call_result(tool_name: str, result: dict) -> str:
        return EventEncoder._encode(EventType.TOOL_CALL_RESULT,
                                    tool_name=tool_name, result=result)

    @staticmethod
    def state_delta(path: str, value: dict) -> str:
        return EventEncoder._encode(EventType.STATE_DELTA,
                                    path=path, value=value)

    @staticmethod
    def run_finished() -> str:
        return EventEncoder._encode(EventType.RUN_FINISHED)

    @staticmethod
    def run_error(message: str) -> str:
        return EventEncoder._encode(EventType.RUN_ERROR, message=message)
```

### 10.4 Agent 节点 → AG-UI 事件映射

| LangGraph 节点 | 输出事件顺序 |
|---------------|-------------|
| `orchestrator` | `RUN_STARTED` → 意图分类 → 路由决策 |
| `schema_grounding` | `TOOL_CALL_START(schema_grounding)` → (检索) → `TOOL_CALL_END(schema_grounding)` → `STATE_DELTA(/grounding, GroundingResult)` |
| `sql_specialist` | `TOOL_CALL_START(sql_generator)` → `TEXT_MESSAGE_CONTENT` (流式) → `TOOL_CALL_END(sql_generator)` |
| `sql_verifier` | `TOOL_CALL_START(sql_validator)` → `TOOL_CALL_END(sql_validator)` → `STATE_DELTA(/validation, {passed, errors})` |
| `sql_executor` | `TOOL_CALL_START(sql_executor)` → `TOOL_CALL_RESULT(sql_executor, {rows, time})` → `TOOL_CALL_END(sql_executor)` |
| `knowledge_specialist` | `TOOL_CALL_START(knowledge_retrieval)` → `TEXT_MESSAGE_CONTENT` → `TOOL_CALL_END(knowledge_retrieval)` |
| `response_formatter` | `STATE_DELTA(/output, {confidence, assumptions})` → `RUN_FINISHED` |

### 10.5 Vue 3 AG-UI 客户端适配器

```typescript
// frontend/src/composables/useAGUIClient.ts

import { reactive } from 'vue'

type AgentStatus = 'idle' | 'running' | 'done' | 'error'

interface ToolState {
  name: string
  status: 'pending' | 'running' | 'done' | 'error'
  result?: unknown
}

interface AGUIClientState {
  status: AgentStatus
  currentTool: ToolState | null
  toolHistory: ToolState[]
  stateDeltas: Record<string, unknown>
  error: string | null
  confidence: number | null
  assumptions: string[]
}

export function useAGUIClient() {
  const state = reactive<AGUIClientState>({
    status: 'idle',
    currentTool: null,
    toolHistory: [],
    stateDeltas: {},
    error: null,
    confidence: null,
    assumptions: [],
  })

  let abortController: AbortController | null = null

  async function runAgent(input: string, dbConnectionId?: string) {
    state.status = 'running'
    state.toolHistory = []
    state.error = null

    abortController = new AbortController()

    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ message: input, db_connection_id: dbConnectionId }),
      signal: abortController.signal,
    })

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const json = line.slice(6).trim()
        if (!json) continue
        try {
          const event = JSON.parse(json)
          handleEvent(event)
        } catch { /* ignore */ }
      }
    }
  }

  function handleEvent(event: any) {
    switch (event.type) {
      case 'RUN_STARTED':
        state.status = 'running'
        break
      case 'TOOL_CALL_START':
        state.currentTool = { name: event.tool_name, status: 'running' }
        break
      case 'TOOL_CALL_END':
        if (state.currentTool) {
          state.currentTool.status = 'done'
          state.toolHistory.push({ ...state.currentTool })
          state.currentTool = null
        }
        break
      case 'TOOL_CALL_RESULT':
        if (state.currentTool) {
          state.currentTool.result = event.result
        }
        break
      case 'STATE_DELTA':
        state.stateDeltas[event.path] = event.value
        if (event.path === '/output') {
          state.confidence = event.value?.confidence ?? null
          state.assumptions = event.value?.assumptions ?? []
        }
        break
      case 'RUN_FINISHED':
        state.status = 'done'
        break
      case 'RUN_ERROR':
        state.status = 'error'
        state.error = event.message
        break
    }
  }

  function cancel() {
    abortController?.abort()
    fetch('/api/chat/cancel', { method: 'POST' }).catch(() => {})
  }

  return { state, runAgent, cancel }
}
```

### 10.6 用户可见的改进

**v1 (当前):**
```
用户看到: 文本一点点出来... → SQL出现 → 结果出现
          (不知道系统做了什么)
```

**v2 (AG-UI):**
```
用户看到:
  🔍 正在理解您的查询...
  📊 已定位表: order_main (订单主表), product (产品表)  [TOOL_CALL_END]
  📝 正在生成 SQL...                                     [TOOL_CALL_START]
  SELECT ... FROM order_main JOIN product ...            [TEXT_MESSAGE_CONTENT]
  ✅ SQL 验证通过                                        [TOOL_CALL_END]
  ⚡ 执行中...                                           [TOOL_CALL_START]
  📋 返回 5 行结果 (0.12s)                               [TOOL_CALL_RESULT]
  置信度: ★★★ (高)                                       [STATE_DELTA]
  假设: "销售额" 映射为 order_main.order_amount            [assumptions]
```

---

## 11. 技术栈

| 层级 | 技术 |
|------|------|
| 编排框架 | LangGraph (StateGraph + ConditionalEdge + MemorySaver) |
| LLM 后端 | LiteLLM (DeepSeek Chat + 回退 Qwen/GPT-4o) |
| Gateway 协议 | **AG-UI** (标准化 SSE 事件) |
| 向量数据库 | Qdrant (schemas, sql_examples, knowledge, error_codes, learned_examples) |
| API 框架 | FastAPI (SSE for streaming) |
| 前端 | Vue 3 + Pinia + NaiveUI + **AG-UI Client Adapter** |
| 持久化 | SQLite (conversations, feedback, semantic_aliases) + Qdrant |
| GBase 连接 | gbase-connector-python (native driver, asyncio.to_thread) |
| SQL 解析 | sqlglot (dialect=mysql, closest to GBase 8a) |
| 全文搜索 | ripgrep (precise path in hybrid RAG) |

## 12. 实施策略

分四个 Phase 渐进实施，每个 Phase 独立可交付：

| Phase | 内容 | 依赖 |
|-------|------|------|
| **Phase 1: 基础设施+AG-UI** | LangGraph 集成、AgentState、Orchestrator 路由、**EventEncoder**、**Vue AG-UI 客户端适配器**、项目目录重构 | 无 |
| **Phase 2: Schema Knowledge Graph** | DDL 解析器增强、语义标注、Schema Graph 构建和存储、多策略检索 | Phase 1 |
| **Phase 3: Specialist Agent 重构** | Schema Grounding、SQL/Knowledge/General Specialist 接入 LangGraph、AG-UI 事件映射 | Phase 2 |
| **Phase 4: 持续学习与优化** | Feedback Learner 闭环、别名自动学习、Few-shot 自动积累、MCP 工具端点 | Phase 3 |

## 13. 风险与缓解

| 风险 | 缓解 |
|------|------|
| LangGraph 增加延迟 | Specialist 调用共享 LiteLLM 实例，避免额外网络开销 |
| Schema Graph 构建不完整 | LLM 辅助推断 + 用户手动补充 COMMENT 的简单入口 |
| ReAct 循环失控 | 硬限制：最多 5 轮 Think-Act 循环；3 次 SQL 自纠错 |
| 上下文窗口超限 | Specialist 只接收最小必要上下文（非完整历史）；文件系统存大对象 |
| 级联问题（Anthropic 经验） | 每层独立重试上限 + 循环检测（相同状态 3 次→升级） |
