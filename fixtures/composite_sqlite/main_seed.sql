INSERT INTO order_stores VALUES
    ('O1', 'S1', '华东'), ('O1', 'S2', '华北'), ('O2', 'S1', '华东'),
    ('O2', 'S2', '华北'), ('O3', 'S1', '华南'), ('O4', 'S1', '华东');
INSERT INTO shipments VALUES
    ('SH1', 'O1', 'S1', '顺丰'), ('SH2', 'O1', 'S2', '中通'),
    ('SH3', 'O2', 'S1', '顺丰'), ('SH4', 'O2', 'S2', '圆通'),
    ('SH5', 'O3', 'S1', '顺丰'), ('SH6', 'O4', 'S1', '中通');
INSERT INTO customers VALUES
    ('C1', 'gold'), ('C2', 'silver'), ('C3', 'gold'), ('C4', 'bronze');
INSERT INTO orders VALUES
    ('O1', 'C1', 120.5), ('O2', 'C2', 80.0), ('O3', 'C1', 45.0),
    ('O4', 'C3', 210.0), ('O5', 'C4', 60.0), ('O6', 'C2', 75.5);
INSERT INTO legacy_parent VALUES ('P1', '旧仓'), ('P2', '新仓');
INSERT INTO legacy_child VALUES ('L1', 'P1'), ('L2', 'P2');
