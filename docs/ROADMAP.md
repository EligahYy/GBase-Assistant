# GBase 8a Assistant — Phase 3 ROADMAP

> 最近更新:2026-05-06
> 当前里程碑:Phase 3 Sprint 1 ✅ 完成,Sprint 2 进行中
> 项目阶段:Demo / 评测阶段(CI、可观测、LangGraph 评估降权)

---

## 一、当前状态快照

### Phase 3 完成度

| Sprint | 状态 | 说明 |
|---|---|---|
| Sprint 1 — 向量检索核心 | ✅ 完成 | Qdrant client、Embedder 工厂、Schema/Example/Knowledge retriever、自动降级、连接保存自动入库 |
| Sprint 2 — RAG + 错误码工具 | 🚧 进行中 | 当前缺 `error_codes.json` 数据、错误码 API、Reindex 接口、运维文档分块 |
| Sprint 3 — Schema 浏览器 + 演示打磨 | ⏸ 待启动 | 节选 C.1/C.2,Vitest 配置降到 P2 |
| Sprint 4 — 稳定性 / CI / 可观测 | ⏸ Demo 阶段降权 | 仅保留 E2E 10 用例 + 错误码 RAG 评测,其余延到上线前 |

### 已完成的 P0 清理(2026-05-06)
- 删除 `_verify_protocol`、`set_qdrant_manager`、`set_embedder`、`addAssistantMessage` 等死代码
- 修正 `SettingsView.vue` fallback 模型清单与 `models.yaml` 对齐
- ORM 模型 `ConversationSummary` / `UserPattern` 保留(Phase 4 长期记忆复用)

---

## 二、Phase 3 Sprint 任务清单

### Sprint 1 ✅ 已完成

- [x] `retrievers.py` Qdrant filter 改用 `models.Filter`
- [x] `ingest.py` 实现 `ingest_schemas()` Schema DDL 入库
- [x] `dependencies.py` 实现三个 retriever 的 Qdrant 绑定 + 降级回退
- [x] 连接保存/更新触发后台 schema 向量化
- [x] `_FakeEmbedder` 测试隔离
- [x] `test_dependencies.py` 9 个降级场景测试通过
- [x] Alembic 迁移 `7ab819dfa573_add_conversation_summary_and_user_.py`

### Sprint 2 🚧 RAG 增强 + 错误码工具

**目标**:演示"输错误码 → 准确返回原因/解决方案"+"知识问答从关键词匹配升级为语义检索"

| # | 任务 | 优先级 | 工作量 | 交付物 |
|---|---|---|---|---|
| 2.1 | 准备 `knowledge/docs/error_codes.json`(50+ 条 GBase 8a 错误码) | P0 | 4h | 错误码数据 |
| 2.2 | 验证 `ingest_error_codes()` 已接入 `sync_all_to_qdrant`(代码已写) | P0 | 0.5h | 启动日志确认 |
| 2.3 | 新建 `app/api/tools.py` — `POST /api/tools/error-code`,支持 code/keyword 查询 | P0 | 3h | 错误码查询接口 |
| 2.4 | 新建 `app/api/admin.py` — `POST /api/admin/reindex` 强制全量重建 | P1 | 2h | 管理接口 |
| 2.5 | 扩展运维文档(性能、参数、集群)分块入库 `knowledge/docs/ops_*.json` | P1 | 6h | 运维知识库 |
| 2.6 | `qa_chain.py` 接入 RAG(已通过 `KnowledgeRetriever` 接收 chunks,验证降级路径命中率) | P0 | 3h | RAG 问答闭环 |
| 2.7 | 前端 `ErrorCodeTool.vue` 组件 + `frontend/src/api/tools.ts` 封装 | P0 | 4h | 错误码 UI |
| 2.8 | `SettingsView.vue` 增加"向量检索状态"卡片 + Reindex 按钮 | P1 | 3h | 状态面板 |
| 2.9 | `MessageBubble.vue` 增加 sources 折叠区(qa_chain 已 stream sources) | P1 | 2h | 引用展示 |
| 2.10 | `health.py` `/health` 增加 `qdrant: connected/disconnected/degraded` | P1 | 1h | 健康端点扩展 |

**Sprint 2 验收**:
- `curl POST /api/tools/error-code -d '{"query":"1146"}'` 返回 GBase 8a 表不存在错误说明
- 知识问答 20 条标准用例,RAG 模式准确率 >= 关键词模式 + 20%
- Settings 页能看到 Qdrant 状态、点 Reindex 后状态条更新

### Sprint 3 ⏸ Schema 浏览器最小可用

**目标**:Schema 管理从文本框升级为可视化列表(节选 PHASE3_PLAN 的 3.1/3.5/3.7,降低范围)

| # | 任务 | 优先级 | 工作量 | 交付物 |
|---|---|---|---|---|
| 3.1 | 后端 `GET /api/connections/{id}/schema/tables` 复用 `_parse_ddl_to_schemas()` | P0 | 3h | Schema 解析接口 |
| 3.2 | 前端在 `SettingsView` 嵌入 Schema 列表(暂不做单独路由) | P0 | 4h | 浏览器 UI |
| 3.3 | `ConversationSummary` 接入:对话 N 轮后异步生成摘要,载入对话时优先使用 | P2 | 4h | 长期记忆 v0 |
| 3.4 | 准备 `docs/demo-cases.md` 10–15 条标准用例(覆盖 SQL/错误码/QA) | P0 | 3h | 演示脚本 |

**Sprint 3 验收**:Schema 列表能正确展示;`docs/demo-cases.md` 用例全部跑通

### Sprint 4 ⏸ 上线前必做(Demo 阶段降权)

下列任务延到上线前再执行,但要在 ROADMAP 显式标注避免遗忘:

- [ ] GitHub Actions CI:`lint → test → build → docker build`
- [ ] `/metrics` Prometheus 端点(向量检索命中率、Embedding 延迟)
- [ ] LangGraph 评估文档(预判:不引入,但需正式归档)
- [ ] 性能基准:Schema 全量注入 vs 向量检索的延迟/准确率对比
- [ ] SQL 反馈闭环:用户反馈自动 enrich Few-shot 库
- [ ] Vitest + Vue Test Utils 配置 + 3-5 个核心组件测试

**Sprint 4 中本期保留的 2 项**:
- E2E 10 用例(并入 Sprint 3 的 demo-cases)
- 错误码 + RAG 准确率人工评测(并入 Sprint 2 验收)

---

## 三、阶段 A:净化(本期同步推进)

PHASE3_PLAN 中没有的额外净化项,与 Sprint 2 并行处理:

### A.1 状态收口(2026-05-06 进行中)
- [x] `.gitignore` 整体忽略 `.claude/`(避免 worktrees 被跟踪)
- [x] 恢复 `PHASE3_PLAN.md` → 本文件 `docs/ROADMAP.md`
- [x] `design-proposal.md` 移至 `docs/design/redesign-proposal.md`
- [ ] 更新 `AGENTS.md` 当前阶段段落(进行中)
- [ ] 同步 `ARCHITECTURE.md` Phase 3 章节状态

### A.2 P1 重构(Sprint 2 完成前完成)
- [ ] `dependencies.py` 三个 fallback wrapper 类合并为泛型 `FallbackRetriever[T]`
- [ ] Embedding 维度从 `models.yaml` 显式读取(去掉 `litellm.py` 的硬编码维度判断)
- [ ] `main.py` lifespan 中 `sync_all_to_qdrant` 改为 `asyncio.create_task` 后台执行 + `SKIP_VECTOR_SYNC` env 开关

### A.3 配置一致性
- [ ] `models.yaml` provider 默认值与 ARCHITECTURE.md 描述统一(local vs litellm 二选一)
- [ ] `.env.example` 检查 `QDRANT_URL`、`DASHSCOPE_API_KEY` 占位是否齐全

---

## 四、关键决策与风险

### 决策 1:Embedding 方案
- 默认配置:**LiteLLM + 阿里云 text-embedding-v4**(dim=1024)
- 备选:本地 bge-m3(dim=1024,首次下载 2.3GB)— 离线场景使用
- 切换方式:改 `backend/config/models.yaml` 的 `embedding.provider`

### 决策 2:LangGraph 是否引入
- **预判:Phase 3 不引入**。当前函数链签名已兼容 LangGraph node 包装,Phase 4 出现复杂状态/checkpoint/审批节点再评估
- 决策文档延到 Sprint 4(上线前)

### 决策 3:ORM 模型 ConversationSummary / UserPattern
- 保留模型 + 表(2026-05-06 用户决策)
- Phase 4 长期记忆功能复用,本期 Sprint 3.3 启用 ConversationSummary

### 风险项

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| bge-m3 首次下载阻塞启动(已发生过) | 启动卡死 | A.2 lifespan 异步化 + `SKIP_VECTOR_SYNC` 开关 |
| Qdrant 检索准确率不达预期 | SQL 生成/QA 质量下降 | 已实现自动降级到全量/关键词;Sprint 2 验收 20 条标准评测 |
| 错误码知识库覆盖不全 | 演示效果打折 | Sprint 2.1 至少覆盖 50 条主流错误,迭代扩展 |

---

## 五、参考文档

- [`AGENTS.md`](../AGENTS.md) — Agent 视角的项目说明
- [`ARCHITECTURE.md`](../ARCHITECTURE.md) — 架构设计与升级路径
- [`docs/design/redesign-proposal.md`](design/redesign-proposal.md) — 前端 UI redesign 方案
- [`backend/config/models.yaml`](../backend/config/models.yaml) — LLM 与 Embedding 模型配置

---

*本 ROADMAP 替代已删除的 `PHASE3_PLAN.md`,在 Phase 3 周期内持续维护。Sprint 完成后划掉对应任务,新增任务追加到对应 Sprint 节末尾。*
