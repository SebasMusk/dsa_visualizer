"""
app.py - DSA Visualizer Engine (CAUS)

Single flow, no AI:
  paste Python code + test input (stdin) -> run with CodeInstrumentor -> visualize
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from tracker import StateTracker
from instrumentor import CodeInstrumentor, highlighted_source_html
from visualizer import COLORS
from js_renderer import VIZ_IFRAME_HEIGHT, build_viz_html

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="DSA Visualizer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ────────────────────────────────────────────────────────────────────────

st.markdown(f"""
<style>
  .stApp {{ background-color:{COLORS['bg']}; color:{COLORS['text']}; }}
  [data-testid="stSidebar"] {{ background-color:{COLORS['bg2']}; }}
  h1,h2,h3 {{ color:{COLORS['visited']} !important;
              font-family:'JetBrains Mono','Fira Code',monospace; }}
  .step-badge {{
    background:{COLORS['bg2']}; border:1px solid {COLORS['visited']};
    border-radius:6px; padding:6px 14px; font-family:monospace;
    font-size:14px; color:{COLORS['visited']}; display:inline-block; margin-bottom:10px;
  }}
  .meta-panel {{
    background:{COLORS['bg2']}; border:1px solid {COLORS['grid_ln']};
    border-radius:8px; padding:12px 14px;
    font-family:'JetBrains Mono',monospace; font-size:12px; line-height:1.8;
  }}
  .meta-key {{ color:{COLORS['frontier']}; font-weight:bold; }}
  .meta-val {{ color:{COLORS['text']}; }}
  #MainMenu,footer,header {{ visibility:hidden; }}
</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────

_DEFAULTS = {
    "viz_snapshots": [], "viz_source": "", "viz_exec_time": None,
    "viz_output": "", "viz_stderr": "", "viz_truncated": False,
    "viz_error": None, "viz_ran": False,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Helpers ────────────────────────────────────────────────────────────────────

def _render_complexity_bar(exec_time_ms: Optional[float], steps: int) -> None:
    parts = []
    if steps:
        parts.append(f"<span><b style='color:#00ff88'>{steps}</b> pasos</span>")
    if exec_time_ms is not None:
        if exec_time_ms < 1:
            t_str = f"{exec_time_ms*1000:.0f}µs"
        elif exec_time_ms < 1000:
            t_str = f"{exec_time_ms:.1f}ms"
        else:
            t_str = f"{exec_time_ms/1000:.2f}s"
        parts.append(f"<span>Tiempo real: <b style='color:#00ff88'>{t_str}</b></span>")
    if not parts:
        return
    sep = "<span style='color:#333;margin:0 8px'>|</span>"
    st.markdown(
        f'<div style="background:#1a1a1a;border:1px solid #2d2d2d;border-radius:6px;'
        f'padding:8px 14px;font-family:JetBrains Mono,monospace;font-size:12px;'
        f'color:#888;display:flex;align-items:center;gap:0;margin-top:6px">'
        f'{sep.join(parts)}</div>',
        unsafe_allow_html=True
    )


# ── Header ─────────────────────────────────────────────────────────────────────

st.markdown("""
<div style="display:flex;align-items:center;gap:20px;margin-bottom:8px">
  <svg width="80" height="80" viewBox="0 0 200 200">
    <polygon points="100,18 182,73 152,175 48,175 18,73"
             fill="none" stroke="#1e3a5f" stroke-width="3"/>
    <line x1="100" y1="18"  x2="152" y2="175" stroke="#2d5a8e" stroke-width="1.5" opacity="0.7"/>
    <line x1="100" y1="18"  x2="48"  y2="175" stroke="#2d5a8e" stroke-width="1.5" opacity="0.7"/>
    <line x1="182" y1="73"  x2="48"  y2="175" stroke="#2d5a8e" stroke-width="1.5" opacity="0.7"/>
    <line x1="182" y1="73"  x2="18"  y2="73"  stroke="#2d5a8e" stroke-width="1.5" opacity="0.7"/>
    <line x1="152" y1="175" x2="18"  y2="73"  stroke="#2d5a8e" stroke-width="1.5" opacity="0.7"/>
    <circle cx="100" cy="18"  r="12" fill="#00ff88" stroke="#1a1a2e" stroke-width="3"/>
    <circle cx="182" cy="73"  r="12" fill="#00d4d4" stroke="#1a1a2e" stroke-width="3"/>
    <circle cx="152" cy="175" r="12" fill="#00d4d4" stroke="#1a1a2e" stroke-width="3"/>
    <circle cx="48"  cy="175" r="12" fill="#00d4d4" stroke="#1a1a2e" stroke-width="3"/>
    <circle cx="18"  cy="73"  r="12" fill="#00d4d4" stroke="#1a1a2e" stroke-width="3"/>
  </svg>
  <div>
    <div style="font-size:26px;font-weight:700;color:#00ff88;
                font-family:JetBrains Mono,monospace;line-height:1.1">
      DSA Visualizer Engine
    </div>
    <div style="font-size:12px;color:#555;font-family:monospace;margin-top:2px">
      Club de Algoritmia · Universidad de Sevilla · CAUS
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Inputs ─────────────────────────────────────────────────────────────────────

st.markdown("Pega tu código Python y un input de prueba. Lo ejecutamos paso a paso y lo visualizamos.")

user_code = st.text_area(
    "Tu código Python", height=300, key="code_input",
    placeholder="n = int(input())\narr = list(map(int, input().split()))\n...",
)
stdin_text = st.text_area(
    "Input de prueba (stdin)", height=100, key="stdin_input",
    placeholder="5\n1 2 3 4 5",
)
watch_vars_str = st.text_input(
    "Variables a observar (opcional)", key="watch_vars",
    placeholder="vacío = todas · ej: dist, visited, dp",
)

run_btn = st.button("⚡  Visualizar", type="primary")

if run_btn:
    if not user_code.strip():
        st.warning("Pega tu código antes de continuar.")
    else:
        watch_vars = [v.strip() for v in watch_vars_str.split(",") if v.strip()] or None
        tracker = StateTracker()
        instr = CodeInstrumentor(tracker, watch_vars=watch_vars)
        with st.spinner("⚙️ Ejecutando…"):
            instr.run(user_code, stdin_text=stdin_text)

        st.session_state["viz_snapshots"] = tracker.snapshots
        st.session_state["viz_source"]    = user_code
        st.session_state["viz_exec_time"] = instr.exec_time_ms
        st.session_state["viz_output"]    = instr.output
        st.session_state["viz_stderr"]    = instr.stderr_output
        st.session_state["viz_truncated"] = instr.truncated
        st.session_state["viz_error"]     = instr.error_info
        st.session_state["viz_ran"]       = True

# ── Results ────────────────────────────────────────────────────────────────────

if st.session_state["viz_ran"]:
    snaps = st.session_state["viz_snapshots"]
    source = st.session_state["viz_source"]
    err = st.session_state["viz_error"]

    if err:
        line = err.get("line")
        where = f" en la línea {line}" if line else ""
        st.error(f"**{err['type']}**{where}: {err['msg']}")
        if line:
            src_lines = source.splitlines()
            if 0 < line <= len(src_lines):
                st.code(f"{line:>4} │ {src_lines[line - 1]}", language="python")
            with st.expander("Ver código con la línea del error", expanded=False):
                st.markdown(highlighted_source_html(source, line, COLORS),
                            unsafe_allow_html=True)
    else:
        st.success(f"✅ Ejecución completada — **{len(snaps)} pasos** capturados.")

    _render_complexity_bar(st.session_state["viz_exec_time"], len(snaps))

    if st.session_state["viz_truncated"]:
        ran_ok = "El programa se ejecutó entero (la salida está completa), pero s" if not err else "S"
        st.warning(
            f"⚠️ Traza truncada en {len(snaps)} pasos. {ran_ok}olo se visualizan "
            f"los primeros {len(snaps)} pasos. Usa «Variables a observar» o un input más pequeño."
        )

    st.markdown("**Salida del programa**")
    st.code(st.session_state["viz_output"] or "(sin salida)", language="text")
    if st.session_state["viz_stderr"]:
        with st.expander("stderr", expanded=False):
            st.code(st.session_state["viz_stderr"], language="text")

    if snaps:
        st.divider()
        st.components.v1.html(
            build_viz_html(snaps, source_lines=source.splitlines(),
                           output=st.session_state["viz_output"]),
            height=VIZ_IFRAME_HEIGHT, scrolling=False,
        )
    elif not err:
        st.info("No se capturaron pasos: el código no asignó variables observables.")
