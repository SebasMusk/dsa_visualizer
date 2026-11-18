"""
visualizer.py — Rendering layer for DSA Visualizer Engine

Converts StateTracker Snapshots into Plotly figures.
Auto-detects structure type (array / grid / graph / scalar) and routes
to the appropriate renderer. All figures share the same dark-neon theme.

Public API:
    detect_type(value)           → "graph" | "grid" | "array" | "scalar"
    render_array(arr, hl, title) → go.Figure
    render_grid(grid, hl, title) → go.Figure
    render_graph(adj, hl, title) → go.Figure
    render_legend()              → go.Figure  (compact color legend)
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import plotly.graph_objects as go

try:
    import networkx as nx
    _HAS_NX = True
except ImportError:
    _HAS_NX = False


# ──────────────────────────────────────────────────────────────────────────────
# Theme — dark background + neon accent palette
# ──────────────────────────────────────────────────────────────────────────────

COLORS: Dict[str, str] = {
    "bg":       "#0d1117",
    "bg2":      "#161b22",
    "text":     "#e6edf3",
    "grid_ln":  "#21262d",
    "default":  "#2a2d3e",
    "inactive": "#3d4450",
    # Semantic roles (match tracker.highlight role keys)
    "visited":  "#00d4ff",   # cyan   — fully processed
    "frontier": "#ff6b35",   # orange — in queue / open-set
    "current":  "#ff0090",   # magenta — active right now
    "path":     "#39ff14",   # green  — answer path
    "updated":  "#ffff00",   # yellow — just written
}

# Priority: roles listed later override earlier ones on the same element
_ROLE_PRIORITY = ["path", "visited", "frontier", "updated", "current"]

_DARK_LAYOUT = dict(
    paper_bgcolor=COLORS["bg"],
    plot_bgcolor=COLORS["bg"],
    font=dict(color=COLORS["text"], family="JetBrains Mono, monospace", size=13),
    margin=dict(l=24, r=24, t=44, b=24),
)


# ──────────────────────────────────────────────────────────────────────────────
# Type detection
# ──────────────────────────────────────────────────────────────────────────────

def detect_type(value: Any) -> str:
    """Return one of: 'graph', 'grid', 'array', 'scalar'."""
    if isinstance(value, dict):
        if all(isinstance(v, (list, set, tuple)) for v in value.values()):
            return "graph"
    if isinstance(value, (list, tuple)):
        if value and isinstance(value[0], (list, tuple)):
            return "grid"
        return "array"
    return "scalar"


# ──────────────────────────────────────────────────────────────────────────────
# Array renderer — neon bar chart
# ──────────────────────────────────────────────────────────────────────────────

def render_array(
    arr: List[Any],
    highlights: Optional[Dict[str, List[int]]] = None,
    title: str = "Array",
) -> go.Figure:
    """
    Bar chart. highlights maps role → list of integer indices.
        render_array(arr, {"current": [i], "visited": [0, 1, 2]})
    """
    hl = highlights or {}
    n = len(arr)

    colors = [COLORS["default"]] * n
    for role in _ROLE_PRIORITY:
        for idx in hl.get(role, []):
            if 0 <= idx < n:
                colors[idx] = COLORS[role]

    _inf = float('inf')
    numeric = [
        0 if (isinstance(v, float) and abs(v) == _inf) else
        v if isinstance(v, (int, float)) else 1
        for v in arr
    ]
    labels = ["∞" if v == _inf else "-∞" if v == float('-inf') else str(v) for v in arr]

    fig = go.Figure(go.Bar(
        x=list(range(n)),
        y=numeric,
        text=labels,
        textposition="outside",
        textfont=dict(color=COLORS["text"], size=12),
        marker=dict(color=colors, line=dict(color=COLORS["bg"], width=1)),
        hovertemplate="index=%{x}<br>value=%{text}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(color=COLORS["visited"], size=16)),
        xaxis=dict(tickvals=list(range(n)), gridcolor=COLORS["grid_ln"], zeroline=False),
        yaxis=dict(gridcolor=COLORS["grid_ln"], zeroline=False),
        **_DARK_LAYOUT,
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# Grid renderer — annotated heatmap with discrete role colors
# ──────────────────────────────────────────────────────────────────────────────

def render_grid(
    grid: List[List[Any]],
    highlights: Optional[Dict[str, List[Tuple[int, int]]]] = None,
    title: str = "Grid / DP Table",
) -> go.Figure:
    """
    Annotated heatmap. highlights maps role → list of (row, col) tuples.
        render_grid(dp, {"current": [(i, j)], "updated": [(i, j-1)]})
    """
    hl = highlights or {}
    rows = len(grid)
    cols = max((len(r) for r in grid), default=0)

    role_idx = {r: i + 1 for i, r in enumerate(_ROLE_PRIORITY)}
    z = [[0] * cols for _ in range(rows)]
    for role, r_idx in role_idx.items():
        for cell in hl.get(role, []):
            if isinstance(cell, (list, tuple)) and len(cell) == 2:
                rr, cc = int(cell[0]), int(cell[1])
                if 0 <= rr < rows and 0 <= cc < cols:
                    z[rr][cc] = r_idx

    def _fmt(v: Any) -> str:
        if v == float("inf"):  return "∞"
        if isinstance(v, float) and v == int(v): return str(int(v))
        return str(v)

    text_mat = [[_fmt(grid[r][c]) for c in range(cols)] for r in range(rows)]

    n_levels = len(_ROLE_PRIORITY) + 1
    palette  = ["default"] + _ROLE_PRIORITY
    colorscale = []
    for i, role in enumerate(palette):
        lo, hi = i / n_levels, (i + 1) / n_levels
        colorscale += [[lo, COLORS[role]], [hi, COLORS[role]]]

    fig = go.Figure(go.Heatmap(
        z=z,
        text=text_mat,
        texttemplate="%{text}",
        textfont=dict(size=13, color=COLORS["text"]),
        colorscale=colorscale,
        zmin=0, zmax=n_levels,
        showscale=False,
        hovertemplate="row=%{y}, col=%{x}<br>val=%{text}<extra></extra>",
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(color=COLORS["visited"], size=16)),
        xaxis=dict(side="top", gridcolor=COLORS["grid_ln"], zeroline=False),
        yaxis=dict(autorange="reversed", gridcolor=COLORS["grid_ln"], zeroline=False),
        **_DARK_LAYOUT,
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# Graph renderer — Plotly network graph
# ──────────────────────────────────────────────────────────────────────────────

def _all_nodes(adj: Dict) -> List[Any]:
    nodes = set(adj.keys())
    for nbs in adj.values():
        nodes.update(nbs)
    try:
        return sorted(nodes)
    except TypeError:
        return list(nodes)


def _is_tree(adj: Dict) -> bool:
    nodes = _all_nodes(adj)
    total_edges = sum(len(v) for v in adj.values())
    return len(nodes) > 0 and total_edges == len(nodes) - 1


def _bfs_tree_layout(adj: Dict, root: Any) -> Dict[Any, Tuple[float, float]]:
    levels: Dict[Any, int] = {root: 0}
    level_nodes: Dict[int, List] = {0: [root]}
    q: deque = deque([root])
    while q:
        node = q.popleft()
        for nb in adj.get(node, []):
            if nb not in levels:
                d = levels[node] + 1
                levels[nb] = d
                level_nodes.setdefault(d, []).append(nb)
                q.append(nb)
    pos: Dict[Any, Tuple[float, float]] = {}
    for depth, dnodes in level_nodes.items():
        for i, node in enumerate(dnodes):
            pos[node] = ((i - (len(dnodes) - 1) / 2) * 2.5, -depth * 2.0)
    return pos


def _circular_layout(adj: Dict) -> Dict[Any, Tuple[float, float]]:
    nodes = _all_nodes(adj)
    n = len(nodes)
    return {
        node: (math.cos(2 * math.pi * i / max(n, 1)),
               math.sin(2 * math.pi * i / max(n, 1)))
        for i, node in enumerate(nodes)
    }


def render_graph(
    adj: Dict[Any, List[Any]],
    highlights: Optional[Dict[str, List]] = None,
    title: str = "Graph",
    directed: bool = False,
    pos: Optional[Dict] = None,
    edge_labels: Optional[Dict[Tuple[Any, Any], str]] = None,
) -> go.Figure:
    """
    Network graph. highlights maps role → list of node ids.
        render_graph(adj, {"current": [u], "frontier": [1,2,3], "visited": [0]})
    """
    hl    = highlights or {}
    nodes = _all_nodes(adj)

    if not nodes:
        fig = go.Figure()
        fig.update_layout(title=title, **_DARK_LAYOUT)
        return fig

    # ── Node positions ────────────────────────────────────────────────────────
    if pos is None:
        if _HAS_NX:
            G = nx.DiGraph() if directed else nx.Graph()
            for u, nbs in adj.items():
                G.add_node(u)
                for v in nbs:
                    G.add_edge(u, v)
            if _is_tree(adj):
                try:
                    if nx.is_tree(G.to_undirected()):
                        pos = _bfs_tree_layout(adj, nodes[0])
                except Exception:
                    pass
            if pos is None:
                pos = nx.spring_layout(G, seed=42, k=2.5)
        else:
            pos = (_bfs_tree_layout(adj, nodes[0]) if _is_tree(adj)
                   else _circular_layout(adj))

    # ── Role → color mapping (higher-priority roles win) ─────────────────────
    node_color: Dict[Any, str] = {}
    for role in _ROLE_PRIORITY:
        for node in hl.get(role, []):
            node_color[node] = COLORS[role]

    # ── Edge traces ───────────────────────────────────────────────────────────
    ex: List[Optional[float]] = []
    ey: List[Optional[float]] = []
    for u, neighbors in adj.items():
        if u not in pos:
            continue
        for v in neighbors:
            if v not in pos:
                continue
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            ex += [x0, x1, None]
            ey += [y0, y1, None]

    edge_trace = go.Scatter(
        x=ex, y=ey,
        mode="lines",
        line=dict(color=COLORS["inactive"], width=2),
        hoverinfo="none",
        showlegend=False,
    )

    # ── Node trace ────────────────────────────────────────────────────────────
    valid = [n for n in nodes if n in pos]
    vx    = [pos[n][0] for n in valid]
    vy    = [pos[n][1] for n in valid]
    vc    = [node_color.get(n, COLORS["default"]) for n in valid]
    vl    = [str(n) for n in valid]

    node_trace = go.Scatter(
        x=vx, y=vy,
        mode="markers+text",
        text=vl,
        textposition="middle center",
        textfont=dict(color="#ffffff", size=14,
                      family="JetBrains Mono, monospace"),
        marker=dict(size=36, color=vc,
                    line=dict(color=COLORS["bg"], width=3)),
        hovertemplate="<b>Node %{text}</b><extra></extra>",
        showlegend=False,
    )

    traces = [edge_trace, node_trace]

    # ── Optional edge weight labels ───────────────────────────────────────────
    if edge_labels and pos:
        elx, ely, elt = [], [], []
        for (u, v), lbl in edge_labels.items():
            if u in pos and v in pos:
                elx.append((pos[u][0] + pos[v][0]) / 2)
                ely.append((pos[u][1] + pos[v][1]) / 2)
                elt.append(str(lbl))
        if elt:
            traces.append(go.Scatter(
                x=elx, y=ely,
                mode="text",
                text=elt,
                textfont=dict(color=COLORS["updated"], size=11,
                              family="JetBrains Mono, monospace"),
                hoverinfo="none",
                showlegend=False,
            ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        title=dict(text=title, font=dict(color=COLORS["visited"], size=16)),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        **_DARK_LAYOUT,
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# Legend figure
# ──────────────────────────────────────────────────────────────────────────────

def render_legend() -> go.Figure:
    """Compact legend showing semantic color roles."""
    items = [
        ("Current",          COLORS["current"]),
        ("Frontier / Queue", COLORS["frontier"]),
        ("Visited",          COLORS["visited"]),
        ("Path / Result",    COLORS["path"]),
        ("Updated",          COLORS["updated"]),
        ("Default",          COLORS["default"]),
    ]
    fig = go.Figure()
    for i, (label, color) in enumerate(items):
        fig.add_trace(go.Scatter(
            x=[0.15], y=[len(items) - i],
            mode="markers+text",
            marker=dict(size=16, color=color,
                        line=dict(color=COLORS["bg2"], width=1)),
            text=[f"  {label}"],
            textposition="middle right",
            textfont=dict(color=COLORS["text"], size=12),
            showlegend=False,
        ))
    fig.update_layout(
        height=190,
        xaxis=dict(range=[-0.1, 4], showgrid=False,
                   showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        **_DARK_LAYOUT,
    )
    return fig
