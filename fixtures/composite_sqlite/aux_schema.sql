CREATE TABLE warehouses (
    warehouse_id TEXT PRIMARY KEY,
    city TEXT NOT NULL
);
CREATE TABLE inventory (
    sku TEXT PRIMARY KEY,
    warehouse_id TEXT NOT NULL,
    qty INTEGER NOT NULL,
    CONSTRAINT fk_inventory_warehouse FOREIGN KEY (warehouse_id)
        REFERENCES warehouses(warehouse_id) ON DELETE CASCADE
);
CREATE TABLE stock_levels (
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    qty INTEGER NOT NULL,
    PRIMARY KEY (sku, warehouse_id)
);
CREATE TABLE stock_moves (
    move_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    CONSTRAINT fk_move_level FOREIGN KEY (sku, warehouse_id)
        REFERENCES stock_levels(sku, warehouse_id)
        ON DELETE RESTRICT ON UPDATE SET DEFAULT
);
CREATE TABLE notes (
    note_id TEXT PRIMARY KEY,
    warehouse_ref TEXT REFERENCES warehouses
);
