"""
example_knapsack.py — 0/1 Knapsack DP for DSA Visualizer Engine

Tracks the full DP table as a grid (heatmap) with per-cell highlights:
  current  — cell being computed right now         (magenta)
  visited  — dependency cells read for transition  (cyan)
  path     — optimal solution cell (final step)    (green)

dp[i][c] = max value using first i items with capacity c
Transition:
  if c >= w:  dp[i][c] = max(dp[i-1][c],  dp[i-1][c-w] + v)
  else:       dp[i][c] = dp[i-1][c]
"""
from __future__ import annotations

from typing import List, Tuple

from tracker import StateTracker


def knapsack(
    items: List[Tuple[int, int]],
    capacity: int,
    tracker: StateTracker,
) -> int:
    """
    0/1 Knapsack bottom-up DP. Returns optimal value.
    One snapshot per cell for full step-by-step replay.
    """
    n = len(items)
    dp: List[List[int]] = [[0] * (capacity + 1) for _ in range(n + 1)]

    item_labels = [
        f"item {i}: w={items[i-1][0]} v={items[i-1][1]}"
        for i in range(1, n + 1)
    ]

    tracker.watch(dp=dp)
    tracker.set_meta(
        items=items,
        capacity=capacity,
        note="dp[i][c] = max value, first i items, capacity c",
    )
    tracker.snapshot("Init DP table — all zeros (0 items, base case)")

    for i in range(1, n + 1):
        w, v = items[i - 1]

        for c in range(capacity + 1):
            deps = [(i - 1, c)]
            if c >= w:
                deps.append((i - 1, c - w))

            # Transition
            dp[i][c] = dp[i - 1][c]
            took = False
            if c >= w and dp[i - 1][c - w] + v > dp[i][c]:
                dp[i][c] = dp[i - 1][c - w] + v
                took = True

            tracker.highlight(dp={"current": [(i, c)], "visited": deps})
            tracker.set_meta(
                item=item_labels[i - 1],
                capacity_c=c,
                took_item=took,
                dp_value=dp[i][c],
            )
            tracker.snapshot(
                f"dp[{i}][{c}]={dp[i][c]}  "
                f"({'TAKE' if took else 'skip'})  "
                f"[{item_labels[i-1]}]"
            )

    # ── Optimal cell ──────────────────────────────────────────────────────────
    tracker.highlight(dp={"path": [(n, capacity)]})
    tracker.set_meta(optimal_value=dp[n][capacity])
    tracker.snapshot(f"Done — max value={dp[n][capacity]}  at dp[{n}][{capacity}]")

    return dp[n][capacity]


def run(
    items: List[Tuple[int, int]],
    capacity: int,
    tracker: StateTracker,
) -> None:
    """Entry point called by app.py."""
    knapsack(items, capacity, tracker)


if __name__ == "__main__":
    demo_items = [(2, 3), (3, 4), (4, 5), (5, 6)]
    demo_cap   = 8
    with StateTracker() as t:
        result = knapsack(demo_items, demo_cap, t)
    print(f"Items   : {demo_items}")
    print(f"Capacity: {demo_cap}")
    print(f"Optimal : {result}")
    print(f"Snapshots: {len(t)}")
    for s in t.snapshots[:5]:
        print(f"  [{s.step:02d}] {s.label}")
    print("  ...")
