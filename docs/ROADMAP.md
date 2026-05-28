# GBase 8a Assistant — Roadmap

> 最近更新：2026-05-28
> 项目状态：v2 多智能体架构已完成，LangGraph 编排 + AG-UI 协议。
> 当前目标：知识库完善、反馈学习闭环、前端 v2 UI 接入。

## 当前快照

| 阶段 | 状态 | 说明 |
|---|---|---|
| v2 多智能体重构 | ✅ 完成 | LangGraph 7 Agent + AG-UI + Schema Knowledge Graph + SSE 连接检测 |
| 知识库 PDF 索引 | ✅ 完成 | 官方产品手册章节切片 + Qdrant 向量索引 + pages.json 缓存 |
| v1 架构移除 | ✅ 完成 | 旧 chat_service / intent / sql_chain 移除，v2 为唯一架构 |
| 前端 v2 UI 接入 | ⏭ 下一步 | useAGUIClient 适配器已就绪，待 ChatPanel 升级接入 AG-UI 事件 |
| Feedback Learner | ⏭ 下一步 | 用户反馈 → 别名权重更新 → Few-shot 自动积累 |
| CI / E2E / 审计 | ⏸ 后续 | GitHub Actions、Playwright E2E、SQL 执行审计 |

## 近期推荐执行顺序

1. 前端 ChatPanel 接入 AG-UI 事件（`useAGUIClient`）
2. PDF 手册首次索引（`POST /api/admin/reindex-pdf`）
3. Feedback Learner 闭环（别名学习 + 示例积累）
4. CI + E2E 测试

## 决策记录

- **LangGraph**：已引入，作为 v2 核心编排框架（Orchestrator-Subagent 模式）。
- **AG-UI**：标准化 SSE 事件协议，单 FastAPI 进程实现，无需 Node.js 中间层。
- **知识库**：PDF 手册 pages.json 缓存 + 官方文档优先，模型生成内容归档到 v1_archive。
- **v1/v2 共存**：已结束，v2 为唯一架构。
