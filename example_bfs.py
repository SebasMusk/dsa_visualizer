"""
example_bfs.py — BFS traversal demo for DSA Visualizer Engine

Shows how to instrument a pure algorithm with StateTracker without
altering its core logic. The run() function is the entry point called
by app.py; the module also works standalone for CLI testing.

Algorithm: Breadth-First Search on a generic directed/undirected graph.
Snapshots are captured at three granularity levels:
  1. Initialization
  2. Dequeue + process node
  3. Discover each new neighbor
"""
from __future__ import annotations

from collections import deque
from typing import Dict, List

from tracker import StateTracker


# ──────────────────────────────────────────────────────────────────────────────
# Pure BFS logic — tracker injection is the only addition
# ──────────────────────────────────────────────────────────────────────────────

def bfs(
    adj: Dict[int, List[int]],
    start: int,
    tracker: StateTracker,
) -> List[int]:
    """
    BFS traversal. Returns nodes in visit order.

    The tracker is injected as a parameter — the algorithm itself remains
    identical to what you would write in a competitive programming contest.
    """
    visited: set = {start}
    queue: deque = deque([start])
    order: List[int] = []

    # Register the graph once; it's referenced until snapshot() deep-copies it
    tracker.watch(graph=adj)

    # ── Step 0: initialization ────────────────────────────────────────────────
    tracker.highlight(graph={"frontier": [start]})
    tracker.set_meta(queue=list(queue), visited=list(visited), order=[])
    tracker.snapshot(f"Init — enqueue start={start}")

    while queue:
        node = queue.popleft()
        order.append(node)

        # ── Step: dequeue and process ─────────────────────────────────────────
        tracker.highlight(graph={
            "current":  [node],
            "frontier": list(queue),
            "visited":  [n for n in visited if n != node and n not in queue],
        })
        tracker.set_meta(
            queue=list(queue),
            visited=list(visited),
            order=order.copy(),
            current_node=node,
        )
        tracker.snapshot(f"Dequeue node={node} → process")

        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

                # ── Step: discover neighbor ───────────────────────────────────
                tracker.highlight(graph={
                    "current":  [node],
                    "frontier": list(queue),
                    "visited":  [n for n in visited
                                 if n not in queue and n != node],
                })
                tracker.set_meta(
                    queue=list(queue),
                    visited=list(visited),
                    order=order.copy(),
                    current_node=node,
                    discovered=neighbor,
                )
                tracker.snapshot(f"Discover {neighbor}  (from {node})")

    # ── Final: traversal complete ─────────────────────────────────────────────
    tracker.highlight(graph={"visited": order})
    tracker.set_meta(queue=[], visited=list(visited), order=order.copy())
    tracker.snapshot(f"Done — BFS order: {order}")

    return order


# ──────────────────────────────────────────────────────────────────────────────
# Entry point called by app.py
# ──────────────────────────────────────────────────────────────────────────────

def run(
    adj: Dict[int, List[int]],
    start: int,
    tracker: StateTracker,
) -> None:
    """Called by app.py after parsing user input."""
    bfs(adj, start, tracker)


# ──────────────────────────────────────────────────────────────────────────────
# Standalone CLI demo
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Default demo graph (tree):
    #       0
    #      / \
    #     1   2
    #    / \   \
    #   3   4   5
    demo_graph: Dict[int, List[int]] = {
        0: [1, 2],
        1: [3, 4],
        2: [5],
        3: [],
        4: [],
        5: [],
    }

    with StateTracker() as t:
        result = bfs(demo_graph, start=0, tracker=t)

    print(f"BFS order : {result}")
    print(f"Snapshots : {len(t)}")
    print()
    for snap in t.snapshots:
        print(f"  [{snap.step:02d}] {snap.label}")
        print(f"        meta : {snap.metadata}")
        print(f"        hl   : {snap.highlights.get('graph', {})}")
