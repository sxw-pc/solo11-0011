/* 主题域着色与筛选：确定性调色板 + 离线图谱 echarts 拦截增强，无外部资源。
 * 离线页（存在 #graph）：包装 echarts.init，在 setOption 前做域着色/筛选；
 * Web 控制台（存在 #webGraph）：仅暴露 TableLinkDomain 工具，由 web_app.js 直接调用。 */
(function () {
  "use strict";
  var DOMAIN_PALETTE = [
    "#2a78d6", "#1baf7a", "#eb6834", "#8e5bd6", "#d6a02a", "#26a6b8",
    "#c94f8c", "#5b8a2f", "#b35042", "#5f6fe0", "#0f9d8f", "#a86a2d"
  ];
  var BRIDGE_COLOR = "#7a4fd0";
  var UNGROUPED_COLOR = "#9a988f";
  var GRAPH = window.__GRAPH__ || null;

  function esc(value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  var TableLinkDomain = {
    palette: DOMAIN_PALETTE,
    hasDomain: function (graph) { return !!(graph && graph.domain && graph.domain.enabled); },
    orderedDomains: function (graph) {
      return ((graph.domain && graph.domain.domains) || []).slice().sort(function (a, b) {
        return a.domain_id < b.domain_id ? -1 : a.domain_id > b.domain_id ? 1 : 0;
      });
    },
    colorOf: function (node) {
      if (!node) return null;
      if (node.domain_role === "bridge") return BRIDGE_COLOR;
      if (node.domain_role === "ungrouped") return UNGROUPED_COLOR;
      if (!node.domain_id) return null;
      var index = parseInt(String(node.domain_id).replace(/^domain_/, ""), 10);
      return isFinite(index) ? DOMAIN_PALETTE[(index - 1) % DOMAIN_PALETTE.length] : null;
    },
    fillFilter: function (selectId, graph) {
      var select = document.getElementById(selectId);
      if (!select || !this.hasDomain(graph)) { if (select) select.disabled = true; return; }
      this.orderedDomains(graph).forEach(function (domain) {
        var option = document.createElement("option");
        option.value = domain.domain_id;
        option.textContent = domain.domain_id + " · " + domain.name;
        select.appendChild(option);
      });
      var bridges = (graph.domain.bridge_tables || []).length;
      if (bridges) {
        var b = document.createElement("option");
        b.value = "__bridge__"; b.textContent = "跨域桥接表（" + bridges + "）";
        select.appendChild(b);
      }
      if ((graph.domain.ungrouped_tables || []).length) {
        var u = document.createElement("option");
        u.value = "__ungrouped__";
        u.textContent = "未分组表（" + graph.domain.ungrouped_tables.length + "）";
        select.appendChild(u);
      }
      select.disabled = false;
    },
    nodePasses: function (node, value) {
      if (!value || value === "all") return true;
      if (value === "__bridge__") return node.domain_role === "bridge";
      if (value === "__ungrouped__") return node.domain_role === "ungrouped";
      return node.domain_id === value;
    },
    labelOf: function (node, graph) {
      if (!this.hasDomain(graph)) return "";
      if (node.domain_role === "bridge") return "跨域桥接表";
      if (node.domain_role === "ungrouped") return "未分组";
      var found = "";
      this.orderedDomains(graph).forEach(function (domain) {
        if (domain.domain_id === node.domain_id) found = domain.name;
      });
      return found ? node.domain_id + " · " + found : node.domain_id || "";
    }
  };
  window.TableLinkDomain = TableLinkDomain;

  function installOfflineEnhancer() {
    var chartNode = document.getElementById("graph");
    if (!chartNode || !TableLinkDomain.hasDomain(GRAPH) || !window.echarts) return;
    var nodeById = {};
    (GRAPH.nodes || []).forEach(function (node) { nodeById[node.id] = node; });
    TableLinkDomain.fillFilter("domainFilter", GRAPH);
    var legend = document.getElementById("domainLegend");
    if (legend) {
      var items = TableLinkDomain.orderedDomains(GRAPH).map(function (domain) {
        return '<span class="legend-item"><span class="swatch node-table" style="background:' +
          esc(TableLinkDomain.colorOf({ domain_id: domain.domain_id })) + '"></span>' +
          esc(domain.domain_id + " " + domain.name) + "</span>";
      });
      if ((GRAPH.domain.bridge_tables || []).length)
        items.push('<span class="legend-item"><span class="swatch node-table" style="background:' + BRIDGE_COLOR + '"></span>跨域桥接表</span>');
      if ((GRAPH.domain.ungrouped_tables || []).length)
        items.push('<span class="legend-item"><span class="swatch node-table" style="background:' + UNGROUPED_COLOR + '"></span>未分组</span>');
      legend.innerHTML = items.join("");
    }
    function currentFilter() {
      var control = document.getElementById("domainFilter");
      return control ? control.value : "all";
    }
    function applyDomain(option) {
      var series = option && option.series && option.series[0];
      if (!series || !series.data) return option;
      var filter = currentFilter();
      series.data.forEach(function (item) {
        var node = nodeById[item.id];
        if (!node || node.node_type !== "table") return;
        var color = TableLinkDomain.colorOf(node);
        if (color) {
          item.itemStyle = item.itemStyle || {};
          item.itemStyle.color = color;
          if (node.domain_role === "bridge") item.itemStyle.borderType = "dashed";
        }
      });
      series.data.forEach(function (item) {
        var node = nodeById[item.id];
        if (!node || node.node_type !== "field") return;
        var tableNode = nodeById["table:" + node.table];
        var color = tableNode && TableLinkDomain.colorOf(tableNode);
        if (color) {
          item.itemStyle = item.itemStyle || {};
          item.itemStyle.borderColor = color;
        }
      });
      if (filter === "all") return option;
      var allowedTables = {};
      (GRAPH.nodes || []).forEach(function (node) {
        if (node.node_type === "table" && TableLinkDomain.nodePasses(node, filter))
          allowedTables[node.id] = true;
      });
      series.links = (series.links || []).filter(function (link) {
        var source = nodeById[link.source];
        var target = nodeById[link.target];
        var sourceTable = link.source_table ? "table:" + link.source_table
          : source && source.node_type === "table" ? link.source : "table:" + (source && source.table);
        var targetTable = link.target_table ? "table:" + link.target_table
          : target && target.node_type === "table" ? link.target : "table:" + (target && target.table);
        return allowedTables[sourceTable] && allowedTables[targetTable];
      });
      var keptIds = {};
      series.links.forEach(function (link) { keptIds[link.source] = true; keptIds[link.target] = true; });
      series.data = series.data.filter(function (item) {
        var node = nodeById[item.id];
        if (node && node.node_type === "table") return allowedTables[item.id];
        return keptIds[item.id];
      });
      var empty = document.getElementById("emptyState");
      if (empty) empty.classList.toggle("show", series.data.length === 0);
      return option;
    }
    var originalInit = window.echarts.init;
    window.echarts.init = function () {
      var real = originalInit.apply(this, arguments);
      return new Proxy(real, {
        get: function (target, prop) {
          var value = target[prop];
          if (typeof value !== "function") return value;
          if (prop === "setOption") {
            return function (option, flag) {
              applyDomain(option);
              return value.call(target, option, flag);
            };
          }
          return value.bind(target);
        }
      });
    };
    var domainControl = document.getElementById("domainFilter");
    function triggerRender() {
      var tableFilter = document.getElementById("tableFilter");
      if (tableFilter) tableFilter.dispatchEvent(new Event("change", { bubbles: true }));
    }
    if (domainControl) domainControl.addEventListener("change", triggerRender);
    var reset = document.getElementById("resetFilters");
    if (reset) reset.addEventListener("click", function () {
      if (domainControl) domainControl.value = "all";
    });
  }
  // 本脚本在 graph_app.js 之前同步加载，需立即安装 echarts 包装，不能等待 DOMContentLoaded
  installOfflineEnhancer();
})();
