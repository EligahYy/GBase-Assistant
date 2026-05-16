# GBase 8a Assistant — Roadmap

> 最近更新：2026-05-16
> 项目状态：Demo 完成态，Phase 3 已完成，Phase 5 SQL 执行能力已提前落地。
> 当前目标：文档收敛、稳态加固，并进入生产化前的 Phase 4。

基础架构、模块地图和开发规范统一见 [`AGENTS.md`](../AGENTS.md)。本文只记录下一步计划。

---

## 当前快照

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 1 MVP | ✅ 完成 | FastAPI + Vue3、Text-to-SQL、SQL 校验、SSE |
| Phase 2 核心增强 | ✅ 完成 | 多轮对话、Schema 管理、反馈、多模型 fallback |
| Phase 3 RAG / 向量检索 | ✅ 完成 | Qdrant、Schema/Few-shot/Knowledge 检索、错误码工具 |
| Phase 5 SQL 执行 | ✅ 提前落地 | 只读执行沙箱、DataBrowser、SqlEditor、Insights |
| Phase 3.5 文档与稳态 | 🚧 当前 | 文档归一、metrics 暴露、功能文档 |
| Phase 4 上线前加固 | ⏭ 下一阶段 | CI/E2E、认证限流、审计、安全收口 |
| Phase 4.5 前端整理 | ⏭ 并行 | 大组件拆分、前端测试 |
| Phase 6 长期记忆 | ⏸ 后续 | ConversationSummary、UserPattern、feedback enrich 调度 |

当前测试口径：后端 pytest 约 80 个用例，覆盖 validator、chain、API、dependencies、crypto、sandbox、metrics。

---

## Phase 3.5 — 文档与稳态加固

目标：让项目说明和真实代码一致，补齐 Demo → 生产化前的基础可观测与用户文档。

| # | 任务 | 优先级 | 状态 |
|---|---|---|---|
| 3.5.1 | 将基础架构、开发规范、关键文件统一收敛到 `AGENTS.md` | P0 | ✅ 已完成 |
| 3.5.2 | 将 `ROADMAP.md` 改为下一步计划，不再承载架构长文 | P0 | ✅ 已完成 |
| 3.5.3 | 将 `ARCHITECTURE.md` 改为兼容旧链接的过渡页 | P0 | ✅ 已完成 |
| 3.5.4 | 清理未使用的 `.claude/` 本地缓存/旧 worktree | P1 | ✅ 已完成 |
| 3.5.5 | 暴露 `/metrics` Prometheus 文本端点 | P0 | ⏭ 下一步 |
| 3.5.6 | 修复摘要任务 LLM 导入与 feedback enricher 知识库路径 | P0 | ⏭ 下一步 |
| 3.5.7 | 为 DataBrowser / Insights / SqlEditor 补 `docs/features/*.md` | P1 | 待启动 |
| 3.5.8 | `health.py` 增加依赖响应时间字段 | P1 | 待启动 |

---

## Phase 4 — 上线前必做

目标：从 Demo 完成态进入可生产部署状态。

| # | 任务 | 优先级 | 建议顺序 |
|---|---|---|---|
| 4.1 | GitHub Actions CI：lint → test → frontend build → docker build | P0 | 1 |
| 4.2 | Playwright E2E：跑通 `docs/demo-cases.md` 核心用例 | P0 | 2 |
| 4.3 | SQL 执行审计日志：用户、连接、SQL、耗时、行数、状态、错误 | P0 | 3 |
| 4.4 | 凭证操作审计：新增、更新、测试连接、删除连接 | P0 | 4 |
| 4.5 | 最小认证：JWT/Session 二选一，配套登录态与登出 | P0 | 5 |
| 4.6 | 限流中间件：chat、stream、query、admin 分级限流 | P0 | 6 |
| 4.7 | CORS / HTTPS / 安全 Header 收口 | P0 | 7 |
| 4.8 | Docker Compose 端到端验证：backend + frontend + qdrant + nginx | P0 | 8 |
| 4.9 | 性能基准：向量检索 vs 全量注入，SQL 执行延迟，LLM 延迟 | P1 | 9 |
| 4.10 | LangGraph 引入评估文档，预判不引入 | P1 | 10 |
| 4.11 | 凭证轮换接口或 KMS 接入方案 | P2 | 后续 |

上线前安全门槛：

- 真实数据库账号必须为只读权限。
- SQL 沙箱不能作为唯一安全边界。
- 所有执行 SQL 必须进入审计日志。
- 生产环境不得开启 debug docs。
- CORS 不能使用宽松开发配置。

---

## Phase 4.5 — 前端架构整理

目标：降低后续维护成本，避免大型单文件继续扩张。

| # | 任务 | 优先级 |
|---|---|---|
| 4.5.1 | 拆分 `SettingsView.vue` 为连接、模型、Schema、系统状态、管理操作 panels | P1 |
| 4.5.2 | 拆分 `DataBrowserView.vue` 为表导航、筛选、数据网格、分页 composables | P1 |
| 4.5.3 | 拆分 `SqlEditorView.vue` 为编辑器、结果表格、保存查询、执行状态 | P1 |
| 4.5.4 | 拆分 `InsightsView.vue` 为概览、倾斜检测、状态变量、进程列表 | P1 |
| 4.5.5 | 拆分 `Sidebar.vue` 为会话列表、标签管理、操作菜单 | P1 |
| 4.5.6 | 引入 Vitest + Vue Test Utils，先覆盖 5-8 个核心组件 | P1 |
| 4.5.7 | 抽离 `useSQLExecution`、`useResultTable`、`useConnectionStatus` | P2 |
| 4.5.8 | Pinia store 分层：chat / connection / settings / savedQueries | P2 |

---

## Phase 6 — 长期记忆与智能化

目标：激活已经预埋但尚未稳定进入主链路的智能能力。

| # | 任务 | 优先级 |
|---|---|---|
| 6.1 | 启用 `ConversationSummary`：N 轮后异步摘要，构建上下文时优先注入摘要 | P1 |
| 6.2 | 启用 `feedback_enricher` 调度：accepted / modified SQL 自动进入 Few-shot | P1 |
| 6.3 | 启用 `UserPattern`：记录常用表、查询模式、用户偏好 | P2 |
| 6.4 | 扩充知识库：FAQ 80、错误码 100、运维文档 60 | P2 |
| 6.5 | RAG 命中率、人工准确率评测脚本化 | P2 |

---

## 近期推荐执行顺序

1. 完成本文档收敛任务：`AGENTS.md`、`ROADMAP.md`、`ARCHITECTURE.md`。
2. 清理 `.claude/`，避免旧工作区文档继续误导。
3. 修复两个后台任务问题：
   - 摘要任务使用不存在的 `app.llm.litellm_client.LiteLLMClient`。
   - feedback enricher 的 `EXAMPLES_PATH` 应改用 `get_settings().knowledge_dir`。
4. 暴露 `/metrics`，复用现有 `backend/app/observability/metrics.py`。
5. 抽出 `chat.py` 的 service/orchestrator，先保证行为不变。
6. 开始 Phase 4：CI、E2E、审计、认证限流。

---

## 决策记录

- **LangGraph**：暂不引入。当前函数链足够，除非出现 checkpoint/resume、人工审批、多 Agent 复杂状态流。
- **SQLite**：当前继续使用，适合单机 <50 人；若并发写锁或生产部署要求提升，再迁移 PostgreSQL。
- **Qdrant**：作为向量检索层，知识库文件仍是源。
- **SQL 执行**：当前功能已存在，但上线前必须补数据库账号只读、审计、认证限流。
- **文档入口**：`AGENTS.md` 是唯一基础架构入口，`ROADMAP.md` 只放计划。
