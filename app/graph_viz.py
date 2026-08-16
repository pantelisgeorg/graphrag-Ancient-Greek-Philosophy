"""Knowledge-graph visualization: Cytoscape.js inline view."""
from __future__ import annotations

import colorsys
import json
import urllib.request
from pathlib import Path

import pandas as pd

from .paths import app_config_dir
from .project import GraphRAGProject


# ---------------- JS asset cache ----------------

_JS_ASSETS: tuple[tuple[str, str], ...] = (
    ("cytoscape.min.js",      "https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js"),
    ("layout-base.js",        "https://unpkg.com/layout-base/layout-base.js"),
    ("cose-base.js",          "https://unpkg.com/cose-base/cose-base.js"),
    ("cytoscape-fcose.js",    "https://unpkg.com/cytoscape-fcose/cytoscape-fcose.js"),
)


def _js_cache_dir() -> Path:
    d = app_config_dir() / "js"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_cached_js() -> str:
    """Return all JS asset contents concatenated, downloading them on first call."""
    cache = _js_cache_dir()
    bundle: list[str] = []
    for name, url in _JS_ASSETS:
        path = cache / name
        if not path.exists() or path.stat().st_size < 1000:
            with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
                path.write_bytes(resp.read())
        bundle.append(f"/* {name} */\n" + path.read_text(encoding="utf-8"))
    return "\n".join(bundle)


# ---------------- helpers ----------------

def _as_list(value) -> list:
    """Normalize array/list/None to a plain Python list."""
    if value is None:
        return []
    if hasattr(value, "tolist"):
        return list(value.tolist())
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _palette(n: int) -> list[str]:
    out: list[str] = []
    for i in range(max(n, 1)):
        h = (i * 0.61803398875) % 1.0
        r, g, b = colorsys.hls_to_rgb(h, 0.58, 0.62)
        out.append("#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255)))
    return out


def _entity_community_map(communities: pd.DataFrame, level: int) -> dict[str, int]:
    """Map entity title → community id at the requested level (or nearest available)."""
    if communities.empty:
        return {}
    levels = sorted(communities["level"].unique().tolist())
    if level in levels:
        chosen = level
    else:
        below = [l for l in levels if l <= level]
        chosen = max(below) if below else min(levels)
    sub = communities[communities["level"] == chosen]
    mapping: dict[str, int] = {}
    for _, row in sub.iterrows():
        comm_id = int(row["community"])
        for eid in _as_list(row.get("entity_ids")):
            mapping[str(eid)] = comm_id
    return mapping


def _truncate(s: str, n: int) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------- Cytoscape.js builder ----------------

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>GraphRAG · Knowledge Graph</title>
<script>__BUNDLED_JS__</script>
<style>
  html, body { margin: 0; height: 100%; background: #0f1216; color: #e6e6e6;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
  #root { display: flex; height: 100vh; }
  #sidebar, #details {
    width: 260px; padding: 10px 12px; box-sizing: border-box; background: #161a20;
    overflow: auto; font-size: 12px; }
  #sidebar { border-right: 1px solid #232830; }
  #details { width: 320px; border-left: 1px solid #232830; }
  #cy { flex: 1; background: #0f1216; }
  h3 { font-size: 11px; text-transform: uppercase; letter-spacing: .8px;
    color: #7c8a9c; margin: 14px 0 6px; }
  input[type=text], select {
    width: 100%; box-sizing: border-box;
    background: #22272e; color: #e6e6e6; border: 1px solid #2f3640;
    padding: 5px 8px; border-radius: 4px; font-size: 12px; }
  input[type=range] { width: 100%; }
  .row { display: flex; align-items: center; gap: 6px; margin: 4px 0; }
  .legend-row {
    display: flex; align-items: center; gap: 6px; margin: 2px 0;
    cursor: pointer; padding: 2px 4px; border-radius: 3px; user-select: none; }
  .legend-row:hover { background: #1c2026; }
  .legend-row.off { opacity: 0.35; }
  .swatch { width: 12px; height: 12px; border-radius: 50%; flex: 0 0 12px;
    box-shadow: 0 0 0 1px #0007 inset; }
  .stat { color: #6c7a8c; margin-top: 10px; }
  #details a { color: #6fb1ff; cursor: pointer; }
  #details ul { padding-left: 14px; margin: 6px 0; }
  #details p { color: #c5cdd6; font-size: 11.5px; line-height: 1.45; }
  .pill { display: inline-block; padding: 1px 6px; background: #22272e;
    border-radius: 8px; color: #aab; margin-right: 4px; font-size: 10.5px; }
  .empty-hint { color: #6c7a8c; font-size: 11.5px; }
</style>
</head>
<body>
<div id="root">
  <div id="sidebar">
    <h3>Search</h3>
    <input id="search" type="text" placeholder="filter nodes by name…" autocomplete="off" />

    <h3>Layout</h3>
    <select id="layout">
      <option value="fcose">fcose (force, recommended)</option>
      <option value="concentric">concentric (by degree)</option>
      <option value="circle">circle</option>
      <option value="breadthfirst">breadthfirst (from selection)</option>
      <option value="grid">grid</option>
    </select>

    <h3>Min degree</h3>
    <div class="row"><input id="minDeg" type="range" min="0" max="MAXDEG_PLACEHOLDER" value="0" /><span id="minDegV">0</span></div>

    <h3>Edge labels</h3>
    <div class="row"><input id="edgeLabels" type="checkbox" /> <label for="edgeLabels" style="color:#aab">show on hover</label></div>

    <h3>Communities <span style="color:#6c7a8c">(click to hide)</span></h3>
    <div id="communities"></div>

    <div class="stat" id="stat"></div>
  </div>

  <div id="cy"></div>

  <div id="details">
    <h3>Selection</h3>
    <div id="selection" class="empty-hint">Click a node or edge to inspect.</div>
  </div>
</div>

<script>
const DATA = __DATA__;
const COLORS = __COLORS__;

const elements = [];
DATA.nodes.forEach(n => elements.push({ data: n }));
DATA.edges.forEach(e => elements.push({ data: e }));

const cy = cytoscape({
  container: document.getElementById('cy'),
  elements,
  wheelSensitivity: 0.25,
  style: [
    { selector: 'node',
      style: {
        'background-color': ele => COLORS[ele.data('community')] || '#9aa3ad',
        'label': 'data(label)',
        'color': '#cfd6de',
        'font-size': 9,
        'text-valign': 'center',
        'text-halign': 'right',
        'text-margin-x': 4,
        'text-outline-color': '#0f1216',
        'text-outline-width': 1.4,
        'width':  ele => 8 + Math.min(ele.data('degree') || 1, 40) * 1.4,
        'height': ele => 8 + Math.min(ele.data('degree') || 1, 40) * 1.4,
        'border-width': 0.5,
        'border-color': '#0a0c10',
      }
    },
    { selector: 'edge',
      style: {
        'width': ele => 0.5 + Math.min((ele.data('weight') || 1) / 2, 6),
        'line-color': '#3a4150',
        'curve-style': 'bezier',
        'font-size': 8,
        'color': '#8a939c',
        'text-rotation': 'autorotate',
        'text-background-color': '#0f1216',
        'text-background-opacity': 0.8,
      }
    },
    { selector: '.dim',       style: { 'opacity': 0.08 } },
    { selector: '.highlight', style: { 'border-width': 2.5, 'border-color': '#ff9a4d' } },
    { selector: 'edge.show-edge-label', style: { 'label': 'data(label)' } },
    { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#6fb1ff' } },
  ],
});

function runLayout(name) {
  let opts;
  if (name === 'fcose') {
    opts = { name: 'fcose', quality: 'default', randomize: false, animate: false,
             nodeRepulsion: 8000, idealEdgeLength: 90, nodeSeparation: 50 };
  } else if (name === 'concentric') {
    opts = { name: 'concentric', concentric: n => n.data('degree') || 0,
             levelWidth: () => 1, minNodeSpacing: 24 };
  } else if (name === 'breadthfirst') {
    const sel = cy.$(':selected').first();
    opts = { name: 'breadthfirst', roots: sel.length ? [sel.id()] : undefined, directed: false, spacingFactor: 1.4 };
  } else {
    opts = { name };
  }
  cy.layout(opts).run();
}

document.getElementById('layout').addEventListener('change', e => runLayout(e.target.value));

document.getElementById('edgeLabels').addEventListener('change', e => {
  if (e.target.checked) cy.edges().addClass('show-edge-label');
  else cy.edges().removeClass('show-edge-label');
});

const minDegInput = document.getElementById('minDeg');
const minDegV = document.getElementById('minDegV');
minDegInput.addEventListener('input', () => {
  const v = parseInt(minDegInput.value, 10);
  minDegV.textContent = v;
  cy.batch(() => {
    cy.nodes().forEach(n => {
      if ((n.data('degree') || 0) < v) n.style('display', 'none');
      else if (!hidden.has(Number(n.data('community')))) n.style('display', 'element');
    });
  });
});

const search = document.getElementById('search');
search.addEventListener('input', () => {
  const q = search.value.trim().toLowerCase();
  cy.batch(() => {
    if (!q) {
      cy.elements().removeClass('dim').removeClass('highlight');
      return;
    }
    cy.nodes().forEach(n => {
      const lbl = (n.data('label') || '').toLowerCase();
      const hit = lbl.includes(q);
      n.toggleClass('highlight', hit);
      n.toggleClass('dim', !hit);
    });
    cy.edges().forEach(e => {
      const lit = e.source().hasClass('highlight') || e.target().hasClass('highlight');
      e.toggleClass('dim', !lit);
    });
  });
});

const commContainer = document.getElementById('communities');
const hidden = new Set();
function rebuildVisibility() {
  const v = parseInt(minDegInput.value, 10);
  cy.batch(() => {
    cy.nodes().forEach(n => {
      const tooSmall = (n.data('degree') || 0) < v;
      const inHidden = hidden.has(Number(n.data('community')));
      n.style('display', (tooSmall || inHidden) ? 'none' : 'element');
    });
  });
}
const communityIds = Object.keys(COLORS).map(Number).sort((a, b) => a - b);
communityIds.forEach(cid => {
  const row = document.createElement('div');
  row.className = 'legend-row';
  const sw = document.createElement('span');
  sw.className = 'swatch';
  sw.style.background = COLORS[cid];
  const count = cy.nodes().filter(n => Number(n.data('community')) === cid).length;
  const lbl = document.createElement('span');
  lbl.textContent = (cid >= 0 ? 'C' + cid : 'unknown') + '  (' + count + ')';
  row.appendChild(sw); row.appendChild(lbl);
  row.addEventListener('click', () => {
    if (hidden.has(cid)) { hidden.delete(cid); row.classList.remove('off'); }
    else { hidden.add(cid); row.classList.add('off'); }
    rebuildVisibility();
  });
  commContainer.appendChild(row);
});

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[<>&"]/g,
    c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' })[c]);
}

const detailsEl = document.getElementById('selection');
function renderNode(n) {
  const d = n.data();
  const neighbors = n.connectedEdges().map(e => {
    const other = e.source().id() === n.id() ? e.target() : e.source();
    return { id: other.id(), label: other.data('label'), weight: e.data('weight') || 0 };
  }).sort((a, b) => b.weight - a.weight);
  detailsEl.innerHTML =
    '<div style="font-size:14px"><b>' + escapeHtml(d.label) + '</b></div>'
    + '<div style="margin:4px 0"><span class="pill">' + escapeHtml(d.type || '?') + '</span>'
    + '<span class="pill">deg ' + (d.degree || 0) + '</span>'
    + '<span class="pill">C' + (d.community ?? '?') + '</span></div>'
    + '<p>' + escapeHtml(d.description || '') + '</p>'
    + '<h3>Neighbors (' + neighbors.length + ')</h3>'
    + '<ul>' + neighbors.slice(0, 60).map(nb =>
        '<li><a data-id="' + nb.id + '">' + escapeHtml(nb.label)
        + '</a> <span style="color:#6c7a8c">· ' + nb.weight + '</span></li>').join('')
    + '</ul>';
  detailsEl.querySelectorAll('a[data-id]').forEach(a => a.addEventListener('click', ev => {
    ev.preventDefault();
    const t = cy.getElementById(a.getAttribute('data-id'));
    if (!t.length) return;
    cy.elements().unselect();
    t.select();
    cy.animate({ center: { eles: t }, zoom: Math.max(cy.zoom(), 1.2), duration: 220 });
    renderNode(t);
  }));
}
function renderEdge(e) {
  const d = e.data();
  detailsEl.innerHTML =
    '<div><b>' + escapeHtml(d.source) + '</b> &rarr; <b>' + escapeHtml(d.target) + '</b></div>'
    + '<div style="margin:4px 0"><span class="pill">w ' + (d.weight || '-') + '</span></div>'
    + '<p>' + escapeHtml(d.label || '') + '</p>';
}
cy.on('tap', 'node', e => renderNode(e.target));
cy.on('tap', 'edge', e => renderEdge(e.target));
cy.on('tap', e => {
  if (e.target === cy) detailsEl.innerHTML = '<span class="empty-hint">Click a node or edge to inspect.</span>';
});

document.getElementById('stat').textContent = cy.nodes().length + ' nodes · ' + cy.edges().length + ' edges';
runLayout('fcose');
</script>
</body>
</html>
"""


def build_cytoscape_html(
    project: GraphRAGProject,
    *,
    level: int = 0,
    max_nodes: int = 500,
) -> Path:
    """Build a self-contained Cytoscape.js HTML view of the graph."""
    entities = project.load_parquet("entities")
    relationships = project.load_parquet("relationships")
    communities = project.load_parquet("communities")

    if entities.empty:
        raise RuntimeError("No entities.parquet found — run indexing first.")

    if "degree" in entities.columns and len(entities) > max_nodes:
        entities = entities.sort_values("degree", ascending=False).head(max_nodes)
    keep_titles: set[str] = set(entities["title"].astype(str).tolist())

    comm_map = _entity_community_map(communities, level)
    unique_comms = sorted({comm_map.get(t, -1) for t in keep_titles})
    palette = _palette(len(unique_comms))
    colors = {cid: palette[i] for i, cid in enumerate(unique_comms)}

    nodes: list[dict] = []
    for _, row in entities.iterrows():
        title = str(row["title"])
        nodes.append({
            "id": title,
            "label": title,
            "type": str(row.get("type") or ""),
            "description": _truncate(row.get("description"), 600),
            "degree": int(row.get("degree") or 0),
            "community": int(comm_map.get(title, -1)),
        })

    edges: list[dict] = []
    if not relationships.empty:
        for _, row in relationships.iterrows():
            s = str(row["source"]); t = str(row["target"])
            if s not in keep_titles or t not in keep_titles:
                continue
            edges.append({
                "id": str(row.get("id") or f"{s}__{t}"),
                "source": s,
                "target": t,
                "label": _truncate(row.get("description"), 160),
                "weight": float(row.get("weight") or 1.0),
            })

    max_degree = max((n["degree"] for n in nodes), default=1)
    payload = {"nodes": nodes, "edges": edges}

    bundled_js = _load_cached_js()
    html = (_HTML_TEMPLATE
            .replace("__BUNDLED_JS__", bundled_js)
            .replace("MAXDEG_PLACEHOLDER", str(max(max_degree, 1)))
            .replace("__DATA__", json.dumps(payload))
            .replace("__COLORS__", json.dumps({str(k): v for k, v in colors.items()})))

    out_path = project.graph_html_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
