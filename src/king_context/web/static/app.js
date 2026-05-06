/* app.js: page interactions for the local UI server.
 *
 * Responsibilities:
 *   - loadAdrPanel(id): fetches /api/adrs/{id} and populates #adr-panel.
 *   - history.pushState integration so /adrs/{id} URLs are bookmarkable.
 *   - popstate listener for browser back/forward.
 *   - kctx:adr-selected listener (dispatched by graph.js).
 *   - data-async="true" link interception inside the ADR list/panel.
 *   - Auto-focus on the search input (when not autofocused by HTML already).
 *
 * No frameworks, no imports. Vanilla JS, runs on DOMContentLoaded.
 */
(function () {
  'use strict';

  function ready(fn) {
    if (document.readyState !== 'loading') {
      fn();
    } else {
      document.addEventListener('DOMContentLoaded', fn);
    }
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function setPanelLoading(panel) {
    panel.innerHTML = '<div class="loading">Loading ADR...</div>';
  }

  function setPanelError(panel, message) {
    panel.innerHTML =
      '<div class="error">Failed to load: ' + escapeHtml(message) + '</div>';
  }

  function buildNeighborhoodSection(label, key, refs) {
    if (!refs || !refs.length) {
      return '';
    }
    var parts = ['<section class="kctx-adr-refs">'];
    parts.push('<h3>' + escapeHtml(label) + '</h3>');
    parts.push('<ul>');
    for (var i = 0; i < refs.length; i++) {
      var ref = refs[i] || {};
      var refId = String(ref.id || '');
      var refTitle = String(ref.title || '');
      var broken = !!ref.broken;
      if (broken) {
        parts.push(
          '<li class="kctx-adr-ref broken-ref">' +
          '<span title="Referenced ADR is missing from the index">' +
          escapeHtml(refId) + ' (broken)</span></li>'
        );
      } else {
        var href = '/adrs/' + encodeURIComponent(refId);
        var labelText = refTitle ? refId + ': ' + refTitle : refId;
        parts.push(
          '<li class="kctx-adr-ref">' +
          '<a href="' + escapeHtml(href) + '" data-async="true" data-id="' +
          escapeHtml(refId) + '">' +
          escapeHtml(labelText) +
          '</a></li>'
        );
      }
    }
    parts.push('</ul></section>');
    return parts.join('');
  }

  function renderPanel(panel, payload) {
    if (payload && payload.reason && !payload.adr) {
      panel.innerHTML =
        '<div class="kctx-empty">' +
        '<p class="kctx-empty-reason">' +
        escapeHtml(payload.reason) +
        '</p>' +
        '<p class="kctx-empty-hint">' +
        escapeHtml(payload.hint || '') +
        '</p>' +
        '</div>';
      return;
    }
    var adr = payload && payload.adr;
    if (!adr) {
      panel.innerHTML =
        '<div class="error">ADR payload missing.</div>';
      return;
    }
    var neighborhood = (payload && payload.neighborhood) || {};
    var areas = adr.areas || [];

    var html = '<article class="kctx-adr-detail">';
    html +=
      '<h2 class="kctx-adr-detail-title">' +
      escapeHtml(adr.id || '') + ': ' +
      escapeHtml(adr.title || '') +
      '</h2>';
    html +=
      '<p class="kctx-adr-detail-meta">' +
      'Status: <strong class="kctx-adr-status status-' +
      escapeHtml(String(adr.status || '').toLowerCase()) + '">' +
      escapeHtml(adr.status || '') +
      '</strong> ' +
      '<span class="kctx-sep">.</span> ' +
      'Date: ' + escapeHtml(adr.date || '') +
      '</p>';
    if (areas.length) {
      var safeAreas = areas.map(function (a) { return escapeHtml(String(a)); });
      html +=
        '<p class="kctx-adr-detail-areas">Areas: ' +
        safeAreas.join(', ') +
        '</p>';
    }
    /* content_html comes pre-rendered from the backend (markdown.markdown),
     * so it is the only field interpolated as raw HTML. All other fields
     * pass through escapeHtml above. */
    html +=
      '<section class="kctx-adr-content">' +
      String(adr.content_html || '') +
      '</section>';

    html += buildNeighborhoodSection('Related', 'related', neighborhood.related);
    html += buildNeighborhoodSection('Supersedes', 'supersedes', neighborhood.supersedes);
    html += buildNeighborhoodSection(
      'Superseded by', 'superseded_by', neighborhood.superseded_by
    );

    html += '</article>';
    panel.innerHTML = html;
  }

  function loadAdrPanel(id, options) {
    var panel = document.getElementById('adr-panel');
    if (!panel) {
      return Promise.resolve();
    }
    var safeId = String(id || '').trim();
    if (!safeId) {
      return Promise.resolve();
    }
    var pushHistory = !options || options.pushHistory !== false;
    setPanelLoading(panel);

    return fetch('/api/adrs/' + encodeURIComponent(safeId), {
      headers: { Accept: 'application/json' },
    })
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error('HTTP ' + resp.status);
        }
        return resp.json();
      })
      .then(function (payload) {
        renderPanel(panel, payload);
        if (pushHistory) {
          var url = '/adrs/' + encodeURIComponent(safeId);
          try {
            history.pushState({ adrId: safeId }, '', url);
          } catch (err) {
            /* ignore: some embedded contexts disallow pushState */
          }
        }
      })
      .catch(function (err) {
        setPanelError(panel, err && err.message ? err.message : 'unknown error');
      });
  }

  function interceptListLinks() {
    document.addEventListener('click', function (ev) {
      var anchor = ev.target;
      while (anchor && anchor !== document.body) {
        if (anchor.tagName === 'A') {
          break;
        }
        anchor = anchor.parentNode;
      }
      if (!anchor || anchor.tagName !== 'A') {
        return;
      }
      if (anchor.getAttribute('data-async') !== 'true') {
        return;
      }
      var id = anchor.getAttribute('data-id') || '';
      if (!id) {
        var href = anchor.getAttribute('href') || '';
        var match = href.match(/\/adrs\/([^?#]+)/);
        if (match) {
          id = decodeURIComponent(match[1]);
        }
      }
      if (!id) {
        return;
      }
      ev.preventDefault();
      loadAdrPanel(id, { pushHistory: true });
    });
  }

  function listenForGraphSelection() {
    document.addEventListener('kctx:adr-selected', function (ev) {
      var id = ev && ev.detail && ev.detail.id;
      if (id) {
        loadAdrPanel(id, { pushHistory: true });
      }
    });
  }

  function listenForPopstate() {
    window.addEventListener('popstate', function (ev) {
      var state = ev.state || {};
      if (state.adrId) {
        loadAdrPanel(state.adrId, { pushHistory: false });
        return;
      }
      var match = window.location.pathname.match(/^\/adrs\/([^/?#]+)/);
      if (match) {
        loadAdrPanel(decodeURIComponent(match[1]), { pushHistory: false });
      }
    });
  }

  function focusSearchInput() {
    if (window.location.pathname !== '/search') {
      return;
    }
    var input = document.querySelector('.kctx-search-form input[name="q"]');
    if (input && document.activeElement !== input) {
      try {
        input.focus({ preventScroll: true });
      } catch (err) {
        input.focus();
      }
    }
  }

  ready(function () {
    interceptListLinks();
    listenForGraphSelection();
    listenForPopstate();
    focusSearchInput();
  });

  /* Expose for easier debugging in the browser devtools. */
  window.kctx = window.kctx || {};
  window.kctx.loadAdrPanel = loadAdrPanel;
})();
