CREATE TABLE order_stores (
    order_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    region TEXT NOT NULL,
    PRIMARY KEY (order_id, store_id)
);
CREATE TABLE shipments (
    ship_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    store_id TEXT NOT NULL,
    carrier TEXT NOT NULL,
    CONSTRAINT fk_shipment_order_store FOREIGN KEY (order_id, store_id)
        REFERENCES order_stores(order_id, store_id)
        ON DELETE SET NULL ON UPDATE CASCADE
        DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    tier TEXT NOT NULL
);
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    amount REAL NOT NULL,
    CONSTRAINT fk_order_customer FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id)
);
CREATE TABLE legacy_parent (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL
);
CREATE TABLE legacy_child (
    id TEXT PRIMARY KEY,
    parent_id TEXT NOT NULL REFERENCES legacy_parent(id)
);
