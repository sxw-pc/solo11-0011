(function () {
  "use strict";
  var GRAPH = window.__GRAPH__ || { nodes: [], stats: {} };
  var DIFF = window.__DIFF__ || null;
  var root = document.documentElement;
  var chart = document.getElementById("graph");
  var emptyState = document.getElementById("emptyState");
  var detailPanel = document.getElementById("detailPanel");
  var tableBody = document.getElementById("edgeTableBody");
  var FAMILIES = ["explicit", "overlap", "fd", "contains"];
  var FAMILY_LABELS = { explicit: "显式 / 人工", overlap: "值域重叠", fd: "函数依赖", contains: "结构包含" };
  var RELATION_LABELS = { custom: "人工规则", explicit_fk: "原生外键", explicit_naming: "命名匹配",
    value_overlap: "值域重叠", functional_dependency: "函数依赖", contains: "表-字段结构" };
  var CHANGE_LABELS = { added: "新增", removed: "失效", confidence_changed: "置信度变化" };
  var nodeIndex = {};
  var edgeIndex = {};
  var shardEdges = {};
  var shardPending = {};
  var shardErrors = {};
  var fetches = {};
  var edgePool = null;
  var started = false;
  var instance = null;
  (GRAPH.nodes || []).forEach(function (node) { nodeIndex[node.id] = node; });
  window.__TL_SHARDS__ = { mode: "sharded", loaded: [], fetches: fetches, errors: shardErrors };

  function esc(value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }
  function css(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function family(type) {
    if (type === "value_overlap") return "overlap";
    if (type === "functional_dependency") return "fd";
    if (type === "contains") return "contains";
    return "explicit";
  }
  function relationLabel(type) { return RELATION_LABELS[type] || type; }
  function shardEntry(name) {
    var found = null;
    ((GRAPH.shards && GRAPH.shards.families) || []).forEach(function (item) {
      if (item.family === name) found = item;
    });
    return found;
  }
  function loadShard(name) {
    var entry = shardEntry(name);
    if (!entry) return Promise.resolve([]);
    if (shardEdges[name]) return Promise.resolve(shardEdges[name]);
    if (shardPending[name]) return shardPending[name];
    if (typeof location !== "undefined" && location.protocol === "file:") {
      shardErrors[name] = entry.file + " · 浏览器禁止 file:// 读取伴生分片，请改用单文件模式或本地 HTTP 服务";
      return Promise.resolve([]);
    }
    var url = (GRAPH.shards.base || "") + entry.file;
    fetches[name] = (fetches[name] || 0) + 1;
    shardPending[name] = fetch(url, { cache: "no-cache" }).then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return response.json();
    }).then(function (payload) {
      if (!payload || !Array.isArray(payload.edges)) throw new Error("分片格式不正确");
      shardEdges[name] = payload.edges;
      if (window.__TL_SHARDS__.loaded.indexOf(name) < 0) window.__TL_SHARDS__.loaded.push(name);
      delete shardErrors[name];
      return payload.edges;
    }).catch(function (error) {
      shardErrors[name] = url + " · " + error.message;
      return null;
    }).then(function (edges) { delete shardPending[name]; return edges; });
    return shardPending[name];
  }
  function checkState() {
    var selected = {};
    document.querySelectorAll("[data-relation]").forEach(function (box) { selected[box.value] = box.checked; });
    return selected;
  }
  function filters() {
    return { relations: checkState(),
      confidence: parseFloat(document.getElementById("confidenceRange").value || "0"),
      table: document.getElementById("tableFilter").value.trim().toLowerCase(),
      change: document.getElementById("changeFilter").value,
      structural: document.getElementById("structuralToggle").checked };
  }
  function neededFamilies(state) {
    return FAMILIES.filter(function (fam) {
      if (fam === "contains") return state.structural && state.change === "all";
      return Object.keys(RELATION_LABELS).some(function (type) {
        return family(type) === fam && state.relations[type];
      });
    });
  }
  function allEdges() {
    if (edgePool) return edgePool;
    var map = {};
    FAMILIES.forEach(function (name) {
      (shardEdges[name] || []).forEach(function (edge) { map[edge.id] = edge; edgeIndex[edge.id] = edge; });
    });
    edgePool = Object.keys(map).map(function (id) { return map[id]; });
    return edgePool;
  }
  function tableMatches(edge, term) {
    return !term || edge.source_table.toLowerCase().indexOf(term) >= 0 ||
      edge.target_table.toLowerCase().indexOf(term) >= 0;
  }
  function passes(edge, state) {
    if (edge.structural) return false;
    if (state.change !== "all") {
      if (edge.change !== state.change) return false;
    } else if (edge.change === "removed") {
      return false;
    }
    var types = edge.relation_types || [edge.relation_type];
    if (!types.some(function (type) { return state.relations[type]; })) return false;
    if ((edge.confidence || 0) < state.confidence) return false;
    return tableMatches(edge, state.table);
  }
  function visibleView() {
    var state = filters();
    var pool = allEdges();
    var associations = pool.filter(function (edge) { return passes(edge, state); });
    var ids = new Set();
    var tableIds = new Set();
    associations.forEach(function (edge) {
      ids.add(edge.source); ids.add(edge.target);
      tableIds.add("table:" + edge.source_table);
      tableIds.add("table:" + edge.target_table);
    });
    var visibleEdges = associations.slice();
    if (state.structural && state.change === "all") {
      pool.forEach(function (edge) {
        if (edge.structural && tableIds.has(edge.source) && ids.has(edge.target)) visibleEdges.push(edge);
      });
    }
    var nodes = (GRAPH.nodes || []).filter(function (node) {
      return node.node_type === "field" ? ids.has(node.id) : tableIds.has(node.id);
    });
    return { associations: associations, edges: visibleEdges, nodes: nodes, state: state };
  }
  function sourceText(edge) { return (edge.detection_sources || []).join(", ") || "-"; }
  function typeText(edge) { return (edge.relation_types || [edge.relation_type]).map(relationLabel).join(" + "); }
  function familyColor(type) {
    var fam = family(type);
    if (fam === "overlap") return css("--series-2");
    if (fam === "fd") return css("--series-3");
    if (fam === "contains") return css("--muted");
    return css("--series-1");
  }
  function changeColor(change) {
    if (change === "added") return css("--good");
    if (change === "removed") return css("--critical");
    if (change === "confidence_changed") return css("--warning");
    return null;
  }
  function dashFor(type, change) {
    if (change === "removed") return "dotted";
    if (change) return "dashed";
    if (type === "custom") return [7, 3];
    if (type === "explicit_naming") return [4, 3];
    if (type === "contains") return "dotted";
    return "solid";
  }
  function nodeOption(node) {
    var dark = root.getAttribute("data-theme") === "dark";
    var isTable = node.node_type === "table";
    var base = isTable ? (dark ? "#c3c2b7" : "#52514e") : css("--series-1");
    var size = isTable ? [Math.max(72, Math.min(96, node.name.length * 6.2 + 14)), 28] : 14 + Math.min(node.degree || 0, 7) * 1.5;
    return { id: node.id, name: node.name, category: node.category,
      symbol: isTable ? "roundRect" : "circle", symbolSize: size, draggable: true, value: node.degree || 0,
      itemStyle: isTable
        ? { color: base, borderColor: dark ? "#1a1a19" : "#fcfcfb", borderWidth: 2, opacity: node.ghost ? .38 : 1 }
        : { color: dark ? "#1e3a5c" : "#dceafa", borderColor: base, borderWidth: 2, opacity: node.ghost ? .35 : 1 },
      label: { show: true, color: isTable ? (dark ? "#f0efec" : "#ffffff") : css("--ink"),
        fontSize: 8.5, fontWeight: isTable ? 650 : 400,
        position: isTable ? "inside" : "right", distance: isTable ? 0 : 5,
        formatter: isTable ? node.name : node.name.split(".").pop() },
      tooltip: { formatter: function () { return nodeTooltip(node); } } };
  }
  function edgeOption(edge) {
    var color = changeColor(edge.change) || familyColor(edge.relation_type);
    return { id: edge.id, source: edge.source, target: edge.target, value: edge.confidence,
      lineStyle: { color: color, width: edge.structural ? 1 : (edge.change ? 2.6 : 1.7),
        type: dashFor(edge.relation_type, edge.change), opacity: edge.structural ? .52 : .82,
        curveness: edge.source === edge.target ? .3 : .08 },
      label: { show: false },
      emphasis: { lineStyle: { width: 3.5, opacity: 1 }, focus: "adjacency" },
      tooltip: { formatter: function () { return edgeTooltip(edge); } } };
  }
  function buildOption(view) {
    var dark = root.getAttribute("data-theme") === "dark";
    return { backgroundColor: "transparent", animation: false,
      aria: { enabled: true, decal: { show: false }, description: "表链测绘仪关联图谱，可拖拽节点与筛选边" },
      tooltip: { confine: true, backgroundColor: dark ? "#2a2a28" : "#ffffff", borderColor: css("--line"),
        textStyle: { color: css("--ink"), fontSize: 12 } },
      series: [{ type: "graph", layout: "force", roam: true, draggable: true, focusNodeAdjacency: true,
        data: view.nodes.map(nodeOption), links: view.edges.map(edgeOption),
        categories: [{ name: "表" }, { name: "字段" }],
        force: { repulsion: 340, gravity: .08, edgeLength: [90, 180], friction: .55, layoutAnimation: false },
        labelLayout: { hideOverlap: true, moveOverlap: "shiftY" }, left: "7%", right: "7%", top: "7%", bottom: "6%",
        edgeSymbol: ["none", "arrow"], edgeSymbolSize: [0, 6], lineStyle: { color: "source" },
        emphasis: { disabled: false, scale: true, focus: "adjacency", label: { show: true } } }] };
  }
  function nodeTooltip(node) {
    if (node.node_type === "table") {
      return "<b>" + esc(node.name) + "</b><br>表节点 · " + esc(node.row_count) + " 行 · " + esc(node.column_count) + " 字段";
    }
    return "<b>" + esc(node.name) + "</b><br>字段节点 · " + esc(node.dtype) + "<br>基数 " +
      esc(node.cardinality) + " · 非空率 " + esc(node.non_null_ratio);
  }
  function edgeTooltip(edge) {
    if (edge.structural) return esc(edge.source_table) + " 包含 " + esc(edge.target_field);
    var change = edge.change ? " · <b>" + esc(CHANGE_LABELS[edge.change]) + "</b>" : "";
    return "<b>" + esc(edge.source_table + "." + edge.source_field) + "</b> → <b>" +
      esc(edge.target_table + "." + edge.target_field) + "</b><br>" + esc(typeText(edge)) +
      " · 置信度 " + Number(edge.confidence).toFixed(4) + change + "<br>来源 " + esc(sourceText(edge));
  }
  function evidenceTable(edge) {
    var rows = (edge.evidence || []).slice(0, 5).map(function (item) {
      return "<tr><td>" + esc(item.source_value) + "</td><td>" + esc(item.target_value) + "</td></tr>";
    }).join("");
    if (!rows) return '<p class="detail-empty">该规则未提供值域样例，请查看检测依据。</p>';
    return '<table class="evidence-table"><thead><tr><th>源值</th><th>目标值</th></tr></thead><tbody>' + rows + "</tbody></table>";
  }
  function showEdge(id) {
    var edge = edgeIndex[id];
    if (!edge || edge.structural) return;
    var tags = (edge.detection_sources || []).map(function (source) {
      return '<span class="tag">' + esc(source) + "</span>";
    }).join("");
    detailPanel.innerHTML =
      "<h2>关联详情</h2><p>点击边查看可审计的匹配依据。</p>" +
      '<dl class="detail-kv">' +
      "<dt>方向</dt><dd class=\"mono\">" + esc(edge.source_table + "." + edge.source_field) + " → " +
      esc(edge.target_table + "." + edge.target_field) + "</dd>" +
      "<dt>类型</dt><dd>" + esc(typeText(edge)) + "</dd>" +
      "<dt>置信度</dt><dd>" + Number(edge.confidence).toFixed(4) + "</dd>" +
      "<dt>变化</dt><dd>" + esc(edge.change ? CHANGE_LABELS[edge.change] : "未变化 / 未比较") + "</dd>" +
      "<dt>检测来源</dt><dd>" + (tags || "-") + "</dd></dl>" +
      "<h2>匹配证据</h2>" + evidenceTable(edge) +
      '<h2 style="margin-top:14px">计算依据</h2><pre class="details-json">' +
      esc(JSON.stringify(edge.details || {}, null, 2)) + "</pre>" +
      '<h2 style="margin-top:14px">检测记录</h2><pre class="details-json">' +
      esc(JSON.stringify(edge.detections || [], null, 2)) + "</pre>";
  }
  function showNode(id) {
    var node = nodeIndex[id];
    if (!node) return;
    var edges = allEdges().filter(function (edge) {
      return !edge.structural && (edge.source === id || edge.target === id);
    });
    var type = node.node_type === "table" ? "表节点" : "字段节点";
    detailPanel.innerHTML =
      "<h2>节点详情</h2><p>" + esc(type) + "</p>" +
      '<dl class="detail-kv"><dt>名称</dt><dd class="mono">' + esc(node.name) + "</dd>" +
      "<dt>所属表</dt><dd>" + esc(node.table) + "</dd>" +
      (node.node_type === "table"
        ? "<dt>规模</dt><dd>" + esc(node.row_count) + " 行 / " + esc(node.column_count) + " 字段</dd>"
        : "<dt>类型</dt><dd>" + esc(node.dtype) + "</dd><dt>基数</dt><dd>" + esc(node.cardinality) + "</dd>") +
      "<dt>关联边</dt><dd>" + edges.length + "</dd></dl>" +
      '<p class="detail-empty">拖拽节点可调整布局，滚轮缩放，点击关联边查看证据。</p>';
  }
  function updateTable(view) {
    tableBody.innerHTML = view.associations.map(function (edge) {
      return "<tr><td>" + esc(typeText(edge)) + "</td>" +
        '<td class="mono">' + esc(edge.source_table + "." + edge.source_field) + "</td>" +
        '<td class="mono">' + esc(edge.target_table + "." + edge.target_field) + "</td>" +
        '<td class="conf">' + Number(edge.confidence).toFixed(4) + "</td>" +
        "<td>" + esc(sourceText(edge)) + "</td>" +
        "<td>" + esc(edge.change ? CHANGE_LABELS[edge.change] : "-") + "</td></tr>";
    }).join("") || '<tr><td colspan="6">当前筛选条件下没有关联。</td></tr>';
  }
  function updateSummary(view) {
    document.getElementById("visibleEdgeCount").textContent = view.associations.length;
    document.getElementById("visibleNodeCount").textContent = view.nodes.length;
    var removed = view.associations.filter(function (edge) { return edge.change === "removed"; }).length;
    document.getElementById("visibleChangeCount").textContent = view.associations.filter(function (edge) { return edge.change; }).length;
    document.getElementById("removedHint").textContent = removed ? removed + " 条失效" : "";
  }
  function shardNotice() {
    var box = document.getElementById("shardNotice");
    if (!box) return;
    var missing = Object.keys(shardErrors);
    if (!missing.length) { box.hidden = true; box.textContent = ""; return; }
    box.hidden = false;
    box.classList.add("error");
    var offline = typeof location !== "undefined" && location.protocol === "file:";
    box.textContent = (offline
      ? "分片模式无法通过 file:// 直接读取伴生数据。请使用单文件模式导出，或在项目目录运行本地 Web 控制台后打开。缺失："
      : "分片数据缺失：") + missing.map(function (name) {
        return (FAMILY_LABELS[name] || name) + "（" + (shardEntry(name) || {}).file + "）";
      }).join("、") + (offline ? "" : "。已加载的分片仍可查看；请补齐同目录伴生文件后重试。");
    var retry = document.createElement("button");
    retry.type = "button"; retry.className = "ghost-btn"; retry.textContent = "重试加载";
    retry.addEventListener("click", function () { requestRender(); });
    box.appendChild(retry);
  }
  function render() {
    if (!started) return;
    var view = visibleView();
    updateSummary(view);
    updateTable(view);
    shardNotice();
    if (!view.nodes.length) {
      chart.style.visibility = "hidden";
      emptyState.classList.add("show");
      return;
    }
    chart.style.visibility = "visible";
    emptyState.classList.remove("show");
    instance.setOption(buildOption(view), { notMerge: true });
  }
  function requestRender() {
    var state = filters();
    started = true;
    var jobs = neededFamilies(state).map(loadShard);
    return Promise.all(jobs).then(function () { edgePool = null; render(); });
  }
  function fillTableFilter() {
    var select = document.getElementById("tableFilter");
    Array.from(new Set((GRAPH.nodes || []).filter(function (node) {
      return node.node_type === "table";
    }).map(function (node) { return node.name; }))).sort().forEach(function (name) {
      var option = document.createElement("option");
      option.value = name; option.textContent = name; select.appendChild(option);
    });
  }
  function initDiff() {
    var select = document.getElementById("changeFilter");
    if (!DIFF) {
      select.disabled = true;
      document.getElementById("diffSummary").textContent = "本次未执行增量对比";
      return;
    }
    var summary = DIFF.summary || {};
    document.getElementById("diffSummary").innerHTML =
      '<span class="change-pill added">新增 ' + esc(summary.added || 0) + "</span>" +
      '<span class="change-pill removed">失效 ' + esc(summary.removed || 0) + "</span>" +
      '<span class="change-pill changed">变化 ' + esc(summary.confidence_changed || 0) + "</span>";
  }
  function setTheme(theme) {
    root.setAttribute("data-theme", theme);
    document.getElementById("themeToggle").textContent = theme === "dark" ? "浅色模式" : "深色模式";
    if (instance) render();
  }
  function boot() {
    instance = echarts.init(chart, null, { renderer: "canvas" });
    fillTableFilter();
    initDiff();
    setTheme(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.querySelectorAll("[data-filter]").forEach(function (control) {
      control.addEventListener("input", requestRender);
      control.addEventListener("change", requestRender);
    });
    document.getElementById("confidenceRange").addEventListener("input", function (event) {
      document.getElementById("confidenceOutput").textContent = Number(event.target.value).toFixed(2);
      requestRender();
    });
    document.getElementById("resetFilters").addEventListener("click", function () {
      document.querySelectorAll("[data-relation]").forEach(function (box) { box.checked = true; });
      document.getElementById("confidenceRange").value = "0";
      document.getElementById("confidenceOutput").textContent = "0.00";
      document.getElementById("tableFilter").value = "";
      document.getElementById("changeFilter").value = "all";
      document.getElementById("structuralToggle").checked = true;
      requestRender();
    });
    document.getElementById("themeToggle").addEventListener("click", function () {
      setTheme(root.getAttribute("data-theme") === "dark" ? "light" : "dark");
    });
    instance.on("click", function (params) {
      if (params.dataType === "edge") showEdge(params.data.id);
      if (params.dataType === "node") showNode(params.data.id);
    });
    window.addEventListener("resize", function () { if (instance) instance.resize(); });
    requestRender();
  }
  boot();
})();
