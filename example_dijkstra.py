"""
example_dijkstra.py — Dijkstra Shortest Path for DSA Visualizer Engine

Tracks two structures simultaneously:
  graph  : node-colored network (current / visited / frontier)
  dist   : bar chart of current shortest distances (updated / visited)

Input: adj_weighted = {node: [(neighbor, weight), ...]}
"""
from __future__ import annotations

import heapq
from math import inf
from typing import Dict, List, Tuple

from tracker import StateTracker


def dijkstra(
    adj_weighted: Dict[int, List[Tuple[int, int]]],
    start: int,
    tracker: StateTracker,
) -> Dict[int, float]:
    """Dijkstra with full state tracking. Returns {node: shortest_distance}."""
    nodes = sorted(
        set(adj_weighted.keys())
        | {v for nbs in adj_weighted.values() for v, _ in nbs}
    )
    node_idx: Dict[int, int] = {n: i for i, n in enumerate(nodes)}

    adj_display: Dict[int, List[int]] = {
        u: [v for v, _ in nbs] for u, nbs in adj_weighted.items()
    }

    dist: Dict[int, float] = {n: inf for n in nodes}
    dist[start] = 0
    # dist_list is watched by reference; mutate in-place so snapshots capture changes
    dist_list: List[float] = [dist[n] for n in nodes]

    visited: set = set()
    pq: List[Tuple[float, int]] = [(0, start)]

    tracker.watch(graph=adj_display, dist=dist_list)
    tracker.set_meta(pq=list(pq), visited=list(visited), nodes=nodes)
    tracker.snapshot(f"Init — dist[{start}]=0, all others=∞")

    while pq:
        d, u = heapq.heappop(pq)

        if u in visited:
            tracker.highlight(
                graph={"visited": list(visited), "current": [u]},
                dist={"visited": [node_idx[n] for n in visited]},
            )
            tracker.set_meta(pq=list(pq), note=f"skip stale ({d},{u})")
            tracker.snapshot(f"Skip stale entry node={u} d={d}")
            continue

        visited.add(u)
        frontier = [n for _, n in pq if n not in visited]

        # ── Snapshot: processing node ─────────────────────────────────────────
        tracker.highlight(
            graph={
                "current":  [u],
                "visited":  [n for n in visited if n != u],
                "frontier": frontier,
            },
            dist={
                "current": [node_idx[u]],
                "visited": [node_idx[n] for n in visited if n != u],
            },
        )
        tracker.set_meta(
            pq=list(pq), visited=list(visited),
            current_node=u, current_dist=d,
        )
        tracker.snapshot(f"Process node={u}  dist={d}")

        for v, w in adj_weighted.get(u, []):
            if v in visited:
                continue
            new_d = dist[u] + w
            if new_d < dist[v]:
                dist[v] = new_d
                dist_list[node_idx[v]] = new_d      # keep reference in sync
                heapq.heappush(pq, (new_d, v))

                frontier = [n for _, n in pq if n not in visited]
                tracker.highlight(
                    graph={
                        "current":  [u],
                        "frontier": frontier,
                        "visited":  [n for n in visited if n != u],
                    },
                    dist={
                        "updated": [node_idx[v]],
                        "current": [node_idx[u]],
                        "visited": [node_idx[n] for n in visited if n != u],
                    },
                )
                tracker.set_meta(
                    pq=list(pq), visited=list(visited),
                    relaxed=f"{u}→{v}", weight=w, new_dist=new_d,
                )
                tracker.snapshot(f"Relax {u}→{v}  (w={w})  dist[{v}]={new_d}")

    # ── Final ─────────────────────────────────────────────────────────────────
    tracker.highlight(
        graph={"visited": list(visited)},
        dist={"visited": list(range(len(nodes)))},
    )
    tracker.set_meta(
        final={n: (dist[n] if dist[n] != inf else "∞") for n in nodes}
    )
    tracker.snapshot(f"Done — shortest paths from source={start}")
    return dist


def run(
    adj_weighted: Dict[int, List[Tuple[int, int]]],
    start: int,
    tracker: StateTracker,
) -> None:
    dijkstra(adj_weighted, start, tracker)


if __name__ == "__main__":
    demo = {
        0: [(1, 4), (2, 1)],
        1: [(3, 1)],
        2: [(1, 2), (3, 5)],
        3: [],
    }
    with StateTracker() as t:
        result = dijkstra(demo, start=0, tracker=t)
    print("Distances:", {k: (v if v != inf else "∞") for k, v in result.items()})
    print(f"Snapshots: {len(t)}")
    for s in t.snapshots:
        print(f"  [{s.step:02d}] {s.label}")
