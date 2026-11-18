"""
analyzer.py - Gemini-powered engine for DSA Visualizer
"""
from __future__ import annotations

import os
import re
import threading
import traceback
from dataclasses import dataclass, field
from typing import Optional, Tuple, List

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

_API_KEY     = os.getenv("GEMINI_API_KEY", "")
ACTIVE_MODEL   = "gemini-2.5-pro"
FALLBACK_MODEL = "gemini-2.5-flash"

# --- CAMBIO 1: LE OBLIGAMOS A ELEGIR LAS VARIABLES CLAVE ---
_PROBLEM_PROMPT = """
You are an expert competitive programmer.
Given a problem statement and a sample input, generate the optimal solution.
Target display language: {LANG}

STRICT RULES:
1. Implement the OPTIMAL algorithm.
2. If target language is C++, provide the C++ solution inside ```cpp ... ``` fences.
3. You MUST ALWAYS provide a pure Python equivalent of the exact same logic inside 
```python ... ``` fences. (The visualizer only reads Python).
4. For the Python version:
   - Use standard Python: list, dict, set, heapq, collections.deque.
   - Use MEANINGFUL variable names (e.g., adj, dp, dist, visited).
   - Prefer explicit FOR/WHILE loops.
   - Include `if __name__ == "__main__":` at the bottom.
   - Assign the SAMPLE INPUT to a multiline string `RAW_INPUT`. Parse it. DO NOT USE `input()` or `sys.stdin`.
   - CRITICAL: Add `# WATCH: var1, var2` at the EXACT FIRST LINE of the python code. Always include 'adj' in the # WATCH variables list so the graph structure is always visualized.
   - CRITICAL: Add `# COMPLEXITY: O(...) time, O(...) space` as the SECOND LINE (right after # WATCH). Example: # COMPLEXITY: O(V+E) time, O(V) space. Be precise using standard Big-O. For graphs: O(V+E). For sorting: O(n log n). For DP: O(n*m). Always include both time and space.
   - ALGORITHM STRUCTURE: Never use early break/return inside BFS/DFS loops to stop when target is found. Always let the full BFS/DFS complete OR reconstruct the path INSIDE the same loop before breaking. The instrumentor captures state line by line — if you break before path reconstruction, path will never appear in the visualization. Preferred pattern for shortest path: run the full BFS loop first, then reconstruct path AFTER the loop using the parent dict.
   - VISUALIZATION ADAPTATION: The visualizer auto-detects types. 1D lists become Arrays. 2D lists become Grids. Dict of lists become Node/Edge Graphs. If the problem is about Bitwise operations, Math, or Geometry, create a specific 1D or 2D list (e.g., `bit_states` or `points`) inside the algorithm explicitly to track the state so the visualizer can render it!
   - CRITICAL FOR GRAPHS: ALWAYS represent adjacency lists as dict of lists, NEVER as list of lists. Use: adj = collections.defaultdict(list)  # CORRECT. Never use: adj = [[] for _ in range(n+1)]  # WRONG. The visualizer only renders dicts as graphs.
5. Return ONLY the code blocks.
""".strip()

_AUTOPSY_PROMPT = """
You are an expert code translator for competitive programming.
Given user code in {LANG}, produce an EXACT Python adaptation for visualization.

STRICT RULES:
1. PRESERVE the exact algorithm - do NOT fix logic bugs.
2. If {LANG} is C++, translate it identically to Python.
3. If {LANG} is Python, keep the exact same code, BUT:
4. Replace stdin reading (cin/scanf/input()/sys.stdin) with the provided SAMPLE INPUT, assigning it to `RAW_INPUT` and parsing from it.
5. Return ONLY executable Python code inside ```python ... ``` fences.
6. Add `# COMPLEXITY: O(...) time, O(...) space` as the SECOND LINE (right after # WATCH if present). Analyze the ACTUAL algorithm — do NOT assume optimal. Nested loops over n: O(n²). BFS/DFS: O(V+E). Brute force: say so.
If CONSTRAINTS are provided:
- Wrap the lines that dominate complexity with # HOTSPOT_START and # HOTSPOT_END comments.
- Add # VERDICT: ACCEPTED if within constraints, or # VERDICT: TLE_RISK — [brief reason] if it may TLE (rule: >10^8 ops for given n).
""".strip()

# --- CAMBIO 2: AÑADIMOS 'watch_vars' AL RESULTADO ---
@dataclass
class AnalysisResult:
    mode:          str
    display_code:  str
    exec_code:     str
    explanation:   str
    raw:           str
    watch_vars:    List[str]
    complexity:    str  = ""
    verdict:       str  = ""
    hotspot_lines: list = field(default_factory=list)

class GeminiAnalyzer:
    def __init__(self, model: str = ACTIVE_MODEL) -> None:
        if not _API_KEY:
            raise ValueError("GEMINI_API_KEY not set in .env")
        self._model  = model
        self._client = genai.Client(api_key=_API_KEY)
        self._config = {
            "temperature": 0.15,
            "max_output_tokens": 4096,
            "safety_settings": [
                types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",        threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
            ],
        }

    def analyze_problem(self, problem_statement: str, sample_input: str, lang: str = "Python") -> AnalysisResult:
        input_block = f"\nSample Input:\n{sample_input.strip()}" if sample_input else "\nSample Input:\n(None provided)"
        prompt_text = _PROBLEM_PROMPT.replace("{LANG}", lang)
        prompt = f"{prompt_text}\n\nProblem statement:\n{problem_statement.strip()}\n{input_block}"

        raw = self._call(prompt)

        # 1. Intentar buscar el bloque explícito de Python
        python_match = re.search(r"```(?:python|py)\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        
        if python_match:
            exec_code = python_match.group(1).strip()
        else:
            # Si la IA se olvidó de poner la palabra 'python', buscamos todos los bloques de código
            blocks = re.findall(r"```(.*?)```", raw, re.DOTALL)
            if blocks:
                exec_code = blocks[-1].strip() # Cogemos el último (suele ser el Python si pidió C++ primero)
            else:
                exec_code = raw.strip() # Último recurso

        # 2. Extraer el bloque de visualización (C++ o Python)
        if lang == "C++":
            cpp_match = re.search(r"```(?:cpp|c\+\+)\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
            display_code = cpp_match.group(1).strip() if cpp_match else exec_code
        else:
            display_code = exec_code

        # Vacuna anti-markdown
        exec_code = exec_code.replace('if name ==', 'if __name__ ==').replace('if name==', 'if __name__ ==')

        # Extraer variables a vigilar y complejidad
        watch_vars = []
        complexity = ""
        for line in exec_code.splitlines():
            if line.strip().startswith("# WATCH:"):
                v_str = line.strip().replace("# WATCH:", "")
                watch_vars = [v.strip() for v in v_str.split(",") if v.strip()]
            if line.strip().startswith("# COMPLEXITY:"):
                complexity = line.strip().replace("# COMPLEXITY:", "").strip()

        return AnalysisResult(
            mode="problem",
            display_code=display_code,
            exec_code=exec_code,
            explanation=self._first_comment(exec_code, fallback=f"AI-generated {lang} solution"),
            raw=raw,
            watch_vars=watch_vars,
            complexity=complexity,
        )

    def prepare_autopsy(self, user_code: str, lang: str, sample_input: str = "",
                        constraints: str = "") -> AnalysisResult:
        input_block = f"\nSample input:\n{sample_input.strip()}" if sample_input.strip() else "\n(No sample input provided)"
        prompt_text = _AUTOPSY_PROMPT.replace("{LANG}", lang)
        prompt = f"{prompt_text}\n\n{lang} code:\n```{lang.lower()}\n{user_code.strip()}\n```\n{input_block}"
        if constraints.strip():
            prompt += f"\n\nConstraints:\n{constraints.strip()}"

        raw = self._call(prompt)

        python_match = re.search(r"```python\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
        exec_code = python_match.group(1).strip() if python_match else raw.strip()
        exec_code = exec_code.replace('if name ==', 'if __name__ ==').replace('if name==', 'if __name__ ==')

        complexity = ""
        verdict = ""
        hotspot_lines: list = []
        in_hotspot = False
        for i, line in enumerate(exec_code.splitlines(), 1):
            if line.strip().startswith("# COMPLEXITY:"):
                complexity = line.strip().replace("# COMPLEXITY:", "").strip()
            if "# VERDICT:" in line:
                verdict = line.strip().replace("# VERDICT:", "").strip()
            if "# HOTSPOT_START" in line:
                in_hotspot = True
            elif "# HOTSPOT_END" in line:
                in_hotspot = False
            elif in_hotspot:
                hotspot_lines.append(i)

        return AnalysisResult(
            mode="autopsy",
            display_code=user_code,
            exec_code=exec_code,
            explanation=f"Autopsy ready for your {lang} code.",
            raw=raw,
            watch_vars=[],
            complexity=complexity,
            verdict=verdict,
            hotspot_lines=hotspot_lines,
        )

    def _call(self, prompt: str) -> str:
        models_to_try = [self._model, FALLBACK_MODEL]
        last_error = None
        for model in models_to_try:
            try:
                response = self._client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=self._config["temperature"],
                        max_output_tokens=self._config["max_output_tokens"],
                        safety_settings=self._config["safety_settings"],
                    ),
                )
                if not response.candidates:
                    raise ValueError("Gemini returned no candidates.")
                candidate = response.candidates[0]
                if candidate.finish_reason.name == "SAFETY":
                    raise ValueError(
                        "Respuesta bloqueada por filtros de seguridad. "
                        "Intenta reformular el problema."
                    )
                return response.text
            except Exception as e:
                if "503" in str(e) or "UNAVAILABLE" in str(e):
                    last_error = e
                    continue
                raise
        raise last_error

    def _first_comment(self, code: str, fallback: str = "") -> str:
        for line in code.splitlines():
            s = line.strip()
            if s.startswith("#") and len(s) > 2:
                return s.lstrip("#").strip()
        return fallback

def call_with_timeout(fn, *args, timeout: int = 60, **kwargs) -> Tuple[Optional[AnalysisResult], Optional[str]]:
    result_box: list = [None]
    error_box:  list = [None]

    def _target():
        try:
            result_box[0] = fn(*args, **kwargs)
        except Exception as exc:
            error_box[0] = f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        return None, f"Gemini timed out after {timeout}s."
    return result_box[0], error_box[0]