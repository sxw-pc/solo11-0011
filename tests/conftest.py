"""共享测试夹具。"""
import copy, os
from pathlib import Path
import pandas as pd
import pytest
import yaml
from tablelink.config import ConfigManager
from tablelink.detector import detect_explicit, detect_fd, detect_overlap
from tablelink.loader import BaseLoader, Dataset, load_dataset
ROOT = Path(__file__).resolve().parents[1]
@pytest.fixture(scope="session")
def config_manager():
    return ConfigManager(str(ROOT / "config.yaml"), base_dir=str(ROOT))
@pytest.fixture(scope="session")
def default_config(config_manager):
    return config_manager.load()
@pytest.fixture(scope="session")
def default_dataset(default_config):
    return load_dataset(default_config, str(ROOT))
@pytest.fixture(scope="session")
def explicit_associations(default_dataset, default_config):
    return detect_explicit(default_dataset, default_config, str(ROOT))
@pytest.fixture(scope="session")
def overlap_associations(default_dataset, default_config):
    return detect_overlap(default_dataset, default_config)
@pytest.fixture(scope="session")
def fd_associations(default_dataset, default_config, explicit_associations, overlap_associations):
    return detect_fd(default_dataset, default_config, explicit_associations + overlap_associations)
def make_dataset(config, frames):
    """由内存 DataFrame 构造 Dataset，便于边界场景测试。"""
    dataset = Dataset()
    loader = BaseLoader(config)
    for name, frame in frames.items():
        dataset.add_table(loader.make_table(name, frame, name + ".csv"))
    return dataset
def write_config(tmp_path, base, **updates):
    """把完整默认配置写入临时文件，返回路径与配置管理器的基目录。"""
    payload = copy.deepcopy(base)
    for key, value in updates.items():
        section, field = key.split(".", 1)
        payload[section][field] = value
    path = Path(tmp_path) / "config.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(path)
@pytest.fixture
def frame_factory():
    return pd.DataFrame
