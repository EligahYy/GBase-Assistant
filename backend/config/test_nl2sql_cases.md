# NL2SQL 语义理解测试用例

> 前置条件：执行 `test_schema.sql` 建表 + `test_data.sql` 插入数据，并确保 GBase 8a 连接已同步 Schema。

## 测试维度

| 维度 | 说明 |
|------|------|
| 术语映射 | 业务术语 → (表, 列) 的正确映射 |
| JOIN 推断 | 多表查询时自动推断关联路径 |
| 聚合理解 | SUM/AVG/COUNT + GROUP BY 的语义对应 |
| 时间过滤 | 自然语言时间表达式 → SQL 日期条件 |
| 枚举过滤 | "金卡会员"/"已取消" → ENUM 值映射 |
| 排序/分页 | "前10"/"最高"/"最低" → ORDER BY + LIMIT |

## 测试用例

### 1. 单表 + 术语映射

| # | 自然语言 | 预期涉及的表/列 | 关键术语 |
|---|---------|---------------|---------|
| 1.1 | 查询所有客户 | customers.customer_name | 客户 |
| 1.2 | 显示产品的名称和单价 | products.product_name, unit_price | 产品, 单价 |
| 1.3 | 有哪些销售区域 | sales_regions.region_name | 区域 |
| 1.4 | 每个产品的库存数量 | products.product_name, stock_quantity | 库存 |

### 2. 聚合查询

| # | 自然语言 | 预期 SQL 特征 |
|---|---------|-------------|
| 2.1 | 各区域的销售额是多少 | SUM(pay_amount) GROUP BY region_id, JOIN sales_regions |
| 2.2 | 每个产品分类的平均单价 | AVG(unit_price) GROUP BY category |
| 2.3 | 总共有多少客户 | COUNT(customer_id) |
| 2.4 | 销售额最高的前5个产品 | SUM(subtotal) GROUP BY product_id ORDER BY DESC LIMIT 5 |
| 2.5 | 各会员等级的累计消费总额 | SUM(total_amount) GROUP BY member_level |

### 3. JOIN 查询

| # | 自然语言 | 预期 JOIN 路径 |
|---|---------|--------------|
| 3.1 | 查询每个客户的订单 | customers → orders (customer_id) |
| 3.2 | 查询每个订单包含哪些产品 | orders → order_items → products |
| 3.3 | 华东区域的客户下了哪些订单 | sales_regions → customers → orders, 过滤 region_name='华东' |
| 3.4 | 各区域负责人管理的客户数量 | sales_regions → customers, GROUP BY manager |

### 4. 时间过滤

| # | 自然语言 | 预期 SQL 特征 |
|---|---------|-------------|
| 4.1 | 今年注册的客户 | WHERE registered_at >= '2025-01-01' |
| 4.2 | 上个月的所有订单 | WHERE order_date BETWEEN ... |
| 4.3 | 2025年第一季度的销售额 | WHERE order_date BETWEEN '2025-01-01' AND '2025-03-31' |
| 4.4 | 最近30天新增的客户 | WHERE registered_at >= CURDATE() - INTERVAL 30 DAY |

### 5. 枚举 + 过滤

| # | 自然语言 | 预期 SQL 特征 |
|---|---------|-------------|
| 5.1 | 查询所有金卡会员 | WHERE member_level = '金卡会员' |
| 5.2 | 已取消的订单有哪些 | WHERE status = 'cancelled' |
| 5.3 | 当前上架的电子产品 | WHERE is_active = 1 AND category = '电子产品' |
| 5.4 | 已完成订单的总额 | WHERE status = 'delivered', SUM(pay_amount) |

### 6. 复合查询（高难度）

| # | 自然语言 | 预期行为 |
|---|---------|---------|
| 6.1 | 华东区域钻石会员的订单总额 | 3表JOIN + 2个过滤条件 + SUM |
| 6.2 | 各产品分类的销售额排行，只看已完成的订单 | JOIN + GROUP BY + WHERE + ORDER BY DESC |
| 6.3 | 深圳智能硬件供应的产品中，哪些卖得最好 | supplier过滤 + SUM(quantity)排序 |
| 6.4 | 今年新增客户中，消费金额最高的前3名 | 时间过滤 + JOIN + SUM + ORDER BY + LIMIT |

## 术语映射验证

执行以下查询确认 glossary 生效（Agent 应先调 `query_glossary` 再生成 SQL）：

| # | 问题 | 应命中的术语 | 应映射到 |
|---|------|-----------|--------|
| G1 | 查询营收最高的区域 | 营收 → 销售额 | orders.pay_amount |
| G2 | 爆款产品有哪些 | 爆款 → 热销产品 | order_items.quantity SUM DESC |
| G3 | 各片区的销量排名 | 片区 → 区域, 销量 → 购买数量 | sales_regions + order_items JOIN |
| G4 | 哪些订单还在等待付款 | 等待付款 → 待付款 | status = 'pending' |
| G5 | 每件商品的进货价和售价是多少 | 进货价 → 成本, 售价 → 单价 | products.cost_price, unit_price |
