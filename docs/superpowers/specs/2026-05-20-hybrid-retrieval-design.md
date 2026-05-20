# 混合检索方案设计：Qdrant 向量检索 + ripgrep 精确检索

> 日期：2026-05-20
> 状态：已确认，待实现

## 背景

GBase 8a Agent 当前知识检索以 Qdrant 向量检索为主，降级走 `FileKnowledgeRetriever`（仅在 FAQ.json 内做简单关键词匹配）。降级路径无法覆盖错误码、SQL 关键字、配置项名等精确查询场景，也无法搜索 FAQ 以外的知识文件。

## 设计目标

构建 **Qdrant 向量检索 + ripgrep 精确检索** 的混合方案：

- **精确查询**（错误码、SQL 关键字、配置项名）→ ripgrep 优先，Qdrant 兜底
- **语义查询**（自然语言问答）→ Qdrant 优先，ripgrep 兜底
- 双路径均非空时，RRF 融合去重
- 对 chain 层透明，`qa_chain.py` 不变

## 架构

```
用户问题
  │
  ├─ QueryRouter（规则分流，零延迟）
  │     ├─ 精确模式匹配 → "precise"
  │     └─ 否则 → "semantic"
  │
  ├─ precise 路径: GrepRetriever → top-10 → 空结果降级 Qdrant
  ├─ semantic 路径: QdrantKnowledgeRetriever → top-10 → 空结果降级 ripgrep
  │
  └─ 后处理: RRF 融合（双路径均非空时）→ top-5 → 注入 LLM
```

## 组件设计

### QueryRouter

规则驱动，不引入模型。触发精确匹配的模式：

- `\b\d{4}\b` — 错误码
- `(错误码|报错|error)\s*[:：]?\s*\d+` — "错误码 1146"
- `\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b` — SQL 关键字
- `` `\w+` `` — 反引号标识符
- `\b(gbase|gccli|gcluster)\b` — GBase 工具名
- `(参数|配置项|变量)\s*[:：]?\s*\w+` — 参数查询

其余归为 semantic。

### GrepRetriever

- 调用 ripgrep CLI（`rg -i -n -C 2 -m 10`）搜索 `knowledge/**/*.{md,yaml,json,jsonl}`
- 用 `asyncio.create_subprocess_exec` 异步执行，不阻塞 event loop
- 关键词提取：从 query 中取有区分度的词（长度>1、非停用词）
- 按匹配行数排名，去重后返回 `list[KnowledgeChunk]`

### HybridKnowledgeRetriever

- 实现 `KnowledgeRetriever` Protocol
- 内聚 QueryRouter + QdrantKnowledgeRetriever + GrepRetriever
- precise 路径：GrepRetriever 先搜，空结果则走 Qdrant
- semantic 路径：Qdrant 先搜，空结果则走 GrepRetriever
- 双路径均非空时：RRF 融合（k=60），取 top-5
- 异常时：任意一条路径可用即继续

## 集成点

改动集中在 `backend/app/dependencies.py` 的 `get_knowledge_retriever()`：

```python
def get_knowledge_retriever() -> KnowledgeRetriever:
    vector = _build_qdrant_retriever()
    grep = GrepRetriever(get_settings().knowledge_dir)
    return HybridKnowledgeRetriever(
        vector=vector,
        grep=grep,
        router=QueryRouter(),
    )
```

`qa_chain.py`、`api/chat.py` 等上游代码不变。

新增文件：

- `backend/app/vector/grep_retriever.py` — GrepRetriever + QueryRouter
- `backend/app/vector/hybrid_retriever.py` — HybridKnowledgeRetriever + RRF 融合

## 评估计划（后续）

1. 从 FAQ.json + errors.md 自动生成 50 条最小测试集（含同义改写变体）
2. 对现有 Qdrant-only 方案跑基线指标（Recall@5、MRR、Hit@5）
3. 实现 Hybrid 后复测，对比提升幅度
4. 评估指标定义见 `docs/superpowers/specs/2026-05-20-hybrid-retrieval-design.md` 第三节

## 实现顺序

1. `GrepRetriever` + `QueryRouter`（可直接作为独立检索器验证）
2. `HybridKnowledgeRetriever` + RRF 融合
3. 接入 `dependencies.py`，保持 `FallbackRetriever` 作为最外层兜底
4. 通过现有 `TESTING=1` 降级路径验证基础功能
5. 启动 Qdrant 环境做集成验证
