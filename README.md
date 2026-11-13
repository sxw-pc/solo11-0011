# 表链测绘仪（TableLink Mapper）

## 1. 项目信息

表链测绘仪是一个**完全离线的本地结构化数据关联发现工具**，面向拥有未文档化 CSV / SQLite 数据集的小团队。它在单机内完成数据加载、显式关联识别、隐式值域重叠、函数依赖、图谱构建、增量比较与多格式导出，不调用任何外部服务。

- 数据源：本地 CSV 目录（UTF-8 / UTF-8-SIG / GBK）与 SQLite 文件。
- 输出：JSON / YAML 规则、Markdown 报告、单文件离线 HTML 交互图谱。
- 运行环境：Python 3.8–3.12，Windows / macOS / Linux；项目自带测试数据，开箱可跑。
- 设计约束：无 CDN、无遥测、无外部 API；Flask 仅监听回环地址；所有文件 UTF-8、无硬编码密钥。

目录：`tablelink/` 检测与导出库，`static/` 本地 ECharts 与前端资源，`fixtures/` 演示及边界数据，`tests/` 自动化测试，`output/` 运行产物。

## 2. 离线安装

在可联网机器上准备依赖 wheel 包（或使用组织内部 PyPI 镜像），把 wheel 放入 `wheelhouse/`，再拷贝整个项目到离线机器：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
python -m pip install --no-index --find-links=wheelhouse -r requirements.txt
```

直接依赖：pandas、SQLAlchemy、networkx、PyYAML、Jinja2、Flask、pytest、pytest-cov。运行和测试阶段均不需要网络；`static/echarts.min.js` 已本地化，HTML 图谱可脱离服务器双击打开。

## 3. 快速开始

```bash
python run_demo.py                 # 一键批处理：默认读取 config.yaml，写出 output/
python run_demo.py --no-baseline   # 不做增量对比
python run_demo.py --baseline output/relations.json   # 与历史规则比较
python run_web.py                  # 本地控制台：http://127.0.0.1:5000
pytest tests/ -v                   # 全量测试（含覆盖率门槛）
```

`output/` 包含 `relations.json`、`relations.yaml`、`report.md`、`graph.json`、`graph.html`。`graph.html` 内嵌 ECharts 与全部样式脚本，可直接双击离线查看；支持拖拽、缩放、关系/置信度/表名/变化筛选，点击边查看检测来源、置信度依据与匹配证据。Web 控制台可执行扫描、热加载配置、查看图谱与下载全部产物。

## 4. 自定义数据源

编辑 `config.yaml` 的 `sources`：

```yaml
sources:
  csv_dirs: ["data/csv", "fixtures/mock_csv"]
  sqlite_files: ["data/app.db"]
  csv_encodings: ["utf-8-sig", "utf-8", "gbk"]
  exclude_tables: ["tmp_*", "sqlite_*"]
  exclude_fields: ["created_at", "raw_payload"]
```

表名取 CSV 文件名（去扩展名）或 SQLite 表名；重名表会自动加来源后缀并记录提示。CSV 依次尝试编码候选，坏文件、NUL、字段数异常只影响单文件，错误会进入报告的“异常关联提示”。

人工规则放在 YAML 中，优先级最高：

```yaml
rules:
  - source: maintain_record.engineer_id
    target: engineer_info.engineer_id
    confidence: 1.0
    relation: reference
    note: 运维台账与人员表的人工确认关系
```

通过 `explicit.custom_rules_path` 引用；规则表/字段不存在、置信度越界、YAML 语法错误都会抛出带位置和修复建议的配置错误。

## 5. 配置参考

| 配置段 | 关键项 | 默认值 / 说明 |
| --- | --- | --- |
| `project` | `name`, `version` | 项目展示信息 |
| `sources` | `csv_dirs`, `sqlite_files`, `csv_encodings` | 数据源、编码回退顺序；`include_tables`/`exclude_tables`/`exclude_fields` 使用通配符 |
| `explicit.naming` | `suffixes`, `synonym_map`, `confidence` | 命名规则后缀、同义词组、置信度 0.84 |
| `explicit` | `custom_rules_path` | 自定义 YAML 规则路径，最高优先级 |
| `overlap` | `threshold`, `min_matched_values`, `weights` | 默认阈值 0.70、至少 3 个交集值、权重 0.60/0.25/0.15 |
| `overlap` | `max_cardinality_ratio`, `min_nonnull_ratio`, `strict_type` | 高基数/稀疏保护与类型兼容开关 |
| `fd` | `min_rows`, `confidence_threshold`, `complete_threshold` | 默认 10 行、0.90、0.999 |
| `fd` | `cross_table`, `max_per_table` | 跨表函数依赖与单表输出上限 |
| `incremental` | `confidence_delta_threshold`, `default_baseline` | 置信度变化阈值 0.05；默认历史文件 |
| `output` | `directory`, 各文件名 | 所有产物目录与文件名 |
| `report` | `high_confidence` | 报告高置信度阈值 0.90 |
| `domain` | `enabled`, `edge_weight_threshold`, `max_domain_size`, `bridge_*`, `relation_weights` | 主题域自动划分，**默认关闭**；强边阈值 0.55、域规模上限 25、桥接平衡比 0.65 |
| `web` | `host`, `port`, `auto_reload` | 仅允许 `127.0.0.1`、`localhost`、`::1`；热加载默认开启 |

配置经严格 Schema 校验：未知项、类型错误、越界值、非法编码/主机都会指出字段路径和修复建议；Web 模式扫描前自动检测配置文件签名变化并热加载。

## 6. 算法说明

1. **显式关联**：读取 SQLite `PRAGMA foreign_key_list` 原生外键；按 `_id` 后缀、同名字段、表名 token 与同义词映射匹配目标键，并要求值域交集比例达标；自定义规则覆盖自动检测。三类来源分别标注 `sqlite_foreign_key`、`naming_rule`、`custom_rule`。
2. **隐式值域重叠**：字段值规范化后计算 Jaccard 交集；名称相似度用 `SequenceMatcher`，同义词命中单独计分，加权归一得到置信度。跳过全空、稀疏、低基数、高基数（引用型 `_id` 跨表豁免）和类型不兼容字段；至少保留 3 条匹配证据。
3. **函数依赖**：按源字段分组校验目标唯一值，置信度 = 一致行数 / 有效行数；达到 0.999 记为 `complete`，否则 `partial`。跨表依赖沿检测到的键关联连接目标表，输出关联路径、行数与证据。小样本、常量目标与唯一代理键会被过滤。
4. **图与去重**：networkx 有向图同时生成表节点、字段节点、结构包含边和关联边。同端点关联保留最高置信度，同时保留全部关系类型、检测来源、证据和检测明细；筛选后自动删除孤立表节点。
5. **可复现**：输出不写入当前时间戳，排序稳定，因此相同输入和配置会生成字节级一致的 JSON/YAML/Markdown/图谱数据。

## 6.1 主题域自动划分（`domain.enabled: true` 开启，默认关闭）

目标是把上百张表自动归入若干主题域，并明确区分域成员、跨域桥接表与未分组表。

1. **表级加权边**：把字段级关联按无向表对折叠，边权重 = 同表对全部关联的 `置信度 × 关系类型权重` 之和（四舍五入到 4 位）。关系权重区分信号强度：人工规则/原生外键 1.0、命名匹配 0.9、值域重叠 0.7、函数依赖仅 0.3（FD 数量多但业务内聚含义弱，避免它主导聚类）。权重达到 `edge_weight_threshold` 的边记为强边。
2. **确定性聚类（无随机初始化）**：全程不使用随机数、不设迭代初值。强边做单链并查集得到连通分量，超过 `max_domain_size` 的分量按“最弱内边优先切、同权重取字典序最大边”反复切分。并查集合并时以字典序较小的根为新根，所有输出按名称字典序排序，因此得分并列或输入顺序变化都不会改变分组。
3. **跨域桥接表**：对每张表在**同一张原始强边图**上独立评估——临时摘除它后做并查集，只统计成员数 ≥2 的“域级分量”（摘除核心表导致叶子坍缩成的单点分量不计，避免误伤域内枢纽表）。强邻接覆盖 ≥`bridge_min_domains` 个域级分量的表是边界表，一律不进任何域；其中次强域权重达到最强域 `bridge_balance_ratio` 比例的标注为 `bridge` 并给出逐域权重依据与首要关联域，达不到比例的弱边界表进未分组清单。这样“同时强关联订单与物流的事实表”不会被硬塞进某一个域。
4. **孤立表与命名**：没有任何强邻接的表（含加载后无关联的孤立表）不进任何域，单列在 `ungrouped_tables`。域名称优先取域内表名高频词（过滤 `info/base/record` 等通用词，词频并列按字典序裁决），无可用词时回退到域内累计权重最高的核心表名，命名依据随产物输出便于复核。
5. **产物落点**：JSON/YAML 的 `domain` 段、`graph.json` 表节点的 `domain_id`/`domain_role`/`domain_name` 与顶层 `domain` 段、Markdown 第 8 节按域分节、离线 HTML 与本地 Web 控制台的按域着色和筛选。功能关闭时这些键与界面元素均不出现，既有产物逐字节不变。

## 7. 增量对比指南

以上一次导出的 `rules.json`（或 YAML）作为基线：

```bash
python run_demo.py --baseline history/relations.json
```

也可设置 `incremental.default_baseline: history/relations.json` 让批处理和 Web 默认使用。比较按“源表.字段 → 目标表.字段”端点对齐，分类：

- `added`：本次新增；`removed`：历史存在但本次消失（HTML 中以 ghost 边保留，便于审计）；
- `confidence_changed`：绝对变化超过 `confidence_delta_threshold`（默认 0.05）；其余计入 `unchanged`。

结果写入 JSON 的 `incremental`、Markdown 第 7 节和 HTML 的增量筛选/状态色。建议每次人工确认后将新结果归档为下一期基线。

## 8. 常见问题（FAQ）

**Q：CSV 中文乱码或加载失败？** 按 `utf-8-sig`、`utf-8`、`gbk` 顺序自动尝试；仍失败时检查文件损坏或 NUL 字节，错误会显示具体文件名。  
**Q：为什么某个明显关系没被识别？** 检查字段是否高基数/稀疏、类型是否兼容、交集值是否少于 3 个，或提高 `overlap.threshold` 前先看证据。  
**Q：为什么函数依赖的结果很多？** 键字段到低基数属性可能形成有效但业务价值较低的依赖；可提高 `confidence_threshold`、降低 `max_per_table`，或关闭 `cross_table`。  
**Q：空表、坏表会中断扫描吗？** 不会。单文件错误被隔离并在报告中列出，空表保留结构元数据但不产生关联。  
**Q：Web 服务能对局域网开放吗？** 不能。配置校验和启动脚本都只允许回环地址；服务端还会拒绝非本机 `remote_addr`。  
**Q：可以删除 `output/` 吗？** 可以，它只包含运行产物；下次运行会安全重建。  
**Q：如何重置演示数据？** 删除 `output/` 后执行 `python run_demo.py`；SQLite 演示库可用 `python fixtures/build_mock_sqlite.py` 重建。  
**Q：为何每个 Python 文件不超过 300 行？** 便于审计与维护；本仓库测试会校验单文件行数和总行数预算。
**Q：主题域划分结果稳定吗？** 稳定。聚类全程无随机初始化，并查集根、切边、词频与域编号的所有并列都按名称字典序裁决，相同输入和配置任意次运行的分组与全部产物逐字节一致。
**Q：桥接表为什么不直接归到关联最强的域？** 它的业务语义本身跨域，硬归入单一会误导治理。工具只标注其跨域身份、逐域权重依据和首要关联域，最终归属留给人工决策；达不到平衡比例的弱边界表则进未分组清单。

## 9. 合规声明

- 全程离线：加载、检测、导出、Web 页面与静态资源均来自本机，无外部网络请求、无 CDN、无遥感/遥测。
- 数据不离开本机：不上传、不同步、不写入第三方系统；临时文件只落在配置指定的本地输出目录。
- Web 服务只绑定 `127.0.0.1` / `localhost` / `::1`，并校验访问来源回环地址。
- 仓库不含真实密钥、令牌、内部服务地址或第三方系统地址；示例数据均为合成数据。
- ECharts 5.5.1 以 Apache-2.0 许可本地分发，许可文本见 `static/ECHARTS-LICENSE.txt`；其余代码为本项目交付代码。
- 使用前请确认对目标数据拥有合法处理权限。本工具只提供关联线索，不替代业务主键、外键或数据治理决策；高影响结论应结合证据人工复核。
