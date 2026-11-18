"""
example_mergesort.py — Merge Sort for DSA Visualizer Engine

Tracks the array in-place across four snapshot types:
  Divide   — split point on the current subrange   (frontier + current)
  Compare  — two elements being compared            (current × 2)
  Place    — element written to sorted position     (updated)
  Merged   — subarray fully sorted                  (visited)
"""
from __future__ import annotations

from typing import List

from tracker import StateTracker


def merge_sort(
    arr: List[int],
    tracker: StateTracker,
    lo: int = 0,
    hi: int = -1,
) -> None:
    """
    Recursive merge sort. arr is mutated in-place.
    tracker.watch stores a reference → each snapshot deep-copies the live state.
    """
    if hi == -1:            # top-level call: register array reference once
        hi = len(arr) - 1
        tracker.watch(array=arr)
        tracker.highlight(array={"frontier": list(range(len(arr)))})
        tracker.set_meta(phase="init", size=len(arr))
        tracker.snapshot("Init — array to sort")

    if lo >= hi:
        return

    mid = (lo + hi) // 2

    # ── Divide ────────────────────────────────────────────────────────────────
    tracker.highlight(array={
        "frontier": list(range(lo, hi + 1)),
        "current":  [mid],
    })
    tracker.set_meta(phase="divide", lo=lo, hi=hi, mid=mid)
    tracker.snapshot(f"Divide [{lo}..{hi}] → [{lo}..{mid}] | [{mid+1}..{hi}]")

    merge_sort(arr, tracker, lo, mid)
    merge_sort(arr, tracker, mid + 1, hi)
    _merge(arr, tracker, lo, mid, hi)


def _merge(
    arr: List[int],
    tracker: StateTracker,
    lo: int,
    mid: int,
    hi: int,
) -> None:
    left  = arr[lo : mid + 1]
    right = arr[mid + 1 : hi + 1]
    i = j = 0
    k = lo

    while i < len(left) and j < len(right):
        li = lo + i
        rj = mid + 1 + j

        # ── Compare ───────────────────────────────────────────────────────────
        tracker.highlight(array={
            "current":  [li, rj],
            "visited":  list(range(lo, k)),
            "frontier": list(range(k, hi + 1)),
        })
        tracker.set_meta(
            phase="compare",
            merge_range=f"[{lo}..{hi}]",
            left=left, right=right,
            comparing=f"{left[i]} vs {right[j]}",
        )
        tracker.snapshot(f"Compare  left[{i}]={left[i]}  vs  right[{j}]={right[j]}")

        if left[i] <= right[j]:
            arr[k] = left[i]; i += 1
        else:
            arr[k] = right[j]; j += 1

        # ── Place ─────────────────────────────────────────────────────────────
        tracker.highlight(array={
            "updated":  [k],
            "visited":  list(range(lo, k)),
            "frontier": list(range(k + 1, hi + 1)),
        })
        tracker.set_meta(phase="place", placed=arr[k], at=k)
        tracker.snapshot(f"Place  arr[{k}]={arr[k]}")
        k += 1

    while i < len(left):
        arr[k] = left[i]
        tracker.highlight(array={"updated": [k], "visited": list(range(lo, k))})
        tracker.set_meta(phase="flush_left", value=arr[k])
        tracker.snapshot(f"Flush left[{i}]={arr[k]} → arr[{k}]")
        i += 1; k += 1

    while j < len(right):
        arr[k] = right[j]
        tracker.highlight(array={"updated": [k], "visited": list(range(lo, k))})
        tracker.set_meta(phase="flush_right", value=arr[k])
        tracker.snapshot(f"Flush right[{j}]={arr[k]} → arr[{k}]")
        j += 1; k += 1

    # ── Subarray merged ───────────────────────────────────────────────────────
    tracker.highlight(array={"visited": list(range(lo, hi + 1))})
    tracker.set_meta(phase="merged", subarray=arr[lo : hi + 1])
    tracker.snapshot(f"Merged [{lo}..{hi}] → {arr[lo:hi+1]}")


def run(arr: List[int], tracker: StateTracker) -> None:
    """Entry point called by app.py. Sorts arr in-place."""
    merge_sort(arr, tracker)


if __name__ == "__main__":
    import random
    data = random.sample(range(1, 50), 8)
    print(f"Input : {data}")
    with StateTracker() as t:
        merge_sort(data, t)
    print(f"Sorted: {data}")
    print(f"Snapshots: {len(t)}")
    for s in t.snapshots:
        print(f"  [{s.step:02d}] {s.label}")
