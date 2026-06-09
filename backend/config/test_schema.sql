-- ============================================================================
-- GBase 8a 测试 Schema — 电商销售场景
-- 兼容 GBase 8a MPP 语法
-- ============================================================================

-- 1. 销售区域表
CREATE TABLE sales_regions (
    region_id    INT          COMMENT 'PRIMARY_KEY|区域ID',
    region_name  VARCHAR(64)  COMMENT '区域名称|华东/华南/华北/西南/西北',
    manager      VARCHAR(32)  COMMENT '区域负责人',
    created_at   DATETIME     COMMENT 'TIME_DIMENSION|创建时间'
) DISTRIBUTED BY ('region_id');

-- 2. 客户表
CREATE TABLE customers (
    customer_id   INT           COMMENT 'PRIMARY_KEY|客户ID',
    customer_name VARCHAR(64)   COMMENT '客户名称',
    region_id     INT           COMMENT 'FOREIGN_KEY→sales_regions|所属区域',
    member_level  VARCHAR(16)   COMMENT 'ENUM|会员等级|1=普通会员|2=银卡会员|3=金卡会员|4=钻石会员',
    phone         VARCHAR(20)   COMMENT '联系电话',
    registered_at DATETIME      COMMENT 'TIME_DIMENSION|注册时间',
    total_orders  INT           COMMENT 'MEASURE|累计订单数',
    total_amount  DECIMAL(14,2) COMMENT 'MEASURE|累计消费金额'
) DISTRIBUTED BY ('customer_id');

-- 3. 产品表
CREATE TABLE products (
    product_id    INT           COMMENT 'PRIMARY_KEY|产品ID',
    product_name  VARCHAR(128)  COMMENT '产品名称',
    category      VARCHAR(32)   COMMENT 'ENUM|产品分类|电子产品|家居用品|食品饮料|服装鞋帽|图书音像',
    unit_price    DECIMAL(10,2) COMMENT 'MEASURE|单价',
    cost_price    DECIMAL(10,2) COMMENT 'MEASURE|成本价',
    stock_quantity INT          COMMENT 'MEASURE|库存数量',
    supplier      VARCHAR(64)   COMMENT '供应商',
    created_at    DATETIME      COMMENT 'TIME_DIMENSION|上架时间',
    is_active     SMALLINT       COMMENT 'ENUM|是否上架|1=上架|0=下架'
) DISTRIBUTED BY ('product_id');

-- 4. 订单表
CREATE TABLE orders (
    order_id      INT           COMMENT 'PRIMARY_KEY|订单ID',
    customer_id   INT           COMMENT 'FOREIGN_KEY→customers|客户ID',
    order_date    DATETIME      COMMENT 'TIME_DIMENSION|下单时间',
    status        VARCHAR(16)   COMMENT 'ENUM|订单状态|pending=待付款|paid=已付款|shipped=已发货|delivered=已完成|cancelled=已取消',
    pay_amount    DECIMAL(14,2) COMMENT 'MEASURE|实付金额',
    discount_amount DECIMAL(14,2) COMMENT 'MEASURE|优惠金额',
    region_id     INT           COMMENT 'FOREIGN_KEY→sales_regions|配送区域',
    remark        VARCHAR(256)  COMMENT '备注'
) DISTRIBUTED BY ('order_id');

-- 5. 订单明细表
CREATE TABLE order_items (
    item_id       INT           COMMENT 'PRIMARY_KEY|明细ID',
    order_id      INT           COMMENT 'FOREIGN_KEY→orders|订单ID',
    product_id    INT           COMMENT 'FOREIGN_KEY→products|产品ID',
    quantity      INT           COMMENT 'MEASURE|购买数量',
    unit_price    DECIMAL(10,2) COMMENT 'MEASURE|成交单价',
    subtotal      DECIMAL(14,2) COMMENT 'MEASURE|小计金额'
) DISTRIBUTED BY ('item_id');
