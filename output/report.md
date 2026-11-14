# 表链测绘仪分析报告

> 本报告由本地离线检测生成，不含任何网络请求。
> 所有关联均附检测来源、置信度依据与值域证据，可逐条复核。

## 1. 数据集概览

- 数据表：8 张
- 字段：44 个
- 总行数：90
- 数据源：alarm_info.csv, device_base.csv, maintain_record.csv, sensor_metric.csv, env_monitor.db
- 关联边：75 条（去重后）

| 表名 | 来源类型 | 行数 | 字段数 |
| --- | --- | --- | --- |
| alarm_info | csv | 12 | 6 |
| device_base | csv | 12 | 6 |
| device_registry | sqlite | 12 | 5 |
| engineer_info | sqlite | 4 | 5 |
| maintain_record | csv | 10 | 7 |
| room_info | sqlite | 4 | 4 |
| sensor_calibration | sqlite | 12 | 5 |
| sensor_metric | csv | 24 | 6 |

## 2. 关联类型统计

| 关系类型 | 数量 |
| --- | --- |
| custom | 3 |
| explicit_fk | 2 |
| explicit_naming | 4 |
| functional_dependency | 48 |
| value_overlap | 18 |

按检测来源统计：

| 检测来源 | 贡献关联数 |
| --- | --- |
| custom_rule | 3 |
| functional_dependency | 48 |
| naming_rule | 13 |
| sqlite_foreign_key | 2 |
| value_overlap | 21 |

多来源命中（同一字段对，证据按来源分组）：

| 方向 | 关系类型 | 检测来源 | 来源证据数 |
| --- | --- | --- | --- |
| `alarm_info.device_id` → `device_base.device_id` | custom + explicit_naming + value_overlap | custom_rule, naming_rule, value_overlap | custom_rule:5, naming_rule:5, value_overlap:5 |
| `alarm_info.device_id` → `device_registry.device_id` | explicit_naming + value_overlap | naming_rule, value_overlap | naming_rule:5, value_overlap:5 |
| `device_base.device_id` → `device_registry.device_id` | explicit_naming + value_overlap | naming_rule, value_overlap | naming_rule:5, value_overlap:5 |
| `device_base.room_id` → `room_info.room_id` | explicit_naming + value_overlap | naming_rule, value_overlap | naming_rule:4, value_overlap:4 |
| `device_registry.room_id` → `room_info.room_id` | explicit_fk + explicit_naming + value_overlap | naming_rule, sqlite_foreign_key, value_overlap | naming_rule:4, sqlite_foreign_key:4, value_overlap:4 |
| `maintain_record.engineer_id` → `engineer_info.engineer_id` | custom + explicit_naming + value_overlap | custom_rule, naming_rule, value_overlap | custom_rule:4, naming_rule:4, value_overlap:4 |
| `sensor_calibration.device_id` → `device_registry.device_id` | explicit_fk + explicit_naming | naming_rule, sqlite_foreign_key | naming_rule:5, sqlite_foreign_key:5 |
| `sensor_metric.device_id` → `device_base.device_id` | explicit_naming + value_overlap | naming_rule, value_overlap | naming_rule:5, value_overlap:5 |
| `sensor_metric.device_id` → `device_registry.device_id` | explicit_naming + value_overlap | naming_rule, value_overlap | naming_rule:5, value_overlap:5 |

图谱节点：9 个表节点，21 个字段节点。

## 3. 高置信度关联清单

阈值：置信度 ≥ 0.90。

| 类型 | 方向 | 置信度 | 检测来源 | 证据样例 |
| --- | --- | --- | --- | --- |
| custom | `alarm_info.device_id` → `device_base.device_id` | 1.0000 | custom_rule, naming_rule, value_overlap | D001→D001; D002→D002; D003→D003 |
| value_overlap | `alarm_info.device_id` → `device_registry.device_id` | 1.0000 | naming_rule, value_overlap | D001→D001; D002→D002; D003→D003 |
| value_overlap | `alarm_info.device_id` → `sensor_calibration.device_id` | 1.0000 | value_overlap | D001→D001; D002→D002; D003→D003 |
| value_overlap | `device_base.device_id` → `device_registry.device_id` | 1.0000 | naming_rule, value_overlap | D001→D001; D002→D002; D003→D003 |
| value_overlap | `device_base.device_id` → `sensor_calibration.device_id` | 1.0000 | value_overlap | D001→D001; D002→D002; D003→D003 |
| value_overlap | `device_base.device_type` → `device_registry.device_type` | 1.0000 | value_overlap | camera→camera; controller→controller; gateway→gateway |
| value_overlap | `device_base.room_id` → `device_registry.room_id` | 1.0000 | value_overlap | R01→R01; R02→R02; R03→R03 |
| value_overlap | `device_base.room_id` → `room_info.room_id` | 1.0000 | naming_rule, value_overlap | R01→R01; R02→R02; R03→R03 |
| value_overlap | `device_registry.device_id` → `sensor_calibration.device_id` | 1.0000 | value_overlap | D001→D001; D002→D002; D003→D003 |
| explicit_fk | `device_registry.room_id` → `room_info.room_id` | 1.0000 | naming_rule, sqlite_foreign_key, value_overlap | R01→R01; R02→R02; R03→R03 |
| custom | `maintain_record.engineer_id` → `engineer_info.engineer_id` | 1.0000 | custom_rule, naming_rule, value_overlap | E01→E01; E02→E02; E03→E03 |
| explicit_fk | `sensor_calibration.device_id` → `device_registry.device_id` | 1.0000 | naming_rule, sqlite_foreign_key | D001→D001; D002→D002; D003→D003 |
| value_overlap | `sensor_metric.device_id` → `alarm_info.device_id` | 1.0000 | value_overlap | D001→D001; D002→D002; D003→D003 |
| value_overlap | `sensor_metric.device_id` → `device_base.device_id` | 1.0000 | naming_rule, value_overlap | D001→D001; D002→D002; D003→D003 |
| value_overlap | `sensor_metric.device_id` → `device_registry.device_id` | 1.0000 | naming_rule, value_overlap | D001→D001; D002→D002; D003→D003 |
| value_overlap | `sensor_metric.device_id` → `sensor_calibration.device_id` | 1.0000 | value_overlap | D001→D001; D002→D002; D003→D003 |
| custom | `sensor_calibration.operator_code` → `engineer_info.engineer_id` | 0.9900 | custom_rule | E01→E01; E02→E02; E03→E03 |
| value_overlap | `device_registry.owner_team` → `engineer_info.team` | 0.9038 | value_overlap | 动环组→动环组; 安防组→安防组; 网络组→网络组 |
| value_overlap | `alarm_info.device_id` → `maintain_record.device_id` | 0.9000 | value_overlap | D001→D001; D002→D002; D003→D003 |
| value_overlap | `device_base.device_id` → `maintain_record.device_id` | 0.9000 | value_overlap | D001→D001; D002→D002; D003→D003 |
| explicit_naming | `device_registry.device_id` → `device_base.device_id` | 0.9000 | naming_rule | D001→D001; D002→D002; D003→D003 |
| value_overlap | `device_registry.device_id` → `maintain_record.device_id` | 0.9000 | value_overlap | D001→D001; D002→D002; D003→D003 |
| explicit_naming | `maintain_record.device_id` → `device_base.device_id` | 0.9000 | naming_rule | D001→D001; D002→D002; D003→D003 |
| explicit_naming | `maintain_record.device_id` → `device_registry.device_id` | 0.9000 | naming_rule | D001→D001; D002→D002; D003→D003 |
| value_overlap | `maintain_record.device_id` → `sensor_calibration.device_id` | 0.9000 | value_overlap | D001→D001; D002→D002; D003→D003 |
| explicit_naming | `sensor_calibration.device_id` → `device_base.device_id` | 0.9000 | naming_rule | D001→D001; D002→D002; D003→D003 |
| value_overlap | `sensor_metric.device_id` → `maintain_record.device_id` | 0.9000 | value_overlap | D001→D001; D002→D002; D003→D003 |

## 4. 待确认低置信度关联

没有低于高置信度阈值的显式或值域关联。

## 5. 异常关联提示

- 检测到双向关联 5 组，例如：`device_base.device_id` → `device_registry.device_id` 与反向关联；`device_base.device_id` → `sensor_calibration.device_id` 与反向关联；`device_registry.device_id` → `sensor_calibration.device_id` 与反向关联；`device_base.device_id` → `maintain_record.device_id` 与反向关联；`device_registry.device_id` → `maintain_record.device_id` 与反向关联。请按业务口径确认方向。

## 6. 函数依赖清单

| 函数依赖 | 范围 | 类别 | 置信度 | 一致/有效行 | 证据样例 |
| --- | --- | --- | --- | --- | --- |
| `alarm_info.device_id` → `alarm_info.alarm_level` | same_table | complete | 1.0000 | 12/12 | D001→low; D004→high; D007→medium |
| `alarm_info.device_id` → `alarm_info.handled` | same_table | complete | 1.0000 | 12/12 | D001→True; D004→True; D007→False |
| `alarm_info.device_id` → `device_base.device_type` | cross_table | complete | 1.0000 | 12/12 | D001→sensor; D004→gateway; D007→sensor |
| `alarm_info.device_id` → `device_base.room_id` | cross_table | complete | 1.0000 | 12/12 | D001→R01; D004→R02; D007→R04 |
| `alarm_info.device_id` → `device_base.status` | cross_table | complete | 1.0000 | 12/12 | D001→online; D004→offline; D007→offline |
| `alarm_info.device_id` → `device_registry.device_type` | cross_table | complete | 1.0000 | 12/12 | D001→sensor; D004→gateway; D007→sensor |
| `alarm_info.device_id` → `device_registry.owner_team` | cross_table | complete | 1.0000 | 12/12 | D001→动环组; D004→网络组; D007→动环组 |
| `alarm_info.device_id` → `device_registry.room_id` | cross_table | complete | 1.0000 | 12/12 | D001→R01; D004→R02; D007→R04 |
| `device_base.device_id` → `device_base.device_type` | same_table | complete | 1.0000 | 12/12 | D001→sensor; D002→sensor; D003→sensor |
| `device_base.device_id` → `device_base.room_id` | same_table | complete | 1.0000 | 12/12 | D001→R01; D002→R01; D003→R02 |
| `device_base.device_id` → `device_base.status` | same_table | complete | 1.0000 | 12/12 | D001→online; D002→online; D003→online |
| `device_base.device_id` → `device_registry.device_type` | cross_table | complete | 1.0000 | 12/12 | D001→sensor; D002→sensor; D003→sensor |
| `device_base.device_id` → `device_registry.owner_team` | cross_table | complete | 1.0000 | 12/12 | D001→动环组; D002→动环组; D003→动环组 |
| `device_base.device_id` → `device_registry.room_id` | cross_table | complete | 1.0000 | 12/12 | D001→R01; D002→R01; D003→R02 |
| `device_base.device_id` → `maintain_record.engineer_id` | cross_table | complete | 1.0000 | 10/10 | D001→E01; D002→E03; D003→E02 |
| `device_base.device_id` → `sensor_calibration.operator_code` | cross_table | complete | 1.0000 | 12/12 | D001→E01; D002→E01; D003→E02 |
| `device_registry.device_id` → `device_base.device_type` | cross_table | complete | 1.0000 | 12/12 | D001→sensor; D002→sensor; D003→sensor |
| `device_registry.device_id` → `device_base.room_id` | cross_table | complete | 1.0000 | 12/12 | D001→R01; D002→R01; D003→R02 |
| `device_registry.device_id` → `device_base.status` | cross_table | complete | 1.0000 | 12/12 | D001→online; D002→online; D003→online |
| `device_registry.device_id` → `device_registry.device_type` | same_table | complete | 1.0000 | 12/12 | D001→sensor; D002→sensor; D003→sensor |
| `device_registry.device_id` → `device_registry.owner_team` | same_table | complete | 1.0000 | 12/12 | D001→动环组; D002→动环组; D003→动环组 |
| `device_registry.device_id` → `device_registry.room_id` | same_table | complete | 1.0000 | 12/12 | D001→R01; D002→R01; D003→R02 |
| `device_registry.device_id` → `maintain_record.engineer_id` | cross_table | complete | 1.0000 | 10/10 | D001→E01; D002→E03; D003→E02 |
| `device_registry.device_id` → `sensor_calibration.operator_code` | cross_table | complete | 1.0000 | 12/12 | D001→E01; D002→E01; D003→E02 |
| `maintain_record.device_id` → `device_base.device_type` | cross_table | complete | 1.0000 | 10/10 | D001→sensor; D004→gateway; D007→sensor |
| `maintain_record.device_id` → `device_base.room_id` | cross_table | complete | 1.0000 | 10/10 | D001→R01; D004→R02; D007→R04 |
| `maintain_record.device_id` → `device_base.status` | cross_table | complete | 1.0000 | 10/10 | D001→online; D004→offline; D007→offline |
| `maintain_record.device_id` → `device_registry.device_type` | cross_table | complete | 1.0000 | 10/10 | D001→sensor; D004→gateway; D007→sensor |
| `maintain_record.device_id` → `device_registry.owner_team` | cross_table | complete | 1.0000 | 10/10 | D001→动环组; D004→网络组; D007→动环组 |
| `maintain_record.device_id` → `device_registry.room_id` | cross_table | complete | 1.0000 | 10/10 | D001→R01; D004→R02; D007→R04 |
| `maintain_record.device_id` → `maintain_record.engineer_id` | same_table | complete | 1.0000 | 10/10 | D001→E01; D004→E02; D007→E03 |
| `maintain_record.device_id` → `sensor_calibration.operator_code` | cross_table | complete | 1.0000 | 10/10 | D001→E01; D004→E02; D007→E01 |
| `sensor_calibration.device_id` → `device_base.device_type` | cross_table | complete | 1.0000 | 12/12 | D001→sensor; D002→sensor; D003→sensor |
| `sensor_calibration.device_id` → `device_base.room_id` | cross_table | complete | 1.0000 | 12/12 | D001→R01; D002→R01; D003→R02 |
| `sensor_calibration.device_id` → `device_base.status` | cross_table | complete | 1.0000 | 12/12 | D001→online; D002→online; D003→online |
| `sensor_calibration.device_id` → `device_registry.device_type` | cross_table | complete | 1.0000 | 12/12 | D001→sensor; D002→sensor; D003→sensor |
| `sensor_calibration.device_id` → `device_registry.owner_team` | cross_table | complete | 1.0000 | 12/12 | D001→动环组; D002→动环组; D003→动环组 |
| `sensor_calibration.device_id` → `device_registry.room_id` | cross_table | complete | 1.0000 | 12/12 | D001→R01; D002→R01; D003→R02 |
| `sensor_calibration.device_id` → `sensor_calibration.operator_code` | same_table | complete | 1.0000 | 12/12 | D001→E01; D002→E01; D003→E02 |
| `sensor_calibration.device_id` → `sensor_calibration.precision_value` | same_table | complete | 1.0000 | 12/12 | D001→0.01; D002→0.01; D003→0.02 |
| `sensor_metric.device_id` → `alarm_info.alarm_level` | cross_table | complete | 1.0000 | 24/24 | D001→low; D002→medium; D003→medium |
| `sensor_metric.device_id` → `alarm_info.handled` | cross_table | complete | 1.0000 | 24/24 | D001→True; D002→True; D003→False |
| `sensor_metric.device_id` → `device_base.device_type` | cross_table | complete | 1.0000 | 24/24 | D001→sensor; D002→sensor; D003→sensor |
| `sensor_metric.device_id` → `device_base.room_id` | cross_table | complete | 1.0000 | 24/24 | D001→R01; D002→R01; D003→R02 |
| `sensor_metric.device_id` → `device_base.status` | cross_table | complete | 1.0000 | 24/24 | D001→online; D002→online; D003→online |
| `sensor_metric.device_id` → `device_registry.device_type` | cross_table | complete | 1.0000 | 24/24 | D001→sensor; D002→sensor; D003→sensor |
| `sensor_metric.device_id` → `device_registry.owner_team` | cross_table | complete | 1.0000 | 24/24 | D001→动环组; D002→动环组; D003→动环组 |
| `sensor_metric.device_id` → `device_registry.room_id` | cross_table | complete | 1.0000 | 24/24 | D001→R01; D002→R01; D003→R02 |

## 7. 增量版本对比

- 新增关联：1 条
- 历史关联失效：1 条
- 置信度变化超过 0.05：1 条
- 未变化：73 条

### 新增关联

| 类型 | 方向 | 置信度 | 检测来源 |
| --- | --- | --- | --- |
| functional_dependency | `alarm_info.device_id` → `device_base.status` | 1.0000 | functional_dependency |

### 失效关联

| 类型 | 方向 | 置信度 | 检测来源 |
| --- | --- | --- | --- |
| explicit_naming | `legacy_device.device_id` → `room_info.room_id` | 0.6000 | history |

### 置信度变化

| 方向 | 原置信度 | 现置信度 | 变化 |
| --- | --- | --- | --- |
| `alarm_info.device_id` → `alarm_info.alarm_level` | 0.8000 | 1.0000 | +0.2000 |

## 8. 审计说明

- 值域关联：Jaccard 权重 0.6，名称相似度权重 0.25，同义词权重 0.15，阈值 0.70。
- 高基数字段阈值：基数 > 行数的 80%；引用型 `_id` 字段可豁免。
- 稀疏字段阈值：非空率 < 20% 时跳过。
- 函数依赖：最小样本 10 行，一致率 ≥ 0.90 纳入；≥ 0.999 记为完全依赖。
- 自定义规则优先于自动检测；同端点关联合并为单条边，保留全部来源与按来源分组的证据（零证据来源不计入分组）。
- 本项目无网络请求、无遥测、无外部资源引用。
