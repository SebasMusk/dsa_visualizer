"""
js_renderer.py - SVG/JS visualization engine for DSA Visualizer Engine

Generates a self-contained HTML string with:
  - All snapshots serialized to JSON at load time (no server round-trips)
  - Pure SVG renderers: array, grid, graph
  - In-place DOM updates -> CSS fill transitions animate smoothly
  - Client-side navigation: slider, Prev, Play/Pause (600ms), Next
  - Source code panel with active-line highlighting + syntax highlighting
"""
from __future__ import annotations

import json
import re
from collections import deque
from typing import Any, List, Optional

from tracker import Snapshot


# ── Serialization ──────────────────────────────────────────────────────────────

def _make_safe(obj: Any) -> Any:
    """Recursively convert Python types to JSON-safe values."""
    if isinstance(obj, bool):   return obj
    if isinstance(obj, float):
        if obj == float('inf'):  return '∞'
        if obj == float('-inf'): return '-∞'
        if obj != obj:           return 'NaN'
        return obj
    if isinstance(obj, int):    return obj
    if isinstance(obj, str):    return obj
    if isinstance(obj, dict):
        return {str(k): _make_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_safe(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        safe = [_make_safe(v) for v in obj]
        try:    return sorted(safe)
        except: return safe
    if isinstance(obj, deque):
        return [_make_safe(v) for v in obj]
    return str(obj)


def _utf16_offsets(text: str):
    """Map a Python (code-point) prefix length to a JS (UTF-16) prefix length."""
    if all(ord(c) <= 0xFFFF for c in text):
        return lambda n: min(n, len(text))
    acc = [0]
    for c in text:
        acc.append(acc[-1] + (2 if ord(c) > 0xFFFF else 1))
    return lambda n: acc[max(0, min(n, len(text)))]


def _serialize(snapshots: List[Snapshot], output: str = "") -> str:
    to_js = _utf16_offsets(output)
    data = []
    for s in snapshots:
        meta = {k: _make_safe(v) for k, v in s.metadata.items()
                if k not in ('line', 'source', 'out_len')}
        data.append({
            'step':       s.step,
            'label':      s.label,
            'variables':  _make_safe(s.variables),
            'highlights': _make_safe(s.highlights),
            'metadata': {
                'line':    s.metadata.get('line', 0),
                'source':  s.metadata.get('source', ''),
                'out_len': to_js(int(s.metadata.get('out_len', 0) or 0)),
                **meta,
            },
        })
    return _js_json(data)


def _js_json(obj: Any) -> str:
    """JSON safe to inline inside <script> (user text may contain '</script>')."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


# Height of the iframe that hosts the visualization (app.py uses it).
VIZ_IFRAME_HEIGHT = 860

_PLACEHOLDER = re.compile(r"/\*(SNAPSHOTS|SOURCE|HOTSPOTS|VERDICT|OUTPUT)\*/")


# ── Public API ─────────────────────────────────────────────────────────────────

def build_viz_html(
    snapshots: List[Snapshot],
    source_lines: Optional[List[str]] = None,
    hotspot_lines: Optional[list] = None,
    verdict: Optional[str] = None,
    output: str = "",
) -> str:
    """
    Return a self-contained HTML string for an iframe of height VIZ_IFRAME_HEIGHT.
    All snapshot data and the program's full stdout (`output`) are baked in;
    each snapshot's metadata.out_len says how much of it existed at that step.
    """
    values = {
        'SNAPSHOTS': _serialize(snapshots, output),
        'SOURCE':    _js_json(source_lines or []),
        'HOTSPOTS':  _js_json(hotspot_lines or []),
        'VERDICT':   _js_json(verdict or ""),
        'OUTPUT':    _js_json(output or ""),
    }
    # Single pass: injected data is never re-scanned for placeholders.
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], _HTML)


# ── HTML + JS template ─────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#141414;color:#d4d4d4;font-family:'JetBrains Mono','Fira Code',monospace;font-size:12px;overflow:hidden;height:100vh}
#app{display:flex;flex-direction:column;height:840px;padding:8px;gap:6px}
#badge{background:#1a1a1a;border-left:3px solid #00ff88;padding:5px 12px;border-radius:0 4px 4px 0;font-size:12px;color:#00ff88;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#main{display:flex;flex:1;gap:0;min-height:0}
#left{width:36%;display:flex;flex-direction:column;gap:0;min-height:0;overflow:hidden;border-right:1px solid #2d2d2d;padding-right:8px;margin-right:8px}
#code-wrap{background:#1c1c1c;border-radius:6px 6px 0 0;padding:8px 6px;overflow-y:auto;flex:1;min-height:0}
.cl{display:flex;padding:1px 0;line-height:1.5}
.cl.act{background:#2a2a2a;border-left:3px solid #00ff88;padding-left:5px}
.ln{color:#444;user-select:none;min-width:26px;text-align:right;padding-right:8px;flex-shrink:0;font-size:12px}
.ln.act{color:#00ff88;font-weight:bold}
.ls{color:#d4d4d4;white-space:pre;font-size:13px}
.ls.act{font-weight:bold}
.cl.hot{background:rgba(255,140,0,.12)}
.ln.hot{color:#ff8c00}
.ls.hot{color:#ff8c00}
#meta-wrap{background:#1a1a1a;border-top:1px solid #2d2d2d;border-radius:0 0 6px 6px;padding:8px;flex-shrink:0;max-height:130px;overflow-y:auto}
.sec-title{color:#555;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px}
.badges{display:flex;flex-wrap:wrap;gap:3px}
.badge{background:#1e1e1e;border:1px solid #333;border-radius:4px;padding:2px 6px;font-size:12px}
.bk{color:#f92672}.beq{color:#666}.bv{color:#e6db74}
.bprev{color:#666;font-size:11px}.bprev s{color:#888}
.badge.bchg{border-color:#e6db74}
.mr{font-size:12px;color:#888;margin-top:2px}
.mk{color:#ff8c00}.mv{color:#d4d4d4}
#right{flex:1;display:flex;flex-direction:column;gap:8px;min-height:0;overflow-y:auto;background:#141414}
.vwrap{background:#1a1a1a;border-radius:6px;padding:6px 8px;flex-shrink:0}
.vtitle{font-size:10px;color:#00ff88;margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px}
.vsvg{display:block;width:100%;overflow:visible}
.animfill{transition:fill .25s ease,stroke .25s ease}
.nodata{background:#1a1a1a;border-radius:6px;padding:20px;text-align:center;color:#444;font-size:11px;flex-shrink:0}
#badge.bfin{color:#00ff88;font-weight:bold}
#badge.berr{border-left-color:#f92672;color:#f92672;font-weight:bold}
#outwrap{position:relative;flex-shrink:0;height:72px;background:#0d0d0d;border:1px solid #2d2d2d;border-radius:6px;transition:border-color .2s}
#outwrap.fin{border-color:#00ff88}
#outwrap.finerr{border-color:#f92672}
#outlabel{position:absolute;top:4px;right:12px;font-size:10px;color:#555;text-transform:uppercase;letter-spacing:1px;pointer-events:none}
#outtext{height:100%;overflow-y:auto;padding:6px 90px 6px 10px;font-family:inherit;font-size:12px;line-height:1.45;white-space:pre-wrap;word-break:break-all}
.oold{color:#bdbdbd}.onew{color:#00ff88;font-weight:bold}.oph{color:#555;font-style:italic}.oerr{color:#f92672;font-weight:bold}
#ctrl{display:flex;align-items:center;gap:8px;flex-shrink:0;background:#0d0d0d;border-top:1px solid #1e1e1e;border-radius:6px;padding:6px 10px;height:52px}
.cbtn{background:transparent;color:#888;border:none;cursor:pointer;font-size:20px;transition:color .15s;flex-shrink:0;padding:4px 8px;line-height:1}
.cbtn:hover{color:#fff}
#slider{flex:1;accent-color:#00ff88;cursor:pointer}
#counter{color:#555;font-size:12px;min-width:60px;text-align:right;flex-shrink:0}
#btoggle{background:#00ff88;border:none;border-radius:4px;color:#0d0d0d;font-size:11px;font-family:inherit;font-weight:700;padding:4px 10px;cursor:pointer;flex-shrink:0;align-self:flex-end;margin-bottom:4px;transition:background .15s,transform .1s;letter-spacing:.5px}
#btoggle:hover{background:#00cc6e}
#btoggle:active{transform:scale(0.97)}
</style>
</head>
<body>
<div id="app">
  <div id="badge">Paso 1 → —</div>
  <div style="display:flex;justify-content:flex-end;flex-shrink:0">
    <button id="btoggle" onclick="toggleCode()">⟨ Ocultar código</button>
  </div>
  <div id="main">
    <div id="left">
      <div id="code-wrap"><em style="color:#444">Sin código fuente</em></div>
      <div id="meta-wrap">
        <div class="sec-title">Variables</div>
        <div id="scbadges" class="badges"></div>
        <div id="metaextra"></div>
      </div>
    </div>
    <div id="right"></div>
  </div>
  <div id="outwrap"><span id="outlabel">Salida</span><pre id="outtext"></pre></div>
  <div id="ctrl">
    <button class="cbtn" id="bprev">⏮</button>
    <button class="cbtn" id="bplay">▶</button>
    <button class="cbtn" id="bnext">⏭</button>
    <input type="range" id="slider" min="0" value="0">
    <span id="counter">1 / 1</span>
  </div>
</div>
<script>
const DATA     = /*SNAPSHOTS*/;
const SOURCE   = /*SOURCE*/;
const HOTSPOTS = /*HOTSPOTS*/;
const VERDICT  = /*VERDICT*/;
const OUTPUT   = /*OUTPUT*/;
const TOTAL  = DATA.length;
const NS     = 'http://www.w3.org/2000/svg';

const RC = {current:'#f92672',frontier:'#ff8c00',visited:'#00cc66',path:'#a6e22e',updated:'#e6db74'};
const DF = '#2d2d4e';
const RP = ['path','visited','frontier','updated','current'];

// ── Helpers ──────────────────────────────────────────────────────────────────
function detectType(v){
  if(v===null||v===undefined)return'scalar';
  const t=typeof v;
  if(t==='number'||t==='boolean'||t==='string')return'scalar';
  if(Array.isArray(v)){
    if(v.length>0&&v.length<=200&&
       v.every(x=>Array.isArray(x)&&x.every(n=>typeof n==='number'))&&
       looksLikeAdjList(v)){
      return'graph';
    }
    if(v.length>0&&Array.isArray(v[0]))return'grid';
    return'array';
  }
  if(t==='object'){
    const vals=Object.values(v);
    if(vals.length===0)return'graph';
    if(vals.every(x=>Array.isArray(x)))return'graph';
    if(vals.every(x=>x===null||typeof x==='number'||typeof x==='string'||typeof x==='boolean'))return'dict_scalar';
  }
  return'scalar';
}

// List of int-lists: adjacency list or numeric grid? Ragged rows → adjacency.
// Uniform rows → adjacency only if every row holds distinct valid node ids.
function looksLikeAdjList(v){
  const N=v.length;
  if(!v.every(r=>r.length===v[0].length))return true;
  return v.every(r=>new Set(r).size===r.length&&
                    r.every(n=>Number.isInteger(n)&&n>=0&&n<=N));
}

function getRole(hl,key){
  if(!hl)return null;
  for(const r of RP){
    for(const k of(hl[r]||[])){
      if(String(k)===String(key))return r;
    }
  }
  return null;
}

function hasRole(hl,key,role){
  return !!(hl&&(hl[role]||[]).some(k=>String(k)===String(key)));
}

function ptrLabel(hl,key){
  return (hl&&hl.labels&&hl.labels[String(key)])||'';
}

const QUEUE_NAMES=new Set(['queue','q','dq','deque']);
const STACK_NAMES=new Set(['stack','st']);

function roleColor(hl,key){
  if(!hl)return DF;
  for(const r of RP){
    for(const k of(hl[r]||[])){
      if(String(k)===String(key))return RC[r];
    }
  }
  return DF;
}

function svgEl(tag,attrs,txt){
  const el=document.createElementNS(NS,tag);
  for(const[k,v]of Object.entries(attrs))el.setAttribute(k,v);
  if(txt!==undefined)el.textContent=txt;
  return el;
}

function goc(parent,tag,id,attrs,txt){
  let el=document.getElementById(id);
  if(!el){el=document.createElementNS(NS,tag);el.id=id;parent.appendChild(el);}
  for(const[k,v]of Object.entries(attrs))el.setAttribute(k,v);
  if(txt!==undefined)el.textContent=txt;
  return el;
}

// ── Syntax highlighting ───────────────────────────────────────────────────────
function syntaxHL(line){
  const KW=new Set(['def','for','if','while','return','in','and','or','not','import','from','class','else','elif','True','False','None','pass','break','continue','lambda','yield','with','as','try','except','finally','raise','del','global','nonlocal','assert']);
  function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function sp(c,s){return '<span style="color:'+c+'">'+esc(s)+'</span>';}
  let r='',i=0;const n=line.length;
  while(i<n){
    if(line[i]==='#'){r+=sp('#6a9955',line.slice(i));break;}
    if(line[i]==='"'||line[i]==="'"){
      const q=line[i];let j=i+1;
      while(j<n&&line[j]!==q){if(line[j]==='\\')j++;j++;}
      j=Math.min(j+1,n);r+=sp('#ce9178',line.slice(i,j));i=j;continue;
    }
    if(/\d/.test(line[i])&&(i===0||/\W/.test(line[i-1]))){
      let j=i;while(j<n&&/[\d.]/.test(line[j]))j++;
      r+=sp('#b5cea8',line.slice(i,j));i=j;continue;
    }
    if(/[a-zA-Z_]/.test(line[i])){
      let j=i;while(j<n&&/[a-zA-Z0-9_]/.test(line[j]))j++;
      const w=line.slice(i,j);
      r+=KW.has(w)?sp('#569cd6',w):esc(w);
      i=j;continue;
    }
    r+=esc(line[i]);i++;
  }
  return r;
}

// ── renderArray (also queue / tuples / chars) ─────────────────────────────────
function renderArray(svg,name,val,hl,mode){
  mode=mode||'array';
  const MAX=50;
  const trunc=val.length>MAX;
  const cells=trunc?val.slice(0,MAX):val;
  const N=cells.length;
  const W=svg.clientWidth||400;
  const H=svg.clientHeight||140;

  if(parseInt(svg.dataset.n||'-1')!==N||svg.dataset.vt!==mode){
    svg.innerHTML='';svg.dataset.n=N;svg.dataset.vt=mode;
  }
  if(N===0){goc(svg,'text',name+'-empty',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#444','font-size':'11'},mode==='queue'?'[ cola vacía ]':'[ vacío ]');return;}

  const cw=Math.max(22,Math.min(72,(W-60)/N));
  const ch=mode==='chars'?40:56;
  const sx=Math.max(6,(W-N*cw)/2);
  const sy=(H-ch)/2-10;
  const fs=cw<36?10:12;
  const maxc=Math.max(2,Math.floor((cw-6)/7));

  for(let i=0;i<N;i++){
    const x=sx+i*cw;
    const role=getRole(hl,i);
    const isCur=hasRole(hl,i,'current');
    const fill=(role&&role!=='current')?RC[role]:'#00d4d4';
    const stroke=isCur?'#ff8c00':'none';
    const sw=isCur?'3':'0';
    const raw=Array.isArray(cells[i])?cells[i].join(','):String(cells[i]);
    const disp=raw.length>maxc?raw.slice(0,maxc-1)+'…':raw;
    const lbl=ptrLabel(hl,i);
    let top=String(i),topFill='#555';
    if(mode==='queue'){
      if(N===1){top='frente/final';topFill='#ff8c00';}
      else if(i===0){top='frente';topFill='#ff8c00';}
      else if(i===N-1&&!trunc){top='final';topFill='#ff8c00';}
    }

    const rect=goc(svg,'rect',name+'-r'+i,{x,y:sy+14,width:Math.max(2,cw-4),height:ch,rx:4,fill,stroke,'stroke-width':sw});
    rect.classList.add('animfill');
    goc(svg,'text',name+'-i'+i,{x:x+cw/2-1,y:sy+11,'text-anchor':'middle','font-size':top.length>3?'9':'10',fill:topFill},top);
    goc(svg,'text',name+'-v'+i,{x:x+cw/2-1,y:sy+14+ch/2+5,'text-anchor':'middle','font-size':fs,fill:'#111','font-weight':'bold'},disp);
    goc(svg,'text',name+'-ci'+i,{x:x+cw/2-1,y:sy+14+ch+14,'text-anchor':'middle','font-size':'10',fill:'#ff8c00','font-weight':'bold',opacity:lbl?'1':'0'},lbl);
  }
  if(trunc){
    goc(svg,'text',name+'-tr',{x:sx+N*cw+6,y:sy+14+ch/2+4,'font-size':'16',fill:'#00d4d4'},'…');
  }else{
    const old=document.getElementById(name+'-tr');if(old)old.remove();
  }
}

// ── renderStack (vertical, top of the stack drawn on top) ─────────────────────
function renderStack(svg,name,val,hl){
  const N=val.length;
  const W=svg.clientWidth||300;
  const H=svg.clientHeight||200;
  if(svg.dataset.vt!=='stack'||svg.dataset.n!==String(N)){
    svg.innerHTML='';svg.dataset.vt='stack';svg.dataset.n=String(N);
  }
  if(N===0){goc(svg,'text',name+'-empty',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#444','font-size':'11'},'[ pila vacía ]');return;}

  const rh=24;
  const vis=Math.min(N,Math.max(1,Math.floor((H-28)/rh)));
  const cw=Math.min(130,W*0.45);
  const sx=(W-cw)/2;
  for(let r=0;r<vis;r++){
    const i=N-1-r;
    const y=6+r*rh;
    const role=getRole(hl,i);
    const isCur=hasRole(hl,i,'current');
    const fill=(role&&role!=='current')?RC[role]:'#00d4d4';
    const raw=Array.isArray(val[i])?val[i].join(','):String(val[i]);
    const disp=raw.length>14?raw.slice(0,13)+'…':raw;
    const side=((r===0?'← tope ':'')+ptrLabel(hl,i)).trim();
    const rect=goc(svg,'rect',name+'-r'+r,{x:sx,y,width:cw,height:rh-3,rx:3,fill,stroke:isCur?'#ff8c00':'none','stroke-width':isCur?'3':'0'});
    rect.classList.add('animfill');
    goc(svg,'text',name+'-i'+r,{x:sx-8,y:y+rh/2+2,'text-anchor':'end','font-size':'10',fill:'#555'},i);
    goc(svg,'text',name+'-v'+r,{x:sx+cw/2,y:y+rh/2+2,'text-anchor':'middle','font-size':'12',fill:'#111','font-weight':'bold'},disp);
    goc(svg,'text',name+'-ci'+r,{x:sx+cw+8,y:y+rh/2+2,'font-size':'10',fill:'#ff8c00','font-weight':'bold',opacity:side?'1':'0'},side);
  }
  const more=N-vis;
  goc(svg,'text',name+'-more',{x:W/2,y:6+vis*rh+12,'text-anchor':'middle','font-size':'10',fill:'#555',opacity:more>0?'1':'0'},'… '+more+' más abajo');
}

// ── renderDictScalar ──────────────────────────────────────────────────────────
function renderDictScalar(svg,name,val,hl){
  const entries=Object.entries(val);
  const MAX=50;
  const trunc=entries.length>MAX;
  const cells=trunc?entries.slice(0,MAX):entries;
  const N=cells.length;
  const W=svg.clientWidth||400;
  const H=svg.clientHeight||140;

  if(svg.dataset.n!==String(N)||svg.dataset.vt!=='dict_scalar'){
    svg.innerHTML='';svg.dataset.n=String(N);svg.dataset.vt='dict_scalar';
  }
  if(N===0){goc(svg,'text',name+'-empty',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#444','font-size':'11'},'{ vacío }');return;}

  const cw=Math.max(48,Math.min(72,(W-60)/N));
  const ch=56;
  const sx=Math.max(6,(W-N*cw)/2);
  const sy=(H-ch)/2-10;

  for(let i=0;i<N;i++){
    const[k,v]=cells[i];
    const x=sx+i*cw;
    const role=getRole(hl,k);
    const isCur=hasRole(hl,k,'current');
    const fill=(role&&role!=='current')?RC[role]:(isCur?'#00d4d4':'#2d5a8e');
    const stroke=isCur?'#ff8c00':'none';
    const sw=isCur?'3':'0';
    const raw=v===null?'∅':String(v);
    const disp=raw==='Infinity'?'∞':(raw==='null'||raw==='undefined')?'∅':raw.length>5?raw.slice(0,4)+'…':raw;
    const vfill=(role&&role!=='current')||isCur?'#111':'#e6db74';
    const lbl=ptrLabel(hl,k);

    const rect=goc(svg,'rect',name+'-r'+i,{x,y:sy+14,width:Math.max(2,cw-4),height:ch,rx:4,fill,stroke,'stroke-width':sw});
    rect.classList.add('animfill');
    goc(svg,'text',name+'-k'+i,{x:x+cw/2-1,y:sy+11,'text-anchor':'middle','font-size':'9',fill:'#888'},k);
    goc(svg,'text',name+'-v'+i,{x:x+cw/2-1,y:sy+14+ch/2+5,'text-anchor':'middle','font-size':'11',fill:vfill,'font-weight':'bold'},disp);
    goc(svg,'text',name+'-ci'+i,{x:x+cw/2-1,y:sy+14+ch+14,'text-anchor':'middle','font-size':'10',fill:'#ff8c00','font-weight':'bold',opacity:lbl?'1':'0'},lbl);
  }
  if(trunc){
    goc(svg,'text',name+'-tr',{x:sx+N*cw+6,y:sy+14+ch/2+4,'font-size':'16',fill:'#00d4d4'},'…');
  }
}

// ── renderGrid ─────────────────────────────────────────────────────────────────
function renderGrid(svg,name,val,hl){
  const rows=val.length;
  const cols=rows>0?val[0].length:0;
  const W=svg.clientWidth||400;
  const H=svg.clientHeight||190;
  const key=rows+'x'+cols;

  if(svg.dataset.gk!==key||svg.dataset.vt!=='grid'){
    svg.innerHTML='';svg.dataset.gk=key;svg.dataset.vt='grid';
  }
  if(rows===0||cols===0)return;

  const hlMap={};
  for(const role of RP){
    for(const cell of(hl[role]||[])){
      if(Array.isArray(cell)&&cell.length>=2)hlMap[cell[0]+','+cell[1]]=RC[role];
    }
  }

  const cs=Math.max(8,Math.min(Math.floor((W-20)/cols),Math.floor((H-30)/rows),40));
  const sx=Math.max(4,(W-cols*cs)/2);
  const sy=Math.max(4,(H-rows*cs)/2);
  const fs=Math.max(7,Math.min(11,cs-4));

  for(let r=0;r<rows;r++){
    for(let c=0;c<cols;c++){
      const x=sx+c*cs;const y=sy+r*cs;
      const fill=hlMap[r+','+c]||'#1e3a5f';
      const raw=val[r][c];
      const disp=String(raw).slice(0,4);

      const rect=goc(svg,'rect',name+'-cr'+r+'-'+c,{x,y,width:cs-1,height:cs-1,fill,stroke:'#0a0a2a','stroke-width':'.5'});
      rect.classList.add('animfill');
      if(cs>=16)goc(svg,'text',name+'-cv'+r+'-'+c,{x:x+cs/2,y:y+cs/2+fs/3,'text-anchor':'middle','font-size':fs,fill:'#d4d4d4'},disp);
    }
  }
}

// ── renderGraph ────────────────────────────────────────────────────────────────
function renderGraph(svg,name,val,hl,weighted){
  if(Array.isArray(val)){
    const dict={};
    val.forEach((neighbors,i)=>{if(neighbors.length>0||i>0)dict[i]=neighbors;});
    val=dict;
  }
  const rawNodes=Object.keys(val);
  const N=rawNodes.length;
  const W=svg.clientWidth||400;
  const H=svg.clientHeight||270;

  if(N>20){
    svg.innerHTML='';
    svg.appendChild(svgEl('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#ff8c00','font-size':'12'},
      'Grafo demasiado grande ('+N+' nodos > 20)'));
    return;
  }
  if(N===0){
    svg.innerHTML='';
    svg.appendChild(svgEl('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#444','font-size':'11'},'Grafo vacío'));
    return;
  }

  const nodes=rawNodes.slice().sort((a,b)=>{
    const na=Number(a),nb=Number(b);
    if(!isNaN(na)&&!isNaN(nb))return na-nb;
    return a<b?-1:a>b?1:0;
  });
  const nodeKey=[...nodes].sort().join(',');

  const vt=weighted?'wgraph':'graph';
  if(svg.dataset.nk!==nodeKey||svg.dataset.vt!==vt){
    svg.innerHTML='';svg.dataset.nk=nodeKey;svg.dataset.vt=vt;
  }
  // Layers keep z-order stable even when edges appear after the nodes exist.
  const gE=goc(svg,'g',name+'-gE',{});
  const gW=goc(svg,'g',name+'-gW',{});
  const gN=goc(svg,'g',name+'-gN',{});

  const R=Math.min(W,H)/2-36;
  const cx=W/2,cy=H/2;
  const nr=Math.max(14,Math.min(22,R/Math.max(N,3)));

  const pos={};
  nodes.forEach((node,i)=>{
    const a=(2*Math.PI*i/N)-Math.PI/2;
    pos[node]={x:cx+R*Math.cos(a),y:cy+R*Math.sin(a)};
  });

  const nc={};
  for(const r of RP)for(const n of(hl[r]||[]))nc[String(n)]=RC[r];

  // Edges (weighted adjacency: neighbours are [v, w] pairs → label w on u→v)
  const edges=[];
  for(const[u,neighbors]of Object.entries(val)){
    for(const nb of neighbors){
      const pair=weighted&&Array.isArray(nb);
      const sv=String(pair?nb[0]:nb);
      if(!pos[u]||!pos[sv])continue;
      edges.push({u,v:sv,w:pair?nb[1]:null});
    }
  }
  const seen=new Map();
  for(const e of edges)seen.set(e.u+'>'+e.v,e.w);
  const placed=[];
  for(const e of edges){
    const rev=e.v+'>'+e.u;
    // u→v and v→u with the same weight = one undirected edge: draw it once.
    if(seen.has(rev)&&same(seen.get(rev),e.w)&&(e.v<e.u||(e.v===e.u)))continue;
    const a=pos[e.u],b=pos[e.v];
    goc(gE,'line',name+'-e-'+e.u+'-'+e.v,{
      x1:a.x,y1:a.y,x2:b.x,y2:b.y,
      stroke:'#3a3a5e','stroke-width':'1.5','stroke-linecap':'round',
    });
    if(e.w===null)continue;
    // Both directions with different weights: push each label to its own side.
    const both=seen.has(rev)&&!same(seen.get(rev),e.w);
    const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1;
    const off=both?10:0;
    const txt=String(e.w);
    const bw=Math.max(14,txt.length*7+6);
    // Slide the label along the edge until it doesn't cover another label or a node
    // (crossing edges share a midpoint in the circular layout).
    let mx=0,my=0;
    for(const t of[0.5,0.35,0.65,0.25,0.75,0.5]){
      mx=a.x+dx*t-dy/len*off;my=a.y+dy*t+dx/len*off;
      const hitsLabel=placed.some(q=>Math.abs(q.x-mx)<(q.w+bw)/2+2&&Math.abs(q.y-my)<17);
      const hitsNode=nodes.some(n=>Math.hypot(pos[n].x-mx,pos[n].y-my)<nr+8);
      if(!hitsLabel&&!hitsNode)break;
    }
    placed.push({x:mx,y:my,w:bw});
    goc(gW,'rect',name+'-ewb-'+e.u+'-'+e.v,{x:mx-bw/2,y:my-8,width:bw,height:15,rx:3,fill:'#141414',stroke:'#3a3a5e','stroke-width':'1'});
    goc(gW,'text',name+'-ew-'+e.u+'-'+e.v,{x:mx,y:my+3,'text-anchor':'middle','font-size':'10',fill:'#e6db74','font-weight':'bold'},txt);
  }

  // Nodes
  for(const node of nodes){
    const{x,y}=pos[node];
    const fill=nc[node]||DF;
    const nStroke=nc[node]||'#555';
    const lbl=String(node);
    const fs=lbl.length>2?9:11;

    const c=goc(gN,'circle',name+'-n-'+node,{cx:x,cy:y,r:nr,fill,stroke:nStroke,'stroke-width':'2'});
    c.classList.add('animfill');
    goc(gN,'text',name+'-nl-'+node,{x,y:y+fs/3,'text-anchor':'middle','font-size':fs,fill:'#fff','font-weight':'bold'},lbl);
  }
}

// ── Binary trees ──────────────────────────────────────────────────────────────
// Tree model: {nodes:[id], L:{id:child|null}, R:{id:child|null}, label:{id:text}}
function treeFromArrays(La,Ra,vals){
  const N=La.length;
  // 0 / -1 / None mean "no child" (0 can't be a child: it's the root or a sentinel)
  const child=x=>(isInt(x)&&x>0&&x<N)?String(x):null;
  const L={},R={},nodes=new Set(),label={};
  for(let i=0;i<N;i++){
    const l=child(La[i]),r=child(Ra[i]),k=String(i);
    L[k]=l;R[k]=r;
    if(l!==null||r!==null)nodes.add(k);
    if(l!==null)nodes.add(l);
    if(r!==null)nodes.add(r);
  }
  if(nodes.size===0)nodes.add(N>1?'1':'0');
  for(const k of nodes)label[k]=vals?String(vals[Number(k)]):k;
  return {nodes:[...nodes],L,R,label};
}

function treeFromDict(obj){
  const L={},R={},nodes=new Set(),label={};
  for(const[k,v]of Object.entries(obj)){
    const l=v[0]===null?null:String(v[0]),r=v[1]===null?null:String(v[1]);
    L[k]=l;R[k]=r;nodes.add(k);
    if(l!==null)nodes.add(l);
    if(r!==null)nodes.add(r);
  }
  for(const k of nodes)label[k]=k;
  return {nodes:[...nodes],L,R,label};
}

function renderBinTree(svg,name,t,hl){
  const W=svg.clientWidth||400;
  const H=svg.clientHeight||240;
  if(t.nodes.length>63){
    svg.innerHTML='';svg.dataset.tk='';
    svg.appendChild(svgEl('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'#ff8c00','font-size':'12'},
      'Árbol demasiado grande ('+t.nodes.length+' nodos > 63)'));
    return;
  }
  const nodeSet=new Set(t.nodes);
  const isChild=new Set();
  for(const n of t.nodes){if(t.L[n]!=null)isChild.add(t.L[n]);if(t.R[n]!=null)isChild.add(t.R[n]);}
  let roots=t.nodes.filter(n=>!isChild.has(n));
  if(!roots.length)roots=[t.nodes[0]];
  roots.sort((a,b)=>Number(a)-Number(b));

  // In-order x position, depth y position
  const order=[],depth={},seen=new Set();
  function walk(n,d){
    if(n==null||!nodeSet.has(n)||seen.has(n))return;
    seen.add(n);depth[n]=d;
    walk(t.L[n],d+1);order.push(n);walk(t.R[n],d+1);
  }
  for(const r of roots)walk(r,0);

  const edges=[];
  for(const n of order){
    for(const c of[t.L[n],t.R[n]])if(c!=null&&seen.has(c))edges.push([n,c]);
  }
  const tk=order.join(',')+'|'+edges.map(e=>e.join('-')).join(',');
  if(svg.dataset.tk!==tk||svg.dataset.vt!=='bintree'){
    svg.innerHTML='';svg.dataset.tk=tk;svg.dataset.vt='bintree';
  }
  const maxD=Math.max(0,...order.map(n=>depth[n]));
  const levelH=maxD?Math.min(56,(H-44)/maxD):0;
  const nr=Math.max(10,Math.min(16,(W-40)/order.length/2-2));
  const pos={};
  order.forEach((n,i)=>{pos[n]={x:20+(i+0.5)*(W-40)/order.length,y:22+depth[n]*levelH};});

  const nc={};
  for(const r of RP)for(const n of(hl[r]||[]))nc[String(n)]=RC[r];

  for(const[a,b]of edges){
    goc(svg,'line',name+'-te-'+a+'-'+b,{x1:pos[a].x,y1:pos[a].y,x2:pos[b].x,y2:pos[b].y,stroke:'#3a3a5e','stroke-width':'1.5'});
  }
  for(const n of order){
    const{x,y}=pos[n];
    const lbl=String(t.label[n]);
    const disp=lbl.length>4?lbl.slice(0,3)+'…':lbl;
    const c=goc(svg,'circle',name+'-tn-'+n,{cx:x,cy:y,r:nr,fill:nc[n]||DF,stroke:nc[n]||'#555','stroke-width':'2'});
    c.classList.add('animfill');
    goc(svg,'text',name+'-tl-'+n,{x,y:y+4,'text-anchor':'middle','font-size':disp.length>2?9:11,fill:'#fff','font-weight':'bold'},disp);
  }
}

// ── Type resolution: value shape + variable name + Python kind ────────────────
const TREE_NAMES=new Set(['tree','children','child','bt','arbol']);
const VALUE_NAMES=['val','vals','value','values','key','keys'];

function isTreeDict(name,v){
  const vals=Object.values(v);
  if(!vals.length)return false;
  if(!vals.every(x=>Array.isArray(x)&&x.length===2&&
                    x.every(c=>c===null||isInt(c)||typeof c==='string')))return false;
  return vals.some(x=>x.includes(null))||TREE_NAMES.has(name);
}

// {u: [(v, w), ...]} or [[(v, w), ...], ...] where every v is a node of the graph.
function isWeightedAdj(name,v,kinds){
  if(kinds[name]!=='weighted_adj')return false;
  const isArr=Array.isArray(v);
  const rows=isArr?v:Object.values(v);
  const keys=isArr?null:new Set(Object.keys(v));
  const ok=x=>Array.isArray(x)&&x.length===2&&
    (keys?keys.has(String(x[0])):(isInt(x[0])&&x[0]>=0&&x[0]<v.length));
  return rows.length>0&&rows.length<=200&&rows.every(r=>Array.isArray(r)&&r.every(ok));
}

function vizType(name,v,kinds){
  kinds=kinds||{};
  if(typeof v==='string')
    return(kinds[name]==='str'&&v.length>0&&v.length<=60)?'chars':'scalar';
  if(Array.isArray(v)){
    if(STACK_NAMES.has(name))return'stack';
    if(QUEUE_NAMES.has(name)||kinds[name]==='deque')return'queue';
    if(isWeightedAdj(name,v,kinds))return'graph';
    if(kinds[name]==='tuple_list'&&v.length>0&&
       v.every(x=>Array.isArray(x)&&x.every(y=>y===null||typeof y!=='object')))return'tuples';
    return detectType(v);
  }
  if(v&&typeof v==='object'&&isWeightedAdj(name,v,kinds))return'graph';
  if(v&&typeof v==='object'&&isTreeDict(name,v))return'bintree';
  return detectType(v);
}

const ARRAYISH=new Set(['array','queue','stack','tuples','chars']);
const isNodeRef=x=>x===null||isInt(x);

// One panel per structure; left/right (or l/r) arrays merge into one tree panel.
function buildPanels(vars,kinds,sizes){
  sizes=sizes||{};
  const panels=[],used=new Set();
  for(const[a,b]of[['left','right'],['l','r']]){
    const A=vars[a],B=vars[b];
    if(Array.isArray(A)&&Array.isArray(B)&&A.length===B.length&&A.length>1&&
       A.every(isNodeRef)&&B.every(isNodeRef)){
      const vals=VALUE_NAMES.map(n=>vars[n]).find(x=>Array.isArray(x)&&x.length===A.length);
      panels.push({name:'tree_'+a+'_'+b,title:'árbol ('+a+', '+b+')',type:'bintree',
                   val:treeFromArrays(A,B,vals)});
      used.add(a);used.add(b);
      break;
    }
  }
  for(const[name,val]of Object.entries(vars)){
    if(used.has(name))continue;
    const type=vizType(name,val,kinds);
    if(type==='scalar')continue;
    let v=val;
    if(type==='chars')v=Array.from(val);
    else if(type==='bintree')v=treeFromDict(val);
    const title=sizes[name]?name+' · '+sizes[name]+' elementos (se ven los primeros '+(Array.isArray(val)?val.length:Object.keys(val).length)+')':name;
    panels.push({name,title,type,val:v,
                 weighted:type==='graph'&&isWeightedAdj(name,val,kinds)});
  }
  return panels;
}

// ── Meta panel (scalars, with the previous value struck through) ──────────────
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function fmtScalar(v){
  if(v===null)return'None';
  if(v===true)return'True';
  if(v===false)return'False';
  if(typeof v==='string'){const t=v.length>40?v.slice(0,39)+'…':v;return"'"+t+"'";}
  if(typeof v==='object'){const t=JSON.stringify(v);return t.length>40?t.slice(0,39)+'…':t;}
  return String(v);
}

function renderMeta(variables,metadata,prevVars){
  const kinds=metadata.__kinds__||{};
  const sb=document.getElementById('scbadges');
  sb.innerHTML='';
  for(const[k,v]of Object.entries(variables)){
    if(vizType(k,v,kinds)!=='scalar')continue;
    const b=document.createElement('span');
    b.className='badge';
    let h='<span class="bk">'+esc(k)+'</span><span class="beq"> = </span><span class="bv">'+esc(fmtScalar(v))+'</span>';
    if(prevVars&&(k in prevVars)&&!same(prevVars[k],v)){
      h+=' <span class="bprev">(antes <s>'+esc(fmtScalar(prevVars[k]))+'</s>)</span>';
      b.classList.add('bchg');
    }
    b.innerHTML=h;
    sb.appendChild(b);
  }
  const me=document.getElementById('metaextra');
  me.innerHTML='';
  for(const[k,v]of Object.entries(metadata)){
    if(k==='line'||k==='source'||k==='__kinds__'||k==='__sizes__'||k==='out_len'||k==='final'||k==='error'||k==='error_msg')continue;
    const d=document.createElement('div');
    d.className='mr';
    const sv=JSON.stringify(v);
    d.innerHTML='<span class="mk">'+esc(k)+'</span>: <span class="mv">'+esc(sv.slice(0,60)+(sv.length>60?'…':''))+'</span>';
    me.appendChild(d);
  }
}

// ── Code panel (built once) ────────────────────────────────────────────────────
(function(){
  if(!SOURCE||!SOURCE.length)return;
  const w=document.getElementById('code-wrap');
  w.innerHTML='';
  SOURCE.forEach((line,i)=>{
    const div=document.createElement('div');div.className='cl';div.id='cl'+(i+1);
    const num=document.createElement('span');num.className='ln';num.id='ln'+(i+1);num.textContent=i+1;
    const src=document.createElement('span');src.className='ls';src.id='ls'+(i+1);
    src.innerHTML=syntaxHL(line);
    div.appendChild(num);div.appendChild(src);w.appendChild(div);
  });
})();

function highlightLine(n,hotspots){
  document.querySelectorAll('.cl.act,.ln.act,.ls.act').forEach(el=>el.classList.remove('act'));
  document.querySelectorAll('.cl.hot,.ln.hot,.ls.hot').forEach(el=>el.classList.remove('hot'));
  if(n){
    const cl=document.getElementById('cl'+n);
    const ln=document.getElementById('ln'+n);
    const ls=document.getElementById('ls'+n);
    if(cl){cl.classList.add('act');cl.scrollIntoView({block:'nearest',behavior:'smooth'});}
    if(ln)ln.classList.add('act');
    if(ls)ls.classList.add('act');
  }
  if(hotspots){
    for(const h of hotspots){
      const hl=document.getElementById('cl'+h);
      const hln=document.getElementById('ln'+h);
      const hls=document.getElementById('ls'+h);
      if(hl)hl.classList.add('hot');
      if(hln)hln.classList.add('hot');
      if(hls)hls.classList.add('hot');
    }
  }
}

// ── Toggle code panel ─────────────────────────────────────────────────────────
function toggleCode(){
  const left=document.getElementById('left');
  const btn=document.getElementById('btoggle');
  const hidden=left.style.display==='none';
  if(hidden){left.style.display='flex';btn.textContent='⟨ Ocultar código';}
  else{left.style.display='none';btn.textContent='⟩ Ver código';}
  renderStep(cur);   // panel width changed: re-layout the SVGs
}

// ── Viz panel ─────────────────────────────────────────────────────────────────
const TH={graph:275,grid:195,bintree:240};
const SH={stack:200};
const PRIMARY=new Set(['graph','grid','bintree']);
const rp=document.getElementById('right');

function makeWrap(p,height){
  const wrap=document.createElement('div');
  wrap.className='vwrap';wrap.id='vw-'+p.name;
  wrap.style.flexShrink='0';
  const title=document.createElement('div');
  title.className='vtitle';title.textContent=p.title;
  const svg=document.createElementNS(NS,'svg');
  svg.id='vs-'+p.name;svg.classList.add('vsvg');
  svg.style.height=height+'px';
  wrap.appendChild(title);wrap.appendChild(svg);
  return wrap;
}

function renderVizVars(snap,panels){
  const varKey=panels.map(p=>p.name+':'+p.type).join(',');

  if(rp.dataset.varkey!==varKey){
    rp.innerHTML='';
    rp.dataset.varkey=varKey;
    const primaries=panels.filter(p=>PRIMARY.has(p.type));
    const secondaries=panels.filter(p=>!PRIMARY.has(p.type));
    for(const p of primaries)rp.appendChild(makeWrap(p,TH[p.type]||275));
    if(secondaries.length>0){
      const grid=document.createElement('div');
      grid.id='secondary-grid';
      grid.style.cssText=secondaries.length===1
        ?'display:flex;flex-direction:column;gap:8px'
        :'display:grid;grid-template-columns:1fr 1fr;gap:8px';
      for(const p of secondaries)grid.appendChild(makeWrap(p,SH[p.type]||110));
      rp.appendChild(grid);
    }
    if(!panels.length){
      const nd=document.createElement('div');nd.id='nodata';nd.className='nodata';
      nd.textContent='Buscando estructuras de datos en este paso…';rp.appendChild(nd);
    }
  }

  for(const p of panels){
    const svg=document.getElementById('vs-'+p.name);
    if(!svg)continue;
    const hl=snap.highlights[p.name]||{};
    switch(p.type){
      case'array':case'tuples':case'chars':renderArray(svg,p.name,p.val,hl,p.type==='chars'?'chars':'array');break;
      case'queue':renderArray(svg,p.name,p.val,hl,'queue');break;
      case'stack':renderStack(svg,p.name,p.val,hl);break;
      case'dict_scalar':renderDictScalar(svg,p.name,p.val,hl);break;
      case'grid':renderGrid(svg,p.name,p.val,hl);break;
      case'graph':renderGraph(svg,p.name,p.val,hl,p.weighted);break;
      case'bintree':renderBinTree(svg,p.name,p.val,hl);break;
    }
  }
}

// ── Main render ───────────────────────────────────────────────────────────────
let cur=0,playing=false,timer=null;

function injectPathHighlights(snap){
  if(!snap.variables.path||!snap.variables.adj)return snap;
  const path=snap.variables.path;
  if(!Array.isArray(path)||path.length<2)return snap;
  const pathSet=new Set(path.map(String));
  if(!snap.highlights.adj)snap.highlights.adj={};
  snap.highlights.adj.path=[...pathSet];
  return snap;
}

// ── Automatic highlights (no AI): diffs, pointers, graph roles, grid cells ──
const PTR_NAMES=['i','j','k','l','r','lo','hi','mid','left','right','idx','pos','p','start','end','cur'];
const NODE_NAMES=['u','v','node','cur','curr','x','start','src'];
const VISITED_NAMES=['visited','seen','vis'];
const FRONTIER_NAMES=['queue','q','stack','pq','frontier','heap'];
const GRID_PAIRS=[['r','c','current'],['nr','nc','frontier'],['i','j','current'],
                  ['x','y','current'],['curr_r','curr_c','current']];

function isInt(x){return typeof x==='number'&&Number.isInteger(x);}
function same(a,b){return JSON.stringify(a)===JSON.stringify(b);}

function addHL(out,name,role,key){
  const h=out[name]||(out[name]={});
  const arr=h[role]||(h[role]=[]);
  if(!arr.some(k=>same(k,key)))arr.push(key);
}
function addLabel(out,name,key,label){
  const h=out[name]||(out[name]={});
  const L=h.labels||(h.labels={});
  const k=String(key);
  const parts=L[k]?L[k].split(','):[];
  if(!parts.includes(label))parts.push(label);
  L[k]=parts.join(',');
}

// Node ids (as strings) referenced by a visited / frontier container.
function nodesIn(val,kind,nNodes){
  if(Array.isArray(val)){
    if(kind!=='set'&&kind!=='deque'&&val.length>0){
      if(val.every(x=>typeof x==='boolean'))
        return val.map((x,i)=>x?String(i):null).filter(x=>x!==null);
      if(val.length>=nNodes&&val.every(x=>x===0||x===1))
        return val.map((x,i)=>x?String(i):null).filter(x=>x!==null);
    }
    return val.map(x=>Array.isArray(x)?(x.length?String(x[x.length-1]):null):String(x))
              .filter(x=>x!==null);
  }
  if(val&&typeof val==='object')
    return Object.entries(val).filter(([,v])=>v&&v!==-1).map(([k])=>k);
  return [];
}

// Indices of `cur` whose element is new w.r.t. `prev` (multiset diff) —
// for queues/sets, where a pop shifts every index.
function newElements(cur,prev){
  const cnt=new Map();
  for(const x of prev){const k=JSON.stringify(x);cnt.set(k,(cnt.get(k)||0)+1);}
  const out=[];
  cur.forEach((x,i)=>{const k=JSON.stringify(x);const c=cnt.get(k)||0;if(c>0)cnt.set(k,c-1);else out.push(i);});
  return out;
}

function autoHighlights(snap,prevSnap){
  const vars=snap.variables;
  const kinds=(snap.metadata&&snap.metadata.__kinds__)||{};
  const panels=buildPanels(vars,kinds);
  const prevPanels={};
  if(prevSnap){
    for(const p of buildPanels(prevSnap.variables,(prevSnap.metadata&&prevSnap.metadata.__kinds__)||{}))
      prevPanels[p.name]=p;
  }
  const out={};
  const scal={};
  for(const[k,v]of Object.entries(vars))if(isInt(v))scal[k]=v;

  for(const{name,type,val}of panels){
    const pp=prevPanels[name];

    if(ARRAYISH.has(type)){
      // 1. changed cells
      if(pp&&ARRAYISH.has(pp.type)){
        if(type==='queue'||kinds[name]==='set'){
          for(const i of newElements(val,pp.val))addHL(out,name,'updated',i);
        }else{
          for(let i=0;i<val.length;i++)
            if(i>=pp.val.length||!same(val[i],pp.val[i]))addHL(out,name,'updated',i);
        }
      }
      // 2. index pointers
      for(const p of PTR_NAMES){
        if(p in scal&&scal[p]>=0&&scal[p]<val.length){
          addHL(out,name,'current',scal[p]);addLabel(out,name,scal[p],p);
        }
      }
    }
    else if(type==='dict_scalar'){
      if(pp&&pp.type==='dict_scalar'){
        for(const[k,v]of Object.entries(val))
          if(!(k in pp.val)||!same(v,pp.val[k]))addHL(out,name,'updated',k);
      }
      for(const p of [...new Set([...PTR_NAMES,...NODE_NAMES])]){
        if(p in scal&&String(scal[p])in val){
          addHL(out,name,'current',String(scal[p]));addLabel(out,name,String(scal[p]),p);
        }
      }
    }
    else if(type==='grid'){
      const rows=val.length;
      if(pp&&pp.type==='grid'&&pp.val.length===rows){
        for(let r=0;r<rows;r++)for(let c=0;c<(val[r]||[]).length;c++)
          if(!pp.val[r]||!same(val[r][c],pp.val[r][c]))addHL(out,name,'updated',[r,c]);
      }
      for(const[a,b,role]of GRID_PAIRS){
        if(a in scal&&b in scal){
          const r=scal[a],c=scal[b];
          if(r>=0&&r<rows&&c>=0&&c<((val[r]||[]).length))addHL(out,name,role,[r,c]);
        }
      }
    }
    else if(type==='graph'||type==='bintree'){
      const keys=new Set(type==='bintree'?val.nodes
        :(Array.isArray(val)?val.map((_,i)=>String(i)):Object.keys(val)));
      for(const n of VISITED_NAMES){
        if(n in vars)for(const id of nodesIn(vars[n],kinds[n],keys.size))
          if(keys.has(id))addHL(out,name,'visited',id);
      }
      for(const n of FRONTIER_NAMES){
        if(n in vars&&Array.isArray(vars[n]))for(const id of nodesIn(vars[n],'deque',keys.size))
          if(keys.has(id))addHL(out,name,'frontier',id);
      }
      const curNames=type==='bintree'?[...NODE_NAMES,'i','idx']:NODE_NAMES;
      for(const n of curNames){
        if(n in scal&&keys.has(String(scal[n])))addHL(out,name,'current',String(scal[n]));
      }
    }
  }
  return out;
}

// Merge auto highlights into the snapshot's own, without overwriting them.
function mergeHL(base,auto){
  const out=JSON.parse(JSON.stringify(base||{}));
  for(const[name,roles]of Object.entries(auto)){
    const h=out[name]||(out[name]={});
    for(const[role,keys]of Object.entries(roles)){
      if(role==='labels'){h.labels=Object.assign({},keys,h.labels||{});continue;}
      const arr=h[role]||(h[role]=[]);
      for(const k of keys)if(!arr.some(x=>same(x,k)))arr.push(k);
    }
  }
  return out;
}

// ── Program output, synced with the current step ──────────────────────────────
function renderOutput(idx,s){
  const wrap=document.getElementById('outwrap');
  const pre=document.getElementById('outtext');
  const n=Math.min(OUTPUT.length,s.metadata.out_len||0);
  const p=idx>0?Math.min(n,DATA[idx-1].metadata.out_len||0):0;
  const fin=!!s.metadata.final,err=fin&&!!s.metadata.error;
  wrap.classList.toggle('fin',fin&&!err);
  wrap.classList.toggle('finerr',err);
  let h='';
  if(n>0)h='<span class="oold">'+esc(OUTPUT.slice(0,p))+'</span><span class="onew">'+esc(OUTPUT.slice(p,n))+'</span>';
  else if(!err)h='<span class="oph">(sin salida todavía)</span>';
  if(err)h+=(n>0&&!OUTPUT.slice(0,n).endsWith('\n')?'\n':'')+'<span class="oerr">✖ '+esc(s.metadata.error_msg||'Error')+'</span>';
  pre.innerHTML=h;
  pre.scrollTop=pre.scrollHeight;
}

function renderBadge(s){
  const b=document.getElementById('badge');
  const fin=!!s.metadata.final,err=fin&&!!s.metadata.error;
  b.classList.toggle('bfin',fin&&!err);
  b.classList.toggle('berr',err);
  if(fin)b.textContent='Fin del programa'+(err?' — ✖ '+(s.metadata.error_msg||'error'):'');
  else b.textContent='Paso '+(s.step+1)+' → '+(s.metadata.source||'—');
}

function renderStep(idx){
  if(idx<0)idx=0;if(idx>=TOTAL)idx=TOTAL-1;cur=idx;
  const base=DATA[idx];
  const prevSnap=idx>0?DATA[idx-1]:null;
  const s=injectPathHighlights(Object.assign({},base,{
    highlights:mergeHL(base.highlights,autoHighlights(base,prevSnap)),
  }));
  const panels=buildPanels(s.variables,s.metadata.__kinds__||{},s.metadata.__sizes__);
  renderBadge(s);
  renderOutput(idx,s);
  highlightLine(s.metadata.line||0,HOTSPOTS);
  renderMeta(s.variables,s.metadata,prevSnap?prevSnap.variables:null);
  renderVizVars(s,panels);
  document.getElementById('slider').value=idx;
  document.getElementById('counter').textContent=(idx+1)+' / '+TOTAL;
  document.getElementById('bplay').textContent=playing?'⏸':'▶';
}

function stopPlay(){playing=false;clearInterval(timer);timer=null;document.getElementById('bplay').textContent='▶';}
function startPlay(){
  playing=true;document.getElementById('bplay').textContent='⏸';
  timer=setInterval(()=>{if(cur>=TOTAL-1)stopPlay();else renderStep(cur+1);},600);
}

document.getElementById('bprev').onclick=()=>{stopPlay();renderStep(cur-1);};
document.getElementById('bnext').onclick=()=>{stopPlay();renderStep(cur+1);};
document.getElementById('bplay').onclick=()=>{
  if(playing)stopPlay();else{if(cur>=TOTAL-1)renderStep(0);startPlay();}
};
document.getElementById('slider').max=TOTAL-1;
document.getElementById('slider').oninput=e=>{stopPlay();renderStep(parseInt(e.target.value));};

renderStep(0);
</script>
</body>
</html>"""
