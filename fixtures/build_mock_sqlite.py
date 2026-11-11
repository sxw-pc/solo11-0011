"""重建内置 SQLite 演示数据，供无网络环境重复生成 fixture。"""
import os
import sqlite3
ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "mock_sqlite", "env_monitor.db")
SCHEMA = """
CREATE TABLE room_info (
    room_id TEXT PRIMARY KEY,
    room_name TEXT NOT NULL,
    building TEXT NOT NULL,
    floor INTEGER NOT NULL
);
CREATE TABLE device_registry (
    device_id TEXT PRIMARY KEY,
    room_id TEXT NOT NULL,
    device_type TEXT NOT NULL,
    firmware TEXT NOT NULL,
    owner_team TEXT NOT NULL,
    CONSTRAINT fk_device_room FOREIGN KEY (room_id) REFERENCES room_info(room_id)
);
CREATE TABLE engineer_info (
    engineer_id TEXT PRIMARY KEY,
    engineer_name TEXT NOT NULL,
    team TEXT NOT NULL,
    contact TEXT,
    active INTEGER NOT NULL
);
CREATE TABLE sensor_calibration (
    calibration_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    calibrated_on TEXT NOT NULL,
    precision_value REAL NOT NULL,
    operator_code TEXT NOT NULL,
    CONSTRAINT fk_calibration_device FOREIGN KEY (device_id)
        REFERENCES device_registry(device_id)
);
"""
ROOMS = [
    ("R01", "一号机房", "A栋", 1),
    ("R02", "二号机房", "A栋", 2),
    ("R03", "三号机房", "B栋", 1),
    ("R04", "四号机房", "B栋", 2),
]
DEVICES = [
    ("D001", "R01", "sensor", "fw-1.2", "动环组"),
    ("D002", "R01", "sensor", "fw-1.2", "动环组"),
    ("D003", "R02", "sensor", "fw-1.3", "动环组"),
    ("D004", "R02", "gateway", "fw-2.0", "网络组"),
    ("D005", "R03", "camera", "fw-3.1", "安防组"),
    ("D006", "R03", "controller", "fw-2.4", "安防组"),
    ("D007", "R04", "sensor", "fw-1.2", "动环组"),
    ("D008", "R01", "sensor", "fw-1.3", "动环组"),
    ("D009", "R02", "sensor", "fw-1.2", "动环组"),
    ("D010", "R03", "gateway", "fw-2.1", "网络组"),
    ("D011", "R04", "camera", "fw-3.1", "安防组"),
    ("D012", "R04", "controller", "fw-2.4", "安防组"),
]
ENGINEERS = [
    ("E01", "张工", "动环组", "demo-0001", 1),
    ("E02", "李工", "网络组", "demo-0002", 1),
    ("E03", "王工", "安防组", "demo-0003", 0),
    ("E04", "赵工", "动环组", "demo-0004", 1),
]
CALIBRATIONS = [
    ("C001", "D001", "2024-01-20", 0.01, "E01"),
    ("C002", "D002", "2024-01-20", 0.01, "E01"),
    ("C003", "D003", "2024-01-21", 0.02, "E02"),
    ("C004", "D004", "2024-01-21", 0.05, "E02"),
    ("C005", "D005", "2024-01-22", 0.10, "E03"),
    ("C006", "D006", "2024-01-22", 0.02, "E03"),
    ("C007", "D007", "2024-01-23", 0.01, "E01"),
    ("C008", "D008", "2024-01-23", 0.02, "E04"),
    ("C009", "D009", "2024-01-24", 0.01, "E04"),
    ("C010", "D010", "2024-01-24", 0.05, "E02"),
    ("C011", "D011", "2024-01-25", 0.10, "E03"),
    ("C012", "D012", "2024-01-25", 0.02, "E04"),
]
def build():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO room_info VALUES (?, ?, ?, ?)", ROOMS)
        connection.executemany("INSERT INTO device_registry VALUES (?, ?, ?, ?, ?)", DEVICES)
        connection.executemany("INSERT INTO engineer_info VALUES (?, ?, ?, ?, ?)", ENGINEERS)
        connection.executemany("INSERT INTO sensor_calibration VALUES (?, ?, ?, ?, ?)", CALIBRATIONS)
        connection.commit()
    finally:
        connection.close()
    return DB_PATH
if __name__ == "__main__":
    print("SQLite fixture rebuilt: {0}".format(build()))
