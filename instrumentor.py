"""
instrumentor.py — Automatic code instrumentation for the Python visualizer

Uses Python's sys.settrace (same mechanism as pdb / coverage.py) to capture
variable state at every line where tracked variables change value.

Safety model:
  - Restricted builtins (no file I/O, no network, no subprocess)
  - Whitelisted imports (see _SAFE_MODULES); `sys` and `io` are fakes
  - Per-run FakeSys: stdin comes from the user's test input, stdout/stderr
    are captured in memory
  - Timeout enforced from inside the trace hook (the runaway code really
    stops), plus a daemon-thread join as a last resort
"""
from __future__ import annotations

import __future__ as _future
import ast
import bisect as _bisect
import builtins as _builtins
import collections as _collections
import copy as _copy
import dataclasses as _dataclasses
import decimal as _decimal
import fractions as _fractions
import functools as _functools
import heapq as _heapq
import io
import itertools as _itertools
import math as _math
import operator as _operator
import random as _random
import statistics as _statistics
import string as _string
import sys
import threading
import time
import traceback
import types
import typing as _typing
from collections import deque
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Set

from tracker import StateTracker


# ──────────────────────────────────────────────────────────────────────────────
# Safe execution environment
# ──────────────────────────────────────────────────────────────────────────────

_ALLOWED_BUILTINS = {
    'abs', 'all', 'any', 'bin', 'bool', 'bytearray', 'bytes', 'callable',
    'chr', 'classmethod', 'complex', 'dict', 'divmod', 'enumerate', 'filter',
    'float', 'format', 'frozenset', 'getattr', 'hasattr', 'hash', 'hex', 'id',
    'int', 'isinstance', 'issubclass', 'iter', 'len', 'list', 'map',
    'max', 'min', 'next', 'object', 'oct', 'ord', 'pow',
    'property', 'range', 'repr', 'reversed', 'round', 'set', 'setattr',
    'slice', 'sorted', 'staticmethod', 'str', 'sum', 'super', 'tuple',
    'type', 'vars', 'zip',
    'ArithmeticError', 'AssertionError', 'AttributeError', 'BaseException',
    'EOFError', 'Exception', 'IndexError', 'KeyError', 'LookupError',
    'NameError', 'NotImplementedError', 'OverflowError', 'RecursionError',
    'RuntimeError', 'StopIteration', 'SystemExit', 'TypeError',
    'ValueError', 'ZeroDivisionError',
    'True', 'False', 'None', 'NotImplemented', 'Ellipsis',
}

# Only in-memory streams: the real `io` module exposes io.open / io.FileIO.
_SAFE_IO = types.SimpleNamespace(StringIO=io.StringIO, BytesIO=io.BytesIO)

# Real modules that are safe to hand out. `sys` and `io` are added per run.
_SAFE_MODULES: Dict[str, Any] = {
    'math':        _math,
    'collections': _collections,
    'heapq':       _heapq,
    'itertools':   _itertools,
    'functools':   _functools,
    'bisect':      _bisect,
    'random':      _random,
    'string':      _string,
    'operator':    _operator,
    'copy':        _copy,
    'typing':      _typing,
    'dataclasses': _dataclasses,
    'fractions':   _fractions,
    'decimal':     _decimal,
    'statistics':  _statistics,
}

_MAX_OUTPUT_CHARS = 1_000_000

# Highest recursion limit user code may request via sys.setrecursionlimit().
_MAX_RECURSION_LIMIT = 200_000
# Snapshots keep at most this many items per container (the renderer never shows
# more than 50 cells / 20 graph nodes) and this much nesting. Real sizes go to
# metadata['__sizes__'].
_SNAP_MAX_ITEMS = 300
_SNAP_MAX_DEPTH = 20
# Stack sizes tried (in order) for the thread that runs user code. Deep Python
# recursion needs a big C stack; the first size the OS accepts is used.
_THREAD_STACK_SIZES = (256 * 1024 * 1024, 128 * 1024 * 1024, 64 * 1024 * 1024)


class _CappedStringIO(io.StringIO):
    """StringIO that stops accepting text after _MAX_OUTPUT_CHARS."""

    def __init__(self) -> None:
        super().__init__()
        self.overflowed = False

    def write(self, s: str) -> int:
        if self.overflowed:
            return len(s)
        if self.tell() + len(s) > _MAX_OUTPUT_CHARS:
            self.overflowed = True
            super().write(s[: max(0, _MAX_OUTPUT_CHARS - self.tell())])
            super().write("\n… [salida truncada]\n")
            return len(s)
        return super().write(s)


class _FakeStdin(io.StringIO):
    """stdin backed by the test input; .buffer gives the same data as bytes."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.buffer = io.BytesIO(text.encode())


class FakeSys:
    """Minimal stand-in for the `sys` module inside the sandbox."""

    def __init__(self, stdin_text: str = "") -> None:
        self.stdin  = _FakeStdin(stdin_text)
        self.stdout = _CappedStringIO()
        self.stderr = _CappedStringIO()
        self.maxsize = sys.maxsize
        self.version_info = sys.version_info
        self.float_info = sys.float_info
        self.argv: List[str] = ['main.py']

    def setrecursionlimit(self, limit: int) -> None:
        """Real limit, capped at _MAX_RECURSION_LIMIT. The instrumentor restores
        the original limit when the run ends (success, error or timeout)."""
        sys.setrecursionlimit(min(limit, _MAX_RECURSION_LIMIT))

    def getrecursionlimit(self) -> int:
        return sys.getrecursionlimit()

    def set_int_max_str_digits(self, _n: int) -> None:  # no-op
        pass

    def exit(self, code: Any = None) -> None:
        raise SystemExit(code)

    def flush(self) -> None:                            # no-op
        pass


def _make_input(fake_sys: FakeSys) -> Callable[..., str]:
    def _input(prompt: Any = "") -> str:
        if prompt:
            fake_sys.stdout.write(str(prompt))
        line = fake_sys.stdin.readline()
        if line == "":
            raise EOFError("EOF when reading a line")
        return line.removesuffix("\n").removesuffix("\r")
    return _input


def _make_print(fake_sys: FakeSys) -> Callable[..., None]:
    def _print(*args: Any, sep: Optional[str] = " ", end: Optional[str] = "\n",
               file: Any = None, flush: bool = False) -> None:
        target = fake_sys.stdout if file is None else file
        sep = " " if sep is None else sep
        end = "\n" if end is None else end
        target.write(sep.join(str(a) for a in args) + end)
    return _print


def _make_safe_globals(fake_sys: FakeSys) -> Dict[str, Any]:
    modules = {**_SAFE_MODULES, 'sys': fake_sys, 'io': _SAFE_IO}

    def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        base = name.split('.')[0]
        if base == '__future__':
            return _future
        if base in modules:
            return modules[base]
        raise ImportError(
            f"'{name}' está bloqueado en el sandbox. "
            f"Permitidos: {', '.join(sorted(modules))}."
        )

    safe_bi = {k: getattr(_builtins, k)
               for k in _ALLOWED_BUILTINS if hasattr(_builtins, k)}
    safe_bi['__import__']      = _restricted_import
    safe_bi['__build_class__'] = _builtins.__build_class__
    safe_bi['input']           = _make_input(fake_sys)
    safe_bi['print']           = _make_print(fake_sys)
    safe_bi['exit']            = fake_sys.exit
    safe_bi['quit']            = fake_sys.exit

    safe_dict: Dict[str, Any] = {'__builtins__': safe_bi, **modules}
    safe_dict['__name__'] = '__main__'
    return safe_dict


class _Timeout(BaseException):
    """Raised from the trace hook; BaseException so `except Exception` can't eat it."""


# ──────────────────────────────────────────────────────────────────────────────
# Type helpers
# ──────────────────────────────────────────────────────────────────────────────

def _normalise(value: Any) -> Any:
    """Convert set/deque → list so the visualizer can render them."""
    if isinstance(value, (set, frozenset)):
        try:
            if len(value) > _SNAP_MAX_ITEMS:
                return _heapq.nsmallest(_SNAP_MAX_ITEMS, value)
            return sorted(value)
        except TypeError:
            return list(_itertools.islice(value, _SNAP_MAX_ITEMS))
    if isinstance(value, deque):
        return list(_itertools.islice(value, _SNAP_MAX_ITEMS))
    return value


def _is_weighted_adj(rows: Any) -> bool:
    """Every row is a list and every entry a 2-tuple (neighbour, weight)."""
    rows = list(rows)
    if not rows or not all(isinstance(r, list) for r in rows):
        return False
    items = [e for r in rows for e in r]
    return bool(items) and all(isinstance(e, tuple) and len(e) == 2 for e in items)


_ATOMIC = (int, float, complex, bool, str, bytes, type(None))


def _bounded_copy(obj: Any, depth: int = 0) -> Any:
    """Deep copy that keeps only the first _SNAP_MAX_ITEMS items of each container."""
    if isinstance(obj, _ATOMIC):
        return obj
    if depth >= _SNAP_MAX_DEPTH:
        return '…'
    L, d = _SNAP_MAX_ITEMS, depth + 1
    if isinstance(obj, list):
        return [_bounded_copy(x, d) for x in obj[:L]]
    if isinstance(obj, tuple):
        return tuple(_bounded_copy(x, d) for x in obj[:L])
    if isinstance(obj, dict):
        return {k: _bounded_copy(v, d) for k, v in _itertools.islice(obj.items(), L)}
    if isinstance(obj, (set, frozenset)):
        return type(obj)(_itertools.islice(obj, L))
    if isinstance(obj, deque):
        return deque(_bounded_copy(x, d) for x in _itertools.islice(obj, L))
    try:
        return deepcopy(obj)
    except Exception:
        return repr(obj)


def _view(value: Any) -> Any:
    """Cheap top-level truncation, comparable with a _bounded_copy of the value."""
    if isinstance(value, (list, tuple)) and len(value) > _SNAP_MAX_ITEMS:
        return value[:_SNAP_MAX_ITEMS]
    if isinstance(value, dict) and len(value) > _SNAP_MAX_ITEMS:
        return dict(_itertools.islice(value.items(), _SNAP_MAX_ITEMS))
    return value


def _big_size(value: Any) -> Optional[int]:
    if isinstance(value, (list, tuple, dict, set, frozenset, deque)) and len(value) > _SNAP_MAX_ITEMS:
        return len(value)
    return None


def _kind(value: Any) -> Optional[str]:
    """Python-side type hint for the renderer (lost once values become JSON)."""
    if isinstance(value, deque):
        return 'deque'
    if isinstance(value, (set, frozenset)):
        return 'set'
    if isinstance(value, tuple):
        return 'tuple'
    if isinstance(value, dict) and _is_weighted_adj(value.values()):
        return 'weighted_adj'
    if isinstance(value, list) and _is_weighted_adj(value):
        return 'weighted_adj'
    if isinstance(value, list) and value and all(isinstance(x, tuple) for x in value):
        return 'tuple_list'
    if isinstance(value, list) and value:
        return 'list'
    if isinstance(value, str):
        return 'str'
    return None


def _index_vars(code: str) -> tuple:
    """Which names are used as indices, globally and per container.

    X[expr] makes the names that appear directly in `expr` pointers of X:
    a[i], a[lo:hi], a[mid+1], dp[i-1][j] (dp ← i, j). A nested subscript counts
    for its own container: dp[c - w[i]] gives dp ← c and w ← i, so `i` is not
    drawn under dp. `k` in `need > k` is a value, never an index.
    Returns (sorted global list, {container: sorted names}); ([], {}) if the
    code doesn't parse.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return [], {}

    def direct_names(expr):
        found, stack = set(), [expr]
        while stack:
            node = stack.pop()
            if isinstance(node, ast.Subscript):
                continue            # handled as its own container
            if isinstance(node, ast.Name):
                found.add(node.id)
            stack.extend(ast.iter_child_nodes(node))
        return found

    def root_name(node):
        while isinstance(node, ast.Subscript):
            node = node.value
        return node.id if isinstance(node, ast.Name) else None

    per: Dict[str, set] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            names = direct_names(node.slice)
            container = root_name(node.value)
            if container and names:
                per.setdefault(container, set()).update(names)
    all_names = sorted(set().union(*per.values())) if per else []
    return all_names, {k: sorted(v) for k, v in per.items()}


def _is_trackable(name: str, value: Any) -> bool:
    if name.startswith('_') or name in {'__builtins__', '__doc__', '__name__'}:
        return False
    if callable(value) and not isinstance(value, (list, dict, set, deque, tuple)):
        return False  # skip functions, lambdas, classes
    return isinstance(value, (int, float, bool, str,
                               list, tuple, dict, set, frozenset, deque))


# ──────────────────────────────────────────────────────────────────────────────
# Core instrumentor
# ──────────────────────────────────────────────────────────────────────────────

class CodeInstrumentor:
    """
    Instruments arbitrary Python code and captures StateTracker snapshots
    at each line where at least one tracked variable changes value.

    Usage:
        tracker = StateTracker()
        instr   = CodeInstrumentor(tracker, watch_vars=["arr", "dist"])
        error   = instr.run(code_string, stdin_text="5\n1 2 3 4 5")
        # error is None on success. After run():
        #   instr.output        — what the program printed (stdout)
        #   instr.stderr_output — what it wrote to sys.stderr
        #   instr.truncated     — True if max_snapshots was reached
        #   instr.error_info    — {'type', 'msg', 'line'} or None
        #   instr.exec_time_ms  — wall time of an untraced run (None if n/a)
        #   instr.stack_size_used — thread stack used for user code (256/128/64 MB)
    Deep recursion: sys.setrecursionlimit(n) inside user code applies
    min(n, 200000) for that run only; the original limit is always restored.
    """

    _FILENAME = "<user_code>"

    def __init__(
        self,
        tracker: StateTracker,
        max_snapshots: int = 1500,
        timeout_seconds: int = 8,
        watch_vars: Optional[List[str]] = None,
    ) -> None:
        self.tracker       = tracker
        self.max_snapshots = max_snapshots
        self.timeout       = timeout_seconds
        self.watch_vars: Optional[Set[str]] = (
            set(watch_vars) if watch_vars else None
        )
        self._src_lines: List[str] = []
        self._prev: Dict[str, Any] = {}
        self._kinds: Dict[str, str] = {}
        self._sizes: Dict[str, int] = {}   # real len() of containers bigger than the snapshot cap
        self._owner: Dict[str, int] = {}   # var name → id() of the frame that last set it
        self._deadline = 0.0
        self._last_line = 0
        self._out: Optional[io.StringIO] = None   # stdout of the traced run
        self._snap_out_len = 0                     # out_len of the last snapshot
        self._globals: Optional[Dict[str, Any]] = None
        self._stopped = False

        self.output: str = ""
        self.stderr_output: str = ""
        self.truncated: bool = False
        self.error_info: Optional[Dict[str, Any]] = None
        self.exec_time_ms: Optional[float] = None
        self.stack_size_used: int = 0   # bytes of thread stack (0 = OS default)

    # ── sys.settrace hooks ────────────────────────────────────────────────────

    def _call_hook(self, frame, event, arg):
        """Return line hook only for frames that belong to user code."""
        if frame.f_code.co_filename == self._FILENAME:
            if time.perf_counter() > self._deadline:
                raise _Timeout()
            return self._line_hook
        return None

    def _line_hook(self, frame, event, arg):
        # 'line' fires BEFORE a line runs; 'return' lets us capture the effect
        # of the last line of a function / of the whole program.
        if event not in ('line', 'return'):
            return self._line_hook
        if time.perf_counter() > self._deadline:
            raise _Timeout()
        if self._stopped:
            return self._line_hook

        lineno = frame.f_lineno
        prev_line = self._last_line      # the line that has just finished running
        self._last_line = lineno
        out_len = self._out_len()

        # One slot is always reserved for the final "Fin del programa" step.
        limit = self.max_snapshots - 1
        if len(self.tracker) >= limit:
            self.truncated = True
        else:
            # The previous line printed something → step attributed to THAT line.
            if out_len > self._snap_out_len and prev_line:
                self._record(frame, prev_line, out_len, force=True)
            if len(self.tracker) < limit:
                self._record(frame, lineno, out_len)
            else:
                self.truncated = True

        # A finished function's locals no longer exist: stop showing them.
        if event == 'return' and frame.f_code.co_name != '<module>':
            self._release(id(frame))
        return self._line_hook

    def _out_len(self) -> int:
        return self._out.tell() if self._out is not None else 0

    def _release(self, fid: int) -> None:
        owned = [k for k, owner in self._owner.items() if owner == fid]
        for k in owned:
            del self._owner[k]
            self._kinds.pop(k, None)
            self._sizes.pop(k, None)
            self._prev.pop(k, None)
        if owned:
            self.tracker.unwatch(*owned)

    def _record(self, frame, lineno: int, out_len: int, force: bool = False) -> None:
        raw = {
            k: v for k, v in frame.f_locals.items()
            if _is_trackable(k, v)
            and (self.watch_vars is None or k in self.watch_vars)
        }
        current = {k: _normalise(v) for k, v in raw.items()}

        # Drop variables that vanished from the frame that provided them
        # (e.g. a comprehension's loop variable, or `del x`).
        fid = id(frame)
        gone = [k for k, owner in self._owner.items()
                if owner == fid and k not in current]
        for k in gone:
            del self._owner[k]
            self._kinds.pop(k, None)
            self._sizes.pop(k, None)
        for k in current:
            self._owner[k] = fid
        if gone:
            self.tracker.unwatch(*gone)

        if not force and (not current or not (gone or self._changed(current))):
            return

        for k, v in raw.items():
            kind = _kind(v)
            if kind is not None:
                self._kinds[k] = kind
            size = _big_size(v)
            if size is None:
                self._sizes.pop(k, None)
            else:
                self._sizes[k] = size

        self.tracker.watch(**current)
        src = self._src(lineno)
        self.tracker.set_meta(line=lineno, source=src, __kinds__=dict(self._kinds),
                              __sizes__=dict(self._sizes), out_len=out_len)
        snap = self.tracker.snapshot(f"L{lineno}: {src}")
        # Snapshot copies are never mutated: reuse them instead of copying again.
        self._prev = {k: snap.variables[k] for k in current}
        self._snap_out_len = out_len

    def _src(self, lineno: Optional[int]) -> str:
        if lineno and 0 < lineno <= len(self._src_lines):
            return self._src_lines[lineno - 1].strip()
        return ""

    def _final_snapshot(self, output: str, error: Optional[Dict[str, Any]]) -> None:
        """Always-present last step: module-level state + full output (+ error)."""
        g = self._globals or {}
        raw = {k: v for k, v in list(g.items())
               if _is_trackable(k, v)
               and (self.watch_vars is None or k in self.watch_vars)}
        if raw:
            self.tracker.replace_watched(**{k: _normalise(v) for k, v in raw.items()})
            kinds = {k: kd for k, v in raw.items() if (kd := _kind(v)) is not None}
            sizes = {k: sz for k, v in raw.items() if (sz := _big_size(v)) is not None}
        elif self.tracker.snapshots:
            # Everything lived inside main()/solve(): keep the last state seen.
            last = self.tracker.snapshots[-1]
            self.tracker.replace_watched(**last.variables)
            kinds = dict(last.metadata.get('__kinds__', {}))
            sizes = dict(last.metadata.get('__sizes__', {}))
        else:
            kinds, sizes = {}, {}

        line = (error or {}).get('line') or self._last_line or None
        meta: Dict[str, Any] = dict(line=line, source=self._src(line), __kinds__=kinds,
                                    __sizes__=sizes,
                                    out_len=len(output), final=True, error=bool(error))
        if error:
            meta['error_msg'] = f"{error['type']}: {error['msg']}"
        self.tracker.set_meta(**meta)
        self.tracker.snapshot("Fin del programa")

    def _changed(self, current: Dict[str, Any]) -> bool:
        if set(current) != set(self._prev):
            return True
        for k, v in current.items():
            try:
                if _view(v) != self._prev.get(k):
                    return True
            except Exception:
                return True
        return False

    # ── Execution ─────────────────────────────────────────────────────────────

    def _user_line(self, exc: BaseException) -> Optional[int]:
        """Line of the innermost user-code frame in the traceback.

        For RecursionError, if the two innermost user frames run the same
        function, report the caller's line: that is the recursive call.
        """
        last = prev = None   # (code, lineno) of the innermost / 2nd innermost
        tb = exc.__traceback__
        while tb is not None:   # manual walk: extract_tb is slow on 200k frames
            code = tb.tb_frame.f_code
            if code.co_filename == self._FILENAME:
                prev, last = last, (code, tb.tb_lineno)
            tb = tb.tb_next
        if last is None:
            return None
        if isinstance(exc, RecursionError) and prev is not None and prev[0] is last[0]:
            return prev[1]
        return last[1]

    @staticmethod
    def _start_big_stack_thread(target: Callable[[], None]) -> tuple:
        """Start `target` in a daemon thread with the largest stack the OS accepts."""
        old = threading.stack_size()
        used = 0
        for size in _THREAD_STACK_SIZES:
            try:
                threading.stack_size(size)
                used = size
                break
            except (ValueError, RuntimeError):
                continue
        try:
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
        finally:
            threading.stack_size(old)   # never leak the setting to other threads
        return thread, used

    def _exec_once(self, compiled, stdin_text: str, traced: bool) -> Dict[str, Any]:
        """Run compiled code once in a fresh sandbox, in a daemon thread."""
        fake_sys = FakeSys(stdin_text)
        result: Dict[str, Any] = {'error': None, 'elapsed': None, 'done': False}

        sandbox_globals = _make_safe_globals(fake_sys)
        if traced:
            self._out = fake_sys.stdout
            self._globals = sandbox_globals

        orig_limit = sys.getrecursionlimit()

        def _execute() -> None:
            t0 = time.perf_counter()
            try:
                if traced:
                    self._deadline = t0 + self.timeout
                    sys.settrace(self._call_hook)
                exec(compiled, sandbox_globals)  # noqa: S102
            except SystemExit:
                pass  # sys.exit() / exit() → normal termination
            except _Timeout:
                result['error'] = {
                    'type': 'TimeoutError',
                    'msg': f"Tiempo límite de {self.timeout}s superado "
                           "(¿bucle infinito o input muy grande?)",
                    'line': self._last_line or None,
                }
            except RecursionError as exc:
                limit = sys.getrecursionlimit()
                result['error'] = {
                    'type': 'RecursionError',
                    'msg': f"Recursión demasiado profunda (límite {limit}). Si tu código "
                           "usa recursión, llama a sys.setrecursionlimit(...)",
                    'line': self._user_line(exc),
                }
            except BaseException as exc:  # noqa: BLE001 — report everything
                result['error'] = {
                    'type': type(exc).__name__,
                    'msg': str(exc),
                    'line': self._user_line(exc),
                }
            finally:
                if traced:
                    sys.settrace(None)
                sys.setrecursionlimit(orig_limit)
                result['elapsed'] = (time.perf_counter() - t0) * 1000
                result['done'] = True

        thread, self.stack_size_used = self._start_big_stack_thread(_execute)
        thread.join(timeout=self.timeout + 1)
        sys.setrecursionlimit(orig_limit)   # also if the thread is still stuck

        if not result['done']:
            self._stopped = True   # runaway thread: stop recording from it
            result['error'] = {
                'type': 'TimeoutError',
                'msg': f"Tiempo límite de {self.timeout}s superado.",
                'line': self._last_line or None,
            }
            result['elapsed'] = None
        result['stdout'] = fake_sys.stdout.getvalue()
        result['stderr'] = fake_sys.stderr.getvalue()
        return result

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, code: str, stdin_text: str = "") -> Optional[str]:
        """
        Instrument and execute code string with `stdin_text` as standard input.
        Returns None on success, or an error message string on failure/timeout.
        """
        self._src_lines = code.splitlines()
        self._prev      = {}
        self._kinds     = {}
        self._sizes     = {}
        self._owner     = {}
        self.tracker.copy_fn = _bounded_copy
        self._last_line = 0
        self._snap_out_len = 0
        self._out = None
        self._globals = None
        self._stopped = False
        self.output = self.stderr_output = ""
        self.truncated = False
        self.error_info = None
        self.exec_time_ms = None

        try:
            compiled = compile(code, self._FILENAME, 'exec')
        except SyntaxError as e:
            self.error_info = {'type': 'SyntaxError', 'msg': e.msg, 'line': e.lineno}
            return f"SyntaxError (línea {e.lineno}): {e.msg}"

        # Global metadata (carried by every snapshot): which names act as indices.
        index_vars, index_map = _index_vars(code)
        self.tracker.set_meta(__indexvars__=index_vars, __indexmap__=index_map)

        # 1) Traced run → snapshots + program output (consistent with the trace).
        traced = self._exec_once(compiled, stdin_text, traced=True)
        self.output = traced['stdout']
        self.stderr_output = traced['stderr']
        self._final_snapshot(self.output, traced['error'])
        self._globals = None

        if traced['error']:
            self.error_info = traced['error']
            line = self.error_info['line']
            where = f" (línea {line})" if line else ""
            return f"{self.error_info['type']}{where}: {self.error_info['msg']}"

        # 2) Untraced run → honest wall-clock time (tracing adds 10–100× overhead).
        plain = self._exec_once(compiled, stdin_text, traced=False)
        if not plain['error']:
            self.exec_time_ms = plain['elapsed']
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Source display helper (used by app.py)
# ──────────────────────────────────────────────────────────────────────────────

def highlighted_source_html(source: str, active_line: int,
                             colors: Dict[str, str]) -> str:
    """HTML block of source code with active_line highlighted in magenta."""
    lines = source.splitlines()
    rows = []
    for i, line in enumerate(lines, 1):
        escaped = (line.replace("&", "&amp;")
                       .replace("<", "&lt;")
                       .replace(">", "&gt;"))
        if i == active_line:
            rows.append(
                f'<div style="background:{colors["current"]}33;'
                f'color:{colors["current"]};font-weight:bold;padding:1px 4px;">'
                f'<span style="opacity:.6">{i:3d} ▶</span>  {escaped}</div>'
            )
        else:
            rows.append(
                f'<div style="color:{colors["text"]};padding:1px 4px;">'
                f'<span style="opacity:.35">{i:3d}  </span>  {escaped}</div>'
            )
    inner = "\n".join(rows)
    return (
        f'<div style="background:{colors["bg2"]};border:1px solid {colors["grid_ln"]};'
        f'border-radius:8px;padding:10px;font-family:JetBrains Mono,monospace;'
        f'font-size:12px;overflow-x:auto;white-space:pre;max-height:420px;'
        f'overflow-y:auto;">{inner}</div>'
    )
