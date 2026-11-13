"""主题域：配置严格校验、确定性聚类、桥接表/孤立表与命名的单元测试。"""
import copy
import pandas as pd
import pytest
from tablelink.config import DEFAULT_CONFIG, validate_config
from tablelink.domain import build_domain_settings, partition_domains, annotate_graph
from tablelink.domain.config import DEFAULT_DOMAIN_CONFIG
from tablelink.domain.partition import aggregate_table_edges, suggest_domain_name
from tablelink.exceptions import ConfigError
from tests.conftest import make_dataset
def _assoc(source, target, relation="explicit_fk", confidence=1.0):
    from tablelink.detector.common import make_association
    return make_association(source, "id", target, "id", relation, confidence, "test",
                            evidence=[{"source_value": "1", "target_value": "1"}])
def _three_domain_dataset():
    frames = {name: pd.DataFrame({"id": [1, 2]}) for name in (
        "order_base", "order_item", "order_payment", "stock_base", "stock_movement",
        "logistics_shipment", "logistics_route", "fact_order_stock", "lonely_table")}
    dataset = make_dataset(DEFAULT_CONFIG, frames)
    associations = [
        _assoc("order_item", "order_base"), _assoc("order_payment", "order_base"),
        _assoc("stock_movement", "stock_base"),
        _assoc("logistics_route", "logistics_shipment"),
        _assoc("fact_order_stock", "order_base"),
        _assoc("fact_order_stock", "logistics_shipment"),
        _assoc("fact_order_stock", "stock_base")]
    return dataset, associations
def test_partition_three_domains_bridge_and_isolated():
    dataset, associations = _three_domain_dataset()
    result = partition_domains(list(dataset.tables), associations,
                               build_domain_settings(DEFAULT_CONFIG["domain"]))
    names = {d["name"]: set(d["tables"]) for d in result["domains"]}
    assert set(names) == {"order", "stock", "logistics"}
    assert names["order"] == {"order_base", "order_item", "order_payment"}
    assert names["stock"] == {"stock_base", "stock_movement"}
    assert names["logistics"] == {"logistics_route", "logistics_shipment"}
    assert result["ungrouped_tables"] == ["lonely_table"]
    bridge = result["bridge_tables"]
    assert len(bridge) == 1 and bridge[0]["table"] == "fact_order_stock"
    assert len({l["domain_id"] for l in bridge[0]["domain_links"]}) == 3
    assert "强邻接覆盖 3 个主题域" in bridge[0]["reason"]
def test_partition_is_byte_reproducible_and_order_independent():
    dataset, associations = _three_domain_dataset()
    settings = build_domain_settings(DEFAULT_CONFIG["domain"])
    first = partition_domains(list(dataset.tables), associations, settings)
    second = partition_domains(list(reversed(list(dataset.tables))),
                               list(reversed(associations)), settings)
    assert first == second
def test_bridge_not_forced_into_any_domain():
    dataset, associations = _three_domain_dataset()
    result = partition_domains(list(dataset.tables), associations,
                               build_domain_settings(DEFAULT_CONFIG["domain"]))
    grouped = {t for d in result["domains"] for t in d["tables"]}
    assert "fact_order_stock" not in grouped
    assert "fact_order_stock" not in result["ungrouped_tables"]
def test_weak_boundary_table_goes_ungrouped_without_merging_domains():
    frames = {n: pd.DataFrame({"id": [1, 2]}) for n in ("a1", "a2", "b1", "b2", "wb")}
    dataset = make_dataset(DEFAULT_CONFIG, frames)
    associations = [_assoc("a1", "a2"), _assoc("b1", "b2"), _assoc("wb", "a1"),
                    _assoc("wb", "b1", "value_overlap", 1.0)]
    config = copy.deepcopy(DEFAULT_CONFIG["domain"])
    config["bridge_balance_ratio"] = 0.8
    result = partition_domains(list(dataset.tables), associations,
                               build_domain_settings(config))
    assert result["bridge_tables"] == []
    assert result["ungrouped_tables"] == ["wb"]
    assert sorted(t for d in result["domains"] for t in d["tables"]) == [
        "a1", "a2", "b1", "b2"]
def test_aggregation_uses_confidence_and_relation_weights():
    edges = aggregate_table_edges(
        [_assoc("a", "b", "custom", 1.0),
         _assoc("a", "b", "functional_dependency", 1.0)],
        build_domain_settings(DEFAULT_CONFIG["domain"])["relation_weights"])
    assert len(edges) == 1 and edges[0]["weight"] == round(1.0 + 0.3, 4)
    assert edges[0]["association_count"] == 2
def test_oversized_component_is_deterministically_split():
    frames = {"m{0:02d}".format(i): pd.DataFrame({"id": [1, 2]}) for i in range(6)}
    dataset = make_dataset(DEFAULT_CONFIG, frames)
    names = sorted(frames)
    associations = [_assoc(names[i], names[i + 1]) for i in range(len(names) - 1)]
    config = copy.deepcopy(DEFAULT_CONFIG["domain"])
    config["max_domain_size"] = 3
    settings = build_domain_settings(config)
    result = partition_domains(list(dataset.tables), associations, settings)
    assert all(d["table_count"] <= 3 for d in result["domains"])
    assert set(result["ungrouped_tables"]) == {"m02", "m03"}
    assert result == partition_domains(list(dataset.tables),
                                       list(reversed(associations)), settings)
def test_empty_and_high_threshold_behaviour():
    settings = build_domain_settings(DEFAULT_CONFIG["domain"])
    empty = partition_domains([], [], settings)
    assert empty["domains"] == [] and empty["ungrouped_tables"] == []
    dataset, associations = _three_domain_dataset()
    config = copy.deepcopy(DEFAULT_CONFIG["domain"])
    config["edge_weight_threshold"] = 1.01
    high = partition_domains(list(dataset.tables), associations,
                             build_domain_settings(config))
    assert high["domains"] == [] and high["bridge_tables"] == []
    assert sorted(high["ungrouped_tables"]) == sorted(dataset.tables)
def test_domain_name_frequency_and_fallback():
    name, evidence = suggest_domain_name(
        ["order_base", "order_item", "payment_log"], "order_base")
    assert name == "order" and evidence["name_basis"] == "high_frequency_token"
    fallback, fallback_evidence = suggest_domain_name(["tmp", "log"], "tmp")
    assert fallback == "tmp" and fallback_evidence["name_basis"] == "core_table"
def test_annotate_graph_marks_roles_and_attaches_section():
    dataset, associations = _three_domain_dataset()
    result = partition_domains(list(dataset.tables), associations,
                               build_domain_settings(DEFAULT_CONFIG["domain"]))
    graph = {"nodes": [
        {"id": "table:order_base", "node_type": "table", "table": "order_base"},
        {"id": "table:fact_order_stock", "node_type": "table", "table": "fact_order_stock"},
        {"id": "table:lonely_table", "node_type": "table", "table": "lonely_table"},
        {"id": "field:order_base.id", "node_type": "field", "table": "order_base"}]}
    annotate_graph(graph, result)
    role_of = {n["table"]: n["domain_role"] for n in graph["nodes"]
               if n["node_type"] == "table"}
    assert role_of["fact_order_stock"] == "bridge"
    assert role_of["lonely_table"] == "ungrouped"
    assert role_of["order_base"] in {"core", "member"}
    assert graph["domain"] is result
    assert annotate_graph({"nodes": []}, None) == {"nodes": []}
def _merge_domain(extra):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["domain"] = copy.deepcopy(DEFAULT_DOMAIN_CONFIG)
    config["domain"].update(extra)
    return config
def test_domain_disabled_by_default():
    assert DEFAULT_CONFIG["domain"]["enabled"] is False
    assert validate_config(copy.deepcopy(DEFAULT_CONFIG), "u.yaml")["domain"]["enabled"] is False
@pytest.mark.parametrize("extra,message", [
    ({"enabled": "yes"}, "应为布尔值"), ({"enabled": 1}, "应为布尔值"),
    ({"edge_weight_threshold": -0.1}, "不能小于"),
    ({"edge_weight_threshold": 1.2}, "不能大于"),
    ({"max_domain_size": 1}, "不能小于 2"),
    ({"bridge_min_domains": 1}, "不能小于 2"),
    ({"bridge_balance_ratio": 2}, "不能大于"),
    ({"unknown_key": 1}, "未知配置项"), ({"relation_weights": []}, "应为映射"),
])
def test_domain_scalar_validation(extra, message):
    with pytest.raises(ConfigError) as exc:
        validate_config(_merge_domain(extra), "u.yaml")
    assert message in str(exc.value) and exc.value.key.startswith("domain")
def test_relation_weight_validation():
    config = _merge_domain({})
    config["domain"]["relation_weights"]["made_up"] = 0.5
    with pytest.raises(ConfigError) as exc:
        validate_config(config, "u.yaml")
    assert "未知关系类型" in str(exc.value)
    config = _merge_domain({})
    del config["domain"]["relation_weights"]["custom"]
    with pytest.raises(ConfigError) as exc:
        validate_config(config, "u.yaml")
    assert "缺少权重项" in str(exc.value)
    config = _merge_domain({})
    for key in config["domain"]["relation_weights"]:
        config["domain"]["relation_weights"][key] = 0
    with pytest.raises(ConfigError) as exc:
        validate_config(config, "u.yaml")
    assert "权重之和必须大于 0" in str(exc.value)
    config = _merge_domain({})
    config["domain"]["relation_weights"]["custom"] = "high"
    with pytest.raises(ConfigError):
        validate_config(config, "u.yaml")
def test_domain_section_must_be_mapping():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["domain"] = ["not", "a", "mapping"]
    with pytest.raises(ConfigError) as exc:
        validate_config(config, "u.yaml")
    assert "domain" in exc.value.key
