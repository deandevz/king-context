/* graph.js: hand-rolled SVG timeline for the ADR graph.
 *
 * Reads {nodes, edges} from /api/adrs/graph and draws nodes on a horizontal
 * date axis with edges (related = solid Bezier above the line, supersedes =
 * dashed red with arrow). Click on a node dispatches a `kctx:adr-selected`
 * event with the ADR id; app.js handles the panel update.
 *
 * No frameworks, no imports. Single file, runs on DOMContentLoaded.
 */
(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var LANES = 5;
  var MARGIN_LEFT = 60;
  var MARGIN_RIGHT = 40;
  var MARGIN_TOP = 36;
  var MARGIN_BOTTOM = 48;
  var WIDTH = 1600;
  var HEIGHT = 360;
  var NODE_RADIUS = 8;

  function ready(fn) {
    if (document.readyState !== 'loading') {
      fn();
    } else {
      document.addEventListener('DOMContentLoaded', fn);
    }
  }

  function el(name, attrs, children) {
    var node = document.createElementNS(SVG_NS, name);
    if (attrs) {
      for (var key in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, key)) {
          node.setAttribute(key, String(attrs[key]));
        }
      }
    }
    if (children && children.length) {
      for (var i = 0; i < children.length; i++) {
        if (children[i] != null) {
          node.appendChild(children[i]);
        }
      }
    }
    return node;
  }

  function parseDate(value) {
    if (!value) {
      return null;
    }
    var t = Date.parse(String(value));
    return isNaN(t) ? null : t;
  }

  function showHint(svg, hint) {
    if (!svg || !svg.parentNode) {
      return;
    }
    svg.style.display = 'none';
    var existing = svg.parentNode.querySelector('.graph-empty-state');
    if (existing) {
      existing.parentNode.removeChild(existing);
    }
    var div = document.createElement('div');
    div.className = 'graph-empty-state';
    div.textContent = hint || 'ADR graph is not available.';
    svg.parentNode.appendChild(div);
  }

  function showWarning(svg, message) {
    if (!svg || !svg.parentNode) {
      return;
    }
    var existing = svg.parentNode.querySelector('.graph-warning');
    if (existing) {
      existing.parentNode.removeChild(existing);
    }
    var div = document.createElement('div');
    div.className = 'graph-warning';
    div.textContent = message;
    svg.parentNode.insertBefore(div, svg);
  }

  function laneFor(index, lanes) {
    return index % lanes;
  }

  function laneY(lane, totalLanes) {
    var usable = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM;
    if (totalLanes <= 1) {
      return MARGIN_TOP + usable / 2;
    }
    var step = usable / (totalLanes - 1);
    return MARGIN_TOP + lane * step;
  }

  function nodeX(dateMs, minMs, maxMs) {
    var usable = WIDTH - MARGIN_LEFT - MARGIN_RIGHT;
    if (maxMs === minMs) {
      return MARGIN_LEFT + usable / 2;
    }
    var ratio = (dateMs - minMs) / (maxMs - minMs);
    return MARGIN_LEFT + ratio * usable;
  }

  function buildArrowMarker() {
    var marker = el('marker', {
      id: 'arrowhead',
      viewBox: '0 0 10 10',
      refX: 9,
      refY: 5,
      markerWidth: 8,
      markerHeight: 8,
      orient: 'auto-start-reverse',
    });
    var path = el('path', {
      d: 'M0,0 L10,5 L0,10 z',
      fill: '#c33',
    });
    marker.appendChild(path);
    return el('defs', null, [marker]);
  }

  function buildAxis(minMs, maxMs) {
    var axisY = HEIGHT - MARGIN_BOTTOM + 8;
    var line = el('line', {
      x1: MARGIN_LEFT,
      y1: axisY,
      x2: WIDTH - MARGIN_RIGHT,
      y2: axisY,
      class: 'graph-axis',
    });
    var children = [line];

    if (minMs == null || maxMs == null) {
      return el('g', { class: 'graph-axis-group' }, children);
    }

    var minYear = new Date(minMs).getUTCFullYear();
    var maxYear = new Date(maxMs).getUTCFullYear();
    for (var year = minYear; year <= maxYear; year++) {
      var tickMs = Date.UTC(year, 0, 1);
      if (tickMs < minMs || tickMs > maxMs) {
        if (year === minYear || year === maxYear) {
          tickMs = year === minYear ? minMs : maxMs;
        } else {
          continue;
        }
      }
      var tickX = nodeX(tickMs, minMs, maxMs);
      children.push(el('line', {
        x1: tickX,
        y1: axisY,
        x2: tickX,
        y2: axisY + 6,
        class: 'graph-axis-tick',
      }));
      var label = el('text', {
        x: tickX,
        y: axisY + 20,
        class: 'graph-axis-label',
        'text-anchor': 'middle',
      });
      label.textContent = String(year);
      children.push(label);
    }

    return el('g', { class: 'graph-axis-group' }, children);
  }

  function nodeTitle(node) {
    var t = el('title', null, null);
    var parts = [node.id || ''];
    if (node.title) {
      parts.push(node.title);
    }
    if (node.date) {
      parts.push(node.date);
    }
    if (node.status) {
      parts.push('status: ' + node.status);
    }
    t.textContent = parts.join(' . ');
    return t;
  }

  function buildNode(node, x, y) {
    var status = (node.status || 'unknown').toLowerCase();
    var group = el('g', {
      class: 'adr-node-group',
      'data-id': node.id || '',
      tabindex: '0',
      role: 'button',
      'aria-label': (node.id || '') + ': ' + (node.title || ''),
    });
    var circle = el('circle', {
      cx: x,
      cy: y,
      r: NODE_RADIUS,
      class: 'adr-node status-' + status,
    });
    circle.appendChild(nodeTitle(node));
    var label = el('text', {
      x: x + NODE_RADIUS + 4,
      y: y + 4,
      class: 'adr-node-label',
    });
    label.textContent = node.id || '';
    group.appendChild(circle);
    group.appendChild(label);
    return group;
  }

  function buildEdge(edge, fromPos, toPos) {
    var type = (edge.type || 'related').toLowerCase();
    if (type === 'supersedes') {
      var pathD = 'M' + fromPos.x + ',' + fromPos.y +
                  ' L' + toPos.x + ',' + toPos.y;
      return el('path', {
        d: pathD,
        class: 'edge edge-supersedes',
        'marker-end': 'url(#arrowhead)',
      });
    }
    var midX = (fromPos.x + toPos.x) / 2;
    var midY = Math.min(fromPos.y, toPos.y) - 30;
    var d = 'M' + fromPos.x + ',' + fromPos.y +
            ' Q' + midX + ',' + midY +
            ' ' + toPos.x + ',' + toPos.y;
    return el('path', {
      d: d,
      class: 'edge edge-related',
    });
  }

  function dispatchSelected(svg, id) {
    var event;
    try {
      event = new CustomEvent('kctx:adr-selected', {
        detail: { id: id },
        bubbles: true,
      });
    } catch (err) {
      event = document.createEvent('CustomEvent');
      event.initCustomEvent('kctx:adr-selected', true, false, { id: id });
    }
    svg.dispatchEvent(event);
  }

  function attachClickHandlers(svg) {
    svg.addEventListener('click', function (ev) {
      var target = ev.target;
      while (target && target !== svg) {
        if (target.classList && target.classList.contains('adr-node-group')) {
          var id = target.getAttribute('data-id');
          if (id) {
            dispatchSelected(svg, id);
          }
          return;
        }
        target = target.parentNode;
      }
    });
    svg.addEventListener('keydown', function (ev) {
      if (ev.key !== 'Enter' && ev.key !== ' ') {
        return;
      }
      var target = ev.target;
      while (target && target !== svg) {
        if (target.classList && target.classList.contains('adr-node-group')) {
          ev.preventDefault();
          var id = target.getAttribute('data-id');
          if (id) {
            dispatchSelected(svg, id);
          }
          return;
        }
        target = target.parentNode;
      }
    });
  }

  function renderGraph(svg, payload) {
    var nodes = (payload && payload.nodes) || [];
    var edges = (payload && payload.edges) || [];

    if (!nodes.length) {
      var hint = (payload && payload.hint) ||
                 'No ADR nodes to display. Run `kctx adr index` after creating ADRs.';
      showHint(svg, hint);
      return;
    }

    if (nodes.length > 50) {
      showWarning(svg, 'Showing ' + nodes.length + ' ADRs. Layout may be dense.');
    }

    var dated = [];
    for (var i = 0; i < nodes.length; i++) {
      var ms = parseDate(nodes[i].date);
      dated.push({ node: nodes[i], ms: ms });
    }

    var validMs = dated
      .map(function (d) { return d.ms; })
      .filter(function (m) { return m != null; });
    var minMs = validMs.length ? Math.min.apply(null, validMs) : null;
    var maxMs = validMs.length ? Math.max.apply(null, validMs) : null;

    while (svg.firstChild) {
      svg.removeChild(svg.firstChild);
    }
    svg.setAttribute('viewBox', '0 0 ' + WIDTH + ' ' + HEIGHT);
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'ADR timeline graph');
    svg.style.display = '';

    svg.appendChild(buildArrowMarker());
    svg.appendChild(buildAxis(minMs, maxMs));

    var positions = {};
    var laneCount = Math.min(LANES, dated.length);
    for (var n = 0; n < dated.length; n++) {
      var entry = dated[n];
      var x;
      if (entry.ms != null && minMs != null && maxMs != null) {
        x = nodeX(entry.ms, minMs, maxMs);
      } else {
        x = MARGIN_LEFT + (WIDTH - MARGIN_LEFT - MARGIN_RIGHT) / 2;
      }
      var lane = laneFor(n, laneCount);
      var y = laneY(lane, laneCount);
      var nodeId = entry.node.id || '';
      positions[nodeId] = { x: x, y: y };
    }

    var edgesGroup = el('g', { class: 'graph-edges' });
    svg.appendChild(edgesGroup);
    for (var e = 0; e < edges.length; e++) {
      var edge = edges[e];
      var fromPos = positions[edge.from];
      var toPos = positions[edge.to];
      if (!fromPos || !toPos) {
        continue;
      }
      edgesGroup.appendChild(buildEdge(edge, fromPos, toPos));
    }

    var nodesGroup = el('g', { class: 'graph-nodes' });
    svg.appendChild(nodesGroup);
    for (var k = 0; k < dated.length; k++) {
      var node = dated[k].node;
      var pos = positions[node.id || ''];
      if (!pos) {
        continue;
      }
      nodesGroup.appendChild(buildNode(node, pos.x, pos.y));
    }

    attachClickHandlers(svg);
  }

  function loadGraph() {
    var svg = document.getElementById('adr-graph');
    if (!svg) {
      return;
    }
    fetch('/api/adrs/graph', { headers: { Accept: 'application/json' } })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error('HTTP ' + resp.status);
        }
        return resp.json();
      })
      .then(function (payload) {
        if (!payload || (payload.items && !payload.nodes)) {
          showHint(svg, (payload && payload.hint) ||
                       'ADR graph not available yet.');
          return;
        }
        renderGraph(svg, payload);
      })
      .catch(function () {
        showHint(svg, 'Failed to load ADR graph. Run `kctx adr index` to regenerate.');
      });
  }

  ready(loadGraph);
})();
