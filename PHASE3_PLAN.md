# GBase 8a Assistant — Phase 2.5 检查报告 & Phase 3 升级规划

> 生成时间：2026-04-29
> 基准版本：Phase 2.5 收尾完成态

---

## 一、Phase 2.5 收尾检查结论

### ✅ 已完成项（全部通过）

| 检查项 | 状态 | 详情 |
|--------|------|------|
| 后端测试 | ✅ 48 passed | `test_api.py`(10) + `test_sql_chain.py`(9) + `test_sql_validator.py`(29) |
| 后端 Lint | ✅ 通过 | ruff check + ruff format 全部通过（42 files） |
| 前端 Lint | ✅ 通过 | oxlint + eslint 0 error/warning |
| 前端 Build | ✅ 通过 | 产物 1.5MB（gzip 后 438KB） |
| Alembic 迁移 | ✅ 正常 | 1 个迁移脚本，`alembic_version` 单条记录无脏数据 |
| FAQ 知识库 | ✅ 38 条 | 覆盖 syntax、features、performance、operations |
| SQL 示例 | ✅ 30 条 | 含 DBNODE、DISTRIBUTED BY、REPLICATED、ENCODING 等特有语法 |
| 部署配置 | ✅ 已补齐 | Dockerfile.backend/frontend、docker-compose.yml、nginx.conf |
| 模型配置 | ✅ 已校准 | `deepseek/deepseek-chat`，评估结论已归档 |
| 安全清理 | ✅ 完成 | `.env.example` 中所有 API Key 已替换为 `sk-xxx` |

### ⚠️ 遗留问题与注意事项

| # | 问题 | 优先级 | 建议处理时机 |
|---|------|--------|-------------|
| 1 | **Git 未提交**：45 modified + 10 untracked（含 Phase 3 预埋代码） | P0 | Phase 3 Sprint 1 开始前统一 commit |
| 2 | **前端组件测试缺失**：Vitest/Vue Test Utils 未配置 | P2 | Sprint 3 或延后 |
| 3 | `error_codes.json` 不存在 | P1 | Sprint 2 |
| 4 | `dependencies.py` 缺少 `get_schema_retriever()` 的 Qdrant 绑定 | P0 | Sprint 1 |
| 5 | `retrievers.py` 中 Qdrant filter 使用裸 dict，建议改用 `models.Filter` | P1 | Sprint 1 |
| 6 | `ingest.py` 缺少 `ingest_schemas()` 函数（Schema DDL 向量化入库） | P0 | Sprint 1 |

### 🔍 Phase 2.5 预埋的 Phase 3 代码盘点

以下模块已在 Phase 2.5 提前编写但未实际启用，Phase 3 可直接复用：

- `backend/app/vector/client.py` — Qdrant async client + collection 生命周期
- `backend/app/vector/embedder.py` — Embedder 工厂（local bge-m3 / LiteLLM 远程）
- `backend/app/vector/embedders/local.py` — sentence-transformers 本地嵌入
- `backend/app/vector/embedders/litellm.py` — LiteLLM 远程嵌入
- `backend/app/vector/retrievers.py` — QdrantSchema/Example/Knowledge Retriever 实现
- `backend/app/vector/ingest.py` — FAQ / SQL 示例 / 错误码 向量化入库
- `backend/app/models/conversation_summary.py` — 对话摘要 ORM（Phase 4 长期记忆）
- `backend/app/models/user_pattern.py` — 用户查询模式 ORM（Phase 4 长期记忆）
- `models.yaml` — 已包含 `embedding` 和 `collections` 配置段
- `config.py` — 已包含 `qdrant_url`、`qdrant_api_key`
- `main.py` — lifespan 已集成 Qdrant 初始化 + 知识库同步（带降级）
- `pyproject.toml` — 已依赖 `qdrant-client>=1.17.1`、`sentence-transformers>=5.4.1`
- `deploy/docker-compose.yml` — 已包含 `qdrant` 服务 + healthcheck

---

## 二、Phase 3 总体目标

**主题：智能增强 — 向量检索落地 + RAG 升级 + 工具扩展**

从"文件驱动 + 全量注入"升级为"向量驱动 + 语义检索"，解决以下痛点：

1. **Schema 过大时 token 超限** → Schema Linking 向量化，只注入相关表
2. **Few-shot 示例固定不变** → 动态检索最相似示例
3. **FAQ 关键词匹配准确率天花板** → RAG 语义检索
4. **无错误码自助查询** → 错误码知识库 + 查询工具
5. **Schema 管理只有文本框** → 可视化 Schema 浏览器

---

## 三、技术栈升级清单

### 新增依赖

| 层级 | 组件 | 说明 |
|------|------|------|
| 向量数据库 | Qdrant | Docker 部署，本地开发 `http://localhost:6333` |
| Embedding | bge-m3 (本地) | 默认，首次下载约 2.3GB，dim=1024 |
| Embedding | OpenAI text-embedding-3-small (远程) | models.yaml 可切换，dim=1536 |
| 前端图表 | 待定（vchart / echarts） | Schema 关系图可视化（可选） |

### 架构变更点

```
Phase 2.5 (当前)
  FastAPI → FileExampleRetriever / FileKnowledgeRetriever / 全量 Schema DDL

Phase 3 (目标)
  FastAPI → QdrantExampleRetriever / QdrantKnowledgeRetriever / QdrantSchemaRetriever
           ↘ 降级回退：Qdrant 不可用时自动回退到文件/DB 全量模式
```

**关键原则**：所有变更只改 `dependencies.py` 的绑定逻辑，不改 chain 层调用代码。

---

## 四、任务拆分与排期（4 个 Sprint）

### Sprint 1：向量检索核心落地（Week 6）

**目标**：Qdrant 检索链路完全可用，Schema/Example/Knowledge 均支持向量检索 + 降级回退。

| # | 任务 | 优先级 | 工作量 | 交付物 |
|---|------|--------|--------|--------|
| 1.1 | Git commit Phase 2.5 全部改动 | P0 | 0.5h | 干净 baseline |
| 1.2 | 修复 `retrievers.py` Qdrant filter 语法（改用 `models.Filter`） | P1 | 2h | 检索代码健壮性提升 |
| 1.3 | 实现 `ingest_schemas()`：将 `schema_ddl` 解析为表级向量点入库 | P0 | 4h | `ingest.py` 新增函数 |
| 1.4 | `dependencies.py` 实现 `get_schema_retriever()`：优先 Qdrant → 回退全量 DB | P0 | 3h | Schema 检索切换完成 |
| 1.5 | `dependencies.py` 完成 Example/Knowledge Retriever 的 Qdrant 绑定 + 降级 | P0 | 3h | 知识检索切换完成 |
| 1.6 | 连接保存/更新时自动触发 schema 向量化入库（后台异步） | P1 | 3h | 自动化入库逻辑 |
| 1.7 | 验证 Docker Compose 全链路启动（backend + frontend + qdrant + nginx） | P1 | 4h | `docker compose up` 一次成功 |
| 1.8 | 补充 `dependencies.py` 和 `retrievers.py` 的单元测试 | P1 | 3h | 测试通过 |

**Sprint 1 验收标准**：
- `docker compose up` 后，Qdrant 健康，后端能正常启动
- 创建/更新数据库连接后，schema 能自动入库 Qdrant
- 聊天时，Schema 检索走 Qdrant，Qdrant 宕机时自动回退到全量 DDL（无感知降级）
- 全部测试通过

---

### Sprint 2：RAG 增强 + 错误码工具（Week 7）

**目标**：知识库全面 RAG 化，错误码查询工具可用。

| # | 任务 | 优先级 | 工作量 | 交付物 |
|---|------|--------|--------|--------|
| 2.1 | 创建 `knowledge/docs/error_codes.json`（50+ 条 GBase 8a 错误码） | P0 | 4h | 错误码知识库 |
| 2.2 | `ingest.py` 接入 `ingest_error_codes()` 并加入 `sync_all_to_qdrant()` | P0 | 2h | 错误码向量化 |
| 2.3 | 后端 API：`POST /api/tools/error-code`（支持 code / keyword 查询） | P0 | 3h | 错误码查询接口 |
| 2.4 | 后端 API：`POST /api/admin/reindex`（手动触发全量知识库同步） | P1 | 2h | 管理接口 |
| 2.5 | 扩展 GBase 8a 运维文档（性能调优、参数配置、集群管理）并分块入库 | P1 | 6h | `knowledge/docs/ops_*.json` |
| 2.6 | `qa_chain.py` 接入 RAG：优先 Qdrant 检索，未命中时回退关键词匹配 | P0 | 3h | RAG 问答链路 |
| 2.7 | 前端：错误码查询组件（输入错误码或描述，展示解决方案） | P0 | 4h | `ErrorCodeTool.vue` |
| 2.8 | 前端：设置页增强（显示向量库连接状态、手动 Reindex 按钮） | P1 | 3h | SettingsView 升级 |

**Sprint 2 验收标准**：
- 输入 `"ERROR 1146"` 能返回对应错误描述和解决方案
- 知识问答准确率达到 Phase 2 的 120%（以 20 条标准问题人工评测）
- Settings 页面可查看 Qdrant 状态和手动触发 Reindex

---

### Sprint 3：Schema 浏览器 + 前端增强（Week 8）

**目标**：Schema 管理从文本框升级为可视化浏览器。

| # | 任务 | 优先级 | 工作量 | 交付物 |
|---|------|--------|--------|--------|
| 3.1 | 后端 API：`GET /api/connections/{id}/schema/tables`（解析 DDL 返回结构化表列表） | P0 | 3h | Schema 解析接口 |
| 3.2 | 后端 API：`GET /api/connections/{id}/schema/tables/{name}`（单表详情） | P0 | 2h | 表详情接口 |
| 3.3 | 前端：Schema 浏览器页面/组件（表列表 → 表详情 → DDL 展示） | P0 | 6h | `SchemaBrowser.vue` |
| 3.4 | 前端：Settings 页面嵌入模型配置可视化（local/litellm 切换、设备选择） | P1 | 3h | SettingsView 增强 |
| 3.5 | 前端：聊天界面支持引用来源展示（RAG 检索到的知识来源） | P1 | 3h | MessageBubble 增强 |
| 3.6 | 配置前端 Vitest + Vue Test Utils，补齐 3-5 个核心组件测试 | P2 | 4h | `frontend/src/components/__tests__/` |
| 3.7 | `conversation_summary.py` 轻量化集成：对话结束时自动生成摘要 | P2 | 4h | 摘要生成逻辑 |

**Sprint 3 验收标准**：
- Schema 浏览器能正确解析并展示 GBase 8a DDL（表名、列、类型、注释）
- 知识问答的回答下方可展开显示引用来源
- 前端 Vitest 运行通过至少 3 个测试

---

### Sprint 4：稳定性 + 评估 + CI/CD（Week 9）

**目标**：全链路稳定，可观测，输出 LangGraph 评估结论。

| # | 任务 | 优先级 | 工作量 | 交付物 |
|---|------|--------|--------|--------|
| 4.1 | LangGraph 评估：当前链路是否需要引入？输出决策文档 | P0 | 4h | `docs/decisions/phase3-langgraph.md` |
| 4.2 | 全链路 E2E 测试：真实 LLM + Qdrant，10 个标准用例 | P0 | 4h | E2E 测试报告 |
| 4.3 | 可观测性：向量检索命中率指标、Embedding 延迟 histogram | P1 | 3h | `/metrics` Prometheus 格式 |
| 4.4 | 性能基准测试：Schema 全量注入 vs 向量检索的延迟/准确率对比 | P1 | 3h | 基准测试报告 |
| 4.5 | GitHub Actions CI：lint → test → build → docker build | P1 | 4h | `.github/workflows/ci.yml` |
| 4.6 | SQL 反馈闭环：用户反馈自动丰富 Few-shot 库（写入 knowledge + 触发 reindex） | P2 | 4h | 自动 enrich 逻辑 |
| 4.7 | 文档更新：`ARCHITECTURE.md` + `AGENTS.md` + `README.md` 同步 Phase 3 变更 | P1 | 2h | 文档同步 |

**Sprint 4 验收标准**：
- CI 流水线 green（GitHub Actions 全部通过）
- E2E 测试 10/10 通过
- LangGraph 决策文档有明确结论（引入 / 不引入 / 延后）
- Schema 全量 vs 向量检索有数据支撑的性能对比

---

## 五、关键决策点与风险

### 决策 1：Embedding 方案选择

| 方案 | 优点 | 缺点 | 建议 |
|------|------|------|------|
| **本地 bge-m3**（默认） | 零 API 费用、离线可用、数据不出境 | 首次下载 2.3GB、CPU 推理慢（~100ms/条） | **默认方案**，适合内部部署 |
| 远程 OpenAI / 阿里云 | 速度快、无需本地模型文件 | 有费用、数据出境 | models.yaml 中配置为备选 |

**结论**：保持 `models.yaml` 当前设计，`provider: local` 为默认，可随时切换。

### 决策 2：LangGraph 是否引入

| 条件 | Phase 3 是否满足 |
|------|-----------------|
| Agent 间复杂状态传递和条件跳转 | ❌ 当前链路仍为线性：intent → chain → validate → output |
| checkpoint/resume 能力 | ❌ 无长时运行任务 |
| human-in-the-loop | ❌ 当前无审批节点 |

**预判**：Phase 3 **不引入 LangGraph**。当前函数链签名已兼容 LangGraph node 包装，若 Phase 4 出现上述条件再评估。

### 决策 3：Schema 浏览器解析策略

GBase 8a DDL 复杂度高，解析方案：
- **方案 A**：sqlglot AST 解析（已引入，推荐）
- **方案 B**：正则提取（快速但不稳健）
- **方案 C**：后端缓存已解析的 JSON 结构

**结论**：使用 **sqlglot 解析 + 缓存结构化结果**，既准确又避免重复解析。

### 风险项

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| bge-m3 首次下载 2.3GB，Docker 镜像膨胀 | 构建慢、镜像大 | Dockerfile 使用多阶段构建，模型挂载为 volume |
| Qdrant 本地开发需额外启动 Docker | 开发体验下降 | `docker compose up qdrant` 单独启动；main.py 已做降级 |
| Schema 向量化后检索准确率不达预期 | SQL 生成质量下降 | 保留全量回退开关；人工评测 20 条标准用例验证 |
| 前端 Vitest 配置与 Vite 6 兼容性 | 测试无法运行 | 使用 `vitest` + `@vue/test-utils@2.x`，先行验证 |

---

## 六、升级后架构图

```
                    Nginx (反向代理)
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     Vue SPA      FastAPI Backend    /metrics
          │              │
          │    ┌─────────┼─────────┐
          │    │         │         │
          │  SQLite   Qdrant   LiteLLM
          │  (app DB) (向量)    (多模型)
          │              │
          │    ┌─────────┴─────────┐
          │    │                   │
          │  schemas          sql_examples
          │  knowledge        error_codes
          │
     Schema Browser  ErrorCode Tool  Chat (RAG增强)
```

---

## 七、立即行动项（开始 Sprint 1 前）

1. [ ] **Git commit Phase 2.5**：`git add . && git commit -m "phase 2.5: finalize — alembic, deploy, faq, tests"`
2. [ ] **确认 Embedding 设备**：M1/M2 Mac 用户建议 `device: mps`，加速推理
3. [ ] **启动 Qdrant 开发环境**：`cd deploy && docker compose up -d qdrant`
4. [ ] **验证 Qdrant 可达**：`curl http://localhost:6333/healthz`

---

*本规划基于 Phase 2.5 实际代码状态编制，所有任务已考虑已有预埋代码的复用。如需调整优先级或范围，可逐 Sprint 细化。*
