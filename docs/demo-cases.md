# GBase 8a Assistant — Sprint 3 标准演示用例

> 本文档用于 Sprint 3 验收，覆盖 SQL 生成、错误码查询、知识问答三大核心场景。
> 每条用例包含：输入 → 预期输出 → 验收标准。

---

## 前置条件

1. 后端服务已启动（`make dev-backend` 或 `uvicorn app.main:app`）
2. 前端服务已启动（`make dev-frontend` 或 `npm run dev`）
3. 至少配置一个数据库连接，并粘贴以下测试 Schema DDL：

```sql
CREATE TABLE users (
  user_id INT PRIMARY KEY,
  username VARCHAR(50),
  email VARCHAR(100),
  register_date DATETIME,
  status TINYINT DEFAULT 1
) DISTRIBUTED BY ('user_id');

CREATE TABLE orders (
  order_id BIGINT PRIMARY KEY,
  user_id INT,
  amount DECIMAL(10,2),
  status VARCHAR(20),
  created_at DATETIME
) DISTRIBUTED BY ('order_id');

CREATE TABLE order_items (
  item_id BIGINT PRIMARY KEY,
  order_id BIGINT,
  product_id INT,
  quantity INT,
  price DECIMAL(10,2)
) DISTRIBUTED BY ('order_id');
```

---

## 用例 1：基础单表查询（SQL）

| 项目 | 内容 |
|------|------|
| **输入** | "查询所有状态为 1 的用户" |
| **预期输出** | SQL：`SELECT * FROM users WHERE status = 1;` |
| **验收标准** | 1. 返回合法 GBase 8a SQL<br>2. WHERE 条件正确<br>3. 附带中文解释 |

---

## 用例 2：聚合查询（SQL）

| 项目 | 内容 |
|------|------|
| **输入** | "统计每个状态的用户数量" |
| **预期输出** | SQL：`SELECT status, COUNT(*) AS cnt FROM users GROUP BY status;` |
| **验收标准** | 1. 使用 GROUP BY + COUNT<br>2. 列名引用正确<br>3. sqlglot 验证通过 |

---

## 用例 3：JOIN 查询（SQL）

| 项目 | 内容 |
|------|------|
| **输入** | "查询每个用户的用户名和订单总金额" |
| **预期输出** | SQL：`SELECT u.username, SUM(o.amount) AS total FROM users u JOIN orders o ON u.user_id = o.user_id GROUP BY u.user_id, u.username;` |
| **验收标准** | 1. JOIN 条件正确（user_id）<br>2. 使用表别名<br>3. SUM 聚合 + GROUP BY |

---

## 用例 4：窗口函数（SQL）

| 项目 | 内容 |
|------|------|
| **输入** | "查询每个用户最近下的 3 笔订单" |
| **预期输出** | SQL：`SELECT * FROM (SELECT *, ROW_NUMBER() OVER(PARTITION BY user_id ORDER BY created_at DESC) AS rn FROM orders) t WHERE rn <= 3;` |
| **验收标准** | 1. 使用 ROW_NUMBER() 窗口函数<br>2. PARTITION BY user_id<br>3. ORDER BY created_at DESC |

---

## 用例 5：时间范围查询（SQL）

| 项目 | 内容 |
|------|------|
| **输入** | "查询 2024 年 1 月创建的订单" |
| **预期输出** | SQL：`SELECT * FROM orders WHERE created_at >= '2024-01-01' AND created_at < '2024-02-01';` |
| **验收标准** | 1. 时间范围条件正确<br>2. 使用 DATETIME 比较<br>3. 避免 YEAR()/MONTH() 函数包裹索引列 |

---

## 用例 6：DISTRIBUTED BY 建表（SQL）

| 项目 | 内容 |
|------|------|
| **输入** | "帮我写一个订单明细表，包含订单ID、商品ID、数量和单价，按订单ID分布" |
| **预期输出** | SQL：`CREATE TABLE order_items (item_id BIGINT PRIMARY KEY, order_id BIGINT, product_id INT, quantity INT, price DECIMAL(10,2)) DISTRIBUTED BY ('order_id');` |
| **验收标准** | 1. 包含 DISTRIBUTED BY 子句<br>2. 选择合理的分布键（order_id）<br>3. 数据类型匹配业务场景 |

---

## 用例 7：精确错误码查询（错误码工具）

| 项目 | 内容 |
|------|------|
| **输入** | 在错误码查询页面输入 "1146" |
| **预期输出** | 返回 Error 1146：表不存在（Table '...' doesn't exist）的原因和解决方案 |
| **验收标准** | 1. mode = "exact"<br>2. 显示 code、description、solution<br>3. 解决方案包含具体 SQL 操作 |

---

## 用例 8：关键词错误码查询（错误码工具）

| 项目 | 内容 |
|------|------|
| **输入** | 在错误码查询页面输入 "数据倾斜" |
| **预期输出** | 返回 GBA-1004 及相关错误码 |
| **验收标准** | 1. mode = "keyword" 或 "semantic"<br>2. 结果包含 GBA-1004<br>3. 展示解决方案中包含 DBNODE() 检查方法 |

---

## 用例 9：GBA 错误码查询（错误码工具）

| 项目 | 内容 |
|------|------|
| **输入** | 在错误码查询页面输入 "GBA-2001" |
| **预期输出** | 返回节点不可达错误的排查流程 |
| **验收标准** | 1. mode = "exact"<br>2. category = "cluster_mpp"<br>3. 解决方案包含 gcadmin showcluster 和日志路径 |

---

## 用例 10：GBase 特性知识问答（QA）

| 项目 | 内容 |
|------|------|
| **输入** | "GBase 8a 支持触发器吗？" |
| **预期输出** | 不支持触发器，原因是 MPP 架构不适合行级事件触发，建议迁移到应用层 |
| **验收标准** | 1. 意图分类为 "qa"<br>2. 回答准确引用知识库内容<br>3. 附带代码示例或替代方案 |

---

## 用例 11：分布键选择知识问答（QA）

| 项目 | 内容 |
|------|------|
| **输入** | "DISTRIBUTED BY 怎么选分布键？" |
| **预期输出** | 高基数、JOIN 条件列、GROUP BY 列，避免 NULL 多的列 |
| **验收标准** | 1. 回答包含选择原则<br>2. 包含检查数据分布的 SQL 示例<br>3. MessageBubble 展示引用来源 |

---

## 用例 12：性能优化知识问答（QA）

| 项目 | 内容 |
|------|------|
| **输入** | "GBase 8a 查询慢怎么优化？" |
| **预期输出** | 分布键检查、REPLICATED 维度表、避免 SELECT *、分区裁剪、列压缩等 |
| **验收标准** | 1. 回答覆盖至少 3 个优化方向<br>2. 包含具体 SQL 示例<br>3. sources 区域显示引用的运维文档 |

---

## 用例 13：Schema 浏览器（设置页）

| 项目 | 内容 |
|------|------|
| **操作** | 1. 进入设置页<br>2. 点击已配置 Schema 的连接卡片上的箭头按钮<br>3. 展开 Schema 列表 |
| **预期输出** | 显示 users、orders、order_items 三个表，每个表可展开查看列名 |
| **验收标准** | 1. 正确解析并展示所有表<br>2. 列名标签完整准确<br>3. 折叠/展开交互正常 |

---

## 用例 14：系统状态检查（设置页）

| 项目 | 内容 |
|------|------|
| **操作** | 进入设置页，查看"系统状态"卡片 |
| **预期输出** | 显示数据库、LLM API、向量数据库的连接状态 |
| **验收标准** | 1. 三个状态项均显示<br>2. 状态标签颜色正确（正常/降级/断开）<br>3. 默认模型名称显示正确 |

---

## 用例 15：多轮对话上下文（聊天）

| 项目 | 内容 |
|------|------|
| **Round 1** | "查询每个用户的订单数量" |
| **Round 2** | "再加一个条件，只统计金额大于 100 的订单" |
| **预期输出** | Round 2 的 SQL 包含 JOIN + COUNT + WHERE amount > 100 |
| **验收标准** | 1. Round 2 理解上下文引用（users/orders 表）<br>2. SQL 语法正确<br>3. 保持对话历史加载正常 |

---

## 验收检查清单

- [ ] 用例 1-6（SQL 生成）：全部返回合法 GBase 8a SQL，sqlglot 验证通过
- [ ] 用例 7-9（错误码查询）：精确匹配 + 关键词匹配均正常
- [ ] 用例 10-12（知识问答）：RAG sources 折叠区正常展示引用来源
- [ ] 用例 13（Schema 浏览器）：Settings 页正确展示表结构列表
- [ ] 用例 14（系统状态）：health 接口返回正确的依赖状态
- [ ] 用例 15（多轮对话）：上下文连贯，历史消息加载正常
