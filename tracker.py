"""
tracker.py — Generic State Tracker for DSA Visualization

Inject a StateTracker into any algorithm without altering its core logic.
The tracker captures deep-copied snapshots at each temporal step so the
visualizer can replay them frame-by-frame.

Usage:
    tracker = StateTracker()
    tracker.watch(graph=adj, dist=dist)
    tracker.highlight(graph={"current": [node], "frontier": list(queue)})
    tracker.set_meta(queue=list(q), depth=d)
    tracker.snapshot("Relaxing edge u→v")
"""
from __future__ import annotations

import copy
import functools
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Snapshot:
    """Immutable record of algorithm state at a single step."""
    step:       int
    label:      str
    variables:  Dict[str, Any]  # deep-copies of all watched variables
    highlights: Dict[str, Any]  # {var_name: {role: [indices/nodes]}}
    metadata:   Dict[str, Any]  # auxiliary context: queue, stack, etc.
    timestamp:  float = field(default_factory=time.time)


# ──────────────────────────────────────────────────────────────────────────────
# Core tracker
# ──────────────────────────────────────────────────────────────────────────────

class StateTracker:
    """
    Generic, algorithm-agnostic state tracker.

    Design principles:
    - Zero coupling to any specific algorithm or data structure.
    - Deep-copies on snapshot so mutations after the fact don't corrupt history.
    - Decorator API (@tracker.trace) for zero-overhead instrumentation.
    - Context-manager support for scoped resets.
    """

    def __init__(self) -> None:
        self._snapshots: List[Snapshot] = []
        self._step: int = 0
        self._watched: Dict[str, Any] = {}
        self._highlights: Dict[str, Any] = {}
        self._metadata: Dict[str, Any] = {}

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def snapshots(self) -> List[Snapshot]:
        return self._snapshots

    def __len__(self) -> int:
        return len(self._snapshots)

    # ── State mutation API ────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear all history and reset step counter."""
        self._snapshots.clear()
        self._step = 0
        self._watched.clear()
        self._highlights.clear()
        self._metadata.clear()

    def watch(self, **kwargs: Any) -> None:
        """
        Register variables to include in every subsequent snapshot.

            tracker.watch(array=arr, dist=dist_table)

        Values are stored by reference and deep-copied only at snapshot time,
        so you can call watch() once and mutate the variables freely.
        """
        self._watched.update(kwargs)

    def replace_watched(self, **kwargs: Any) -> None:
        """Make exactly these variables the watched set (drops all others)."""
        self._watched = dict(kwargs)

    def unwatch(self, *names: str) -> None:
        """Stop including the given variables in subsequent snapshots."""
        for name in names:
            self._watched.pop(name, None)

    def highlight(self, **kwargs: Any) -> None:
        """
        Declare which indices / nodes to emphasise in the next snapshot.

        Keys must match watched variable names.
        Values are dicts mapping a semantic role to a list of indices/node-ids:

            tracker.highlight(
                graph={"current": [u], "frontier": list(queue), "visited": list(seen)},
                dist={"updated": [v]},
            )

        Roles understood by the visualizer:
            current   — node/index being processed right now   (magenta)
            frontier  — nodes in queue / open-set             (orange)
            visited   — fully processed nodes                  (cyan)
            path      — nodes on the final answer path         (green)
            updated   — cells just written                     (yellow)
        """
        self._highlights = kwargs

    def set_meta(self, **kwargs: Any) -> None:
        """Store auxiliary state shown in the context panel (queue, depth…)."""
        self._metadata.update(kwargs)

    def clear_meta(self) -> None:
        self._metadata.clear()

    def snapshot(self, label: str = "") -> Snapshot:
        """
        Capture and store an immutable snapshot of the current state.
        Returns the Snapshot so callers can inspect or discard it.
        """
        snap = Snapshot(
            step=self._step,
            label=label,
            variables=copy.deepcopy(self._watched),
            highlights=copy.deepcopy(self._highlights),
            metadata=copy.deepcopy(self._metadata),
        )
        self._snapshots.append(snap)
        self._step += 1
        return snap

    # ── Decorator API ─────────────────────────────────────────────────────────

    def trace(self, label: str | Callable = "") -> Callable:
        """
        Decorator that auto-snapshots after every call to the wrapped function.

            @tracker.trace("Visit node {0}")
            def visit(node): ...

        Label string supports positional-arg interpolation via str.format.
        Alternatively pass a callable: label=lambda node: f"Visit {node}".
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                result = func(*args, **kwargs)
                if callable(label):
                    lbl = label(*args, **kwargs)
                elif isinstance(label, str):
                    try:
                        lbl = label.format(*args, **kwargs) if args else label
                    except Exception:
                        lbl = label
                else:
                    lbl = func.__name__
                self.snapshot(lbl)
                return result
            return wrapper
        return decorator

    # ── Context-manager support ───────────────────────────────────────────────

    def __enter__(self) -> "StateTracker":
        self.reset()
        return self

    def __exit__(self, *_: Any) -> None:
        pass  # history preserved; caller reads tracker.snapshots after exit
