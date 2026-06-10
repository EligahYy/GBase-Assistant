CREATE TABLE sales_regions (
    region_id INTEGER PRIMARY KEY,
    region_name TEXT NOT NULL,
    manager TEXT,
    created_at TEXT
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    customer_name TEXT NOT NULL,
    region_id INTEGER NOT NULL,
    member_level TEXT,
    phone TEXT,
    registered_at TEXT,
    total_orders INTEGER,
    total_amount NUMERIC,
    FOREIGN KEY (region_id) REFERENCES sales_regions(region_id)
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT,
    unit_price NUMERIC,
    cost_price NUMERIC,
    stock_quantity INTEGER,
    supplier TEXT,
    created_at TEXT,
    is_active INTEGER
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    status TEXT,
    pay_amount NUMERIC,
    discount_amount NUMERIC,
    region_id INTEGER,
    remark TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (region_id) REFERENCES sales_regions(region_id)
);

CREATE TABLE order_items (
    item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER,
    unit_price NUMERIC,
    subtotal NUMERIC,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
