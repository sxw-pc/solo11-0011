INSERT INTO warehouses VALUES ('W1', '上海'), ('W2', '北京'), ('W3', '深圳');
INSERT INTO inventory VALUES
    ('A1', 'W1', 10), ('A2', 'W2', 20), ('A3', 'W1', 30), ('A4', 'W3', 15);
INSERT INTO stock_levels VALUES
    ('A1', 'W1', 10), ('A2', 'W2', 20), ('A3', 'W1', 30), ('A4', 'W3', 15);
INSERT INTO stock_moves VALUES
    ('M1', 'A1', 'W1'), ('M2', 'A2', 'W2'), ('M3', 'A3', 'W1'), ('M4', 'A4', 'W3');
INSERT INTO notes VALUES ('N1', 'W1'), ('N2', 'W2');
