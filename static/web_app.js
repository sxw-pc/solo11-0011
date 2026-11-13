(function () {
  "use strict";
  var root = document.documentElement;
  var chartNode = document.getElementById("webGraph");
  var empty = document.getElementById("webEmpty");
  var chart = echarts.init(chartNode);
  var state = { graph: null, summary: null };
  var REL_LABEL = { custom: "人工规则", explicit_fk: "原生外键", explicit_naming: "命名匹配", value_overlap: "值域重叠", functional_dependency: "函数依赖", contains: "结构" };

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }
  function css(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function color(type) {
    if (type === "value_overlap") return css("--series-2");
    if (type === "functional_dependency") return css("--series-3");
    if (type === "contains") return css("--muted");
    return css("--series-1");
  }
  function setBusy(busy, message, isError) {
    var button = document.getElementById("runScan");
    var status = document.getElementById("statusLine");
    button.disabled = busy;
    button.textContent = busy ? "扫描中…" : "运行全量扫描";
    if (message) status.textContent = message;
    status.classList.toggle("error", !!isError);
  }
  function notice(message, success) {
    var box = document.getElementById("notice");
    if (!message) { box.hidden = true; return; }
    box.hidden = false;
    box.textContent = message;
    box.classList.toggle("success", !!success);
  }
  async function api(url, options) {
    var response = await fetch(url, options || {});
    var payload = await response.json().catch(function () { return { ok: false, error: "响应不是 JSON" }; });
    if (!response.ok || payload.ok === false) throw new Error(payload.error || "请求失败");
    return payload;
  }
  function renderSummary(summary) {
    document.getElementById("statTables").textContent = summary.tables;
    document.getElementById("statFields").textContent = summary.fields;
    document.getElementById("statAssociations").textContent = summary.associations;
    document.getElementById("statErrors").textContent = summary.load_errors;
    document.getElementById("statDiff").textContent = summary.diff
      ? (summary.diff.added + summary.diff.removed + summary.diff.confidence_changed) : "—";
    var diff = document.getElementById("webDiff");
    if (!summary.diff) diff.innerHTML = '<span class="detail-empty">未提供历史规则，本次无增量对比。</span>';
    else diff.innerHTML = '<div class="diff-list">' +
      '<div class="diff-row"><span>新增</span><b>' + esc(summary.diff.added) + "</b></div>" +
      '<div class="diff-row"><span>失效</span><b>' + esc(summary.diff.removed) + "</b></div>" +
      '<div class="diff-row"><span>置信度变化</span><b>' + esc(summary.diff.confidence_changed) + "</b></div>" +
      '<div class="diff-row"><span>未变化</span><b>' + esc(summary.diff.unchanged) + "</b></div></div>";
    var links = [["rules_json", "规则 JSON"], ["rules_yaml", "规则 YAML"], ["report_md", "Markdown 报告"],
      ["graph_json", "图数据 JSON"], ["graph_html", "单文件图谱"]];
    document.getElementById("downloads").innerHTML = links.map(function (pair) {
      var href = pair[0] === "graph_html" ? "/graph/index.html" : "/files/" + pair[0];
      return '<a href="' + href + '"' + (pair[0] === "graph_html" ? ' target="_blank" rel="noopener"' : "") + ">" + pair[1] + "</a>";
    }).join("");
  }
  function filteredGraph() {
    var min = parseFloat(document.getElementById("webConfidence").value || "0");
    var relation = document.getElementById("webRelation").value;
    var graph = state.graph;
    if (!graph) return null;
    var links = graph.edges.filter(function (edge) {
      if (edge.structural) return false;
      if (edge.confidence < min) return false;
      return relation === "all" || edge.relation_type === relation;
    });
    var fieldIds = {};
    links.forEach(function (edge) { fieldIds[edge.source] = true; fieldIds[edge.target] = true; });
    var tableIds = {};
    links.forEach(function (edge) {
      tableIds["table:" + edge.source_table] = true;
      tableIds["table:" + edge.target_table] = true;
    });
    var nodes = graph.nodes.filter(function (node) {
      return node.node_type === "field" ? fieldIds[node.id] : tableIds[node.id];
    });
    var contains = graph.edges.filter(function (edge) {
      return edge.structural && fieldIds[edge.target] && tableIds[edge.source];
    });
    return { nodes: nodes, links: links.concat(contains), associations: links };
  }
  function graphOption(view) {
    var dark = root.getAttribute("data-theme") === "dark";
    return { backgroundColor: "transparent", animation: false,
      tooltip: { confine: true, backgroundColor: dark ? "#2a2a28" : "#fff", borderColor: css("--line"), textStyle: { color: css("--ink"), fontSize: 12 } },
      series: [{ type: "graph", layout: "force", roam: true, draggable: true,
        data: view.nodes.map(function (node) {
          var table = node.node_type === "table";
          return { id: node.id, name: node.name, category: node.category, draggable: true,
            symbol: table ? "roundRect" : "circle", symbolSize: table ? [Math.max(88, node.name.length * 7.4 + 20), 29] : 13 + Math.min(node.degree || 0, 7),
            itemStyle: table ? { color: dark ? "#c3c2b7" : "#52514e", borderWidth: 2, borderColor: dark ? "#1a1a19" : "#fcfcfb" }
              : { color: dark ? "#1e3a5c" : "#dceafa", borderColor: css("--series-1"), borderWidth: 2 },
            label: { show: true, fontSize: table ? 10 : 9, color: table ? "#fff" : css("--ink"), position: table ? "inside" : "right", distance: 5 } };
        }),
        links: view.links.map(function (edge) {
          return { id: edge.id, source: edge.source, target: edge.target,
            lineStyle: { color: color(edge.relation_type), width: edge.structural ? 1 : 1.6, opacity: edge.structural ? .3 : .8, type: edge.structural ? "dotted" : "solid", curveness: .07 },
            tooltip: { formatter: esc(edge.source_table + "." + edge.source_field) + " → " + esc(edge.target_table + "." + edge.target_field) + "<br>" + esc(REL_LABEL[edge.relation_type] || edge.relation_type) + " · " + Number(edge.confidence).toFixed(4) } };
        }),
        edgeSymbol: ["none", "arrow"], edgeSymbolSize: [0, 5],
        force: { repulsion: 230, gravity: .06, edgeLength: [90, 190], layoutAnimation: false },
        labelLayout: { hideOverlap: true }, left: "4%", right: "4%", top: "8%", bottom: "6%",
        categories: [{ name: "表" }, { name: "字段" }] }] };
  }
  function draw() {
    if (!state.graph) return;
    var view = filteredGraph();
    if (!view.nodes.length) {
      chartNode.style.visibility = "hidden"; empty.classList.add("show"); return;
    }
    chartNode.style.visibility = "visible"; empty.classList.remove("show");
    chart.setOption(graphOption(view), { notMerge: true });
  }
  function showEdge(edge) {
    var evidence = (edge.evidence || []).slice(0, 5).map(function (item) {
      return "<tr><td>" + esc(item.source_value) + "</td><td>" + esc(item.target_value) + "</td></tr>";
    }).join("");
    document.getElementById("webDetailBody").innerHTML =
      "<dl class=\"detail-kv\"><dt>方向</dt><dd class=\"mono\">" + esc(edge.source_table + "." + edge.source_field) + " → " + esc(edge.target_table + "." + edge.target_field) + "</dd>" +
      "<dt>类型</dt><dd>" + esc(REL_LABEL[edge.relation_type] || edge.relation_type) + "</dd>" +
      "<dt>置信度</dt><dd>" + Number(edge.confidence).toFixed(4) + "</dd>" +
      "<dt>来源</dt><dd>" + esc((edge.detection_sources || []).join(", ")) + "</dd></dl>" +
      (evidence ? '<table class="evidence-table"><thead><tr><th>源值</th><th>目标值</th></tr></thead><tbody>' + evidence + "</tbody></table>" : "") +
      '<pre class="details-json">' + esc(JSON.stringify(edge.details || {}, null, 2)) + "</pre>";
  }
  async function scan() {
    setBusy(true, "正在读取本地数据并执行检测…");
    notice("");
    try {
      var payload = await api("/api/scan", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ baseline: document.getElementById("baselinePath").value.trim() || null })
      });
      state.summary = payload.summary;
      renderSummary(payload.summary);
      var graphPayload = await api("/api/graph");
      state.graph = graphPayload.graph;
      draw();
      setBusy(false, "扫描完成，结果已写入本地输出目录");
      notice("扫描完成：" + payload.summary.tables + " 张表，" + payload.summary.associations + " 条去重关联。", true);
    } catch (error) {
      setBusy(false, "扫描失败", true);
      notice(error.message);
    }
  }
  document.getElementById("runScan").addEventListener("click", scan);
  document.getElementById("reloadConfig").addEventListener("click", async function () {
    try {
      await api("/api/config/reload", { method: "POST" });
      notice("配置已热加载，下一次扫描使用新参数。", true);
    } catch (error) { notice(error.message); }
  });
  document.getElementById("themeToggle").addEventListener("click", function () {
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    this.textContent = next === "dark" ? "浅色模式" : "深色模式";
    draw();
  });
  document.getElementById("webConfidence").addEventListener("input", function (event) {
    document.getElementById("webConfidenceOutput").textContent = Number(event.target.value).toFixed(2);
    draw();
  });
  document.getElementById("webRelation").addEventListener("change", draw);
  chart.on("click", function (params) {
    if (params.dataType === "edge" && params.data && params.data.id && state.graph) {
      var edge = state.graph.edges.find(function (item) { return item.id === params.data.id; });
      if (edge) showEdge(edge);
    }
  });
  window.addEventListener("resize", function () { chart.resize(); });
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    root.setAttribute("data-theme", "dark");
    document.getElementById("themeToggle").textContent = "浅色模式";
  }
})();
