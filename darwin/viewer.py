"""Build a single, offline HTML page from a run directory.

  python run.py viewer                 # latest run
  python run.py viewer runs/<id>       # a specific run

The page needs no network and calls no model: it replays what the run
recorded (events.jsonl, lineage.json, final.json, orgs/*.yaml)."""
import glob
import json
import os

from . import org as orgmod

MAX_EVENTS = 40000


def _load_run(run_dir):
    def read_json(name, default):
        p = os.path.join(run_dir, name)
        try:
            with open(p) as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    orgs = {}
    for p in sorted(glob.glob(os.path.join(run_dir, "orgs", "*.yaml"))):
        try:
            o = orgmod.load(p)
            orgs[o["name"]] = o
        except Exception:
            continue

    events = []
    ev_path = os.path.join(run_dir, "events.jsonl")
    if os.path.exists(ev_path):
        with open(ev_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue  # a half-written last line from an interrupted run
                if len(events) >= MAX_EVENTS:
                    break

    lineage = read_json("lineage.json", [])
    compare = []
    for p in sorted(glob.glob(os.path.join(run_dir, "compare_*.json"))):
        try:
            compare += json.load(open(p))
        except (OSError, ValueError):
            pass
    if not lineage and compare:  # a compare run: show the orgs as one generation
        lineage = [{"name": c["org"], "gen": 0, "parent": None, "mutation": None, "kept": True,
                    "structure": orgmod.summary(orgs[c["org"]]) if c["org"] in orgs else "",
                    "score": c["score"], "solved": c["solved"], "runs": c["runs"],
                    "cost_usd": c["cost_usd"], "breakers": c.get("breakers", 0),
                    "errors": c.get("errors", 0)} for c in compare]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    splits = {os.path.basename(t): os.path.basename(os.path.dirname(t))
              for t in glob.glob(os.path.join(root, "tasks", "*", "*"))}
    return {
        "splits": splits,
        "meta": read_json("meta.json", {}),
        "lineage": lineage,
        "final": read_json("final.json", {}),
        "orgs": orgs,
        "events": events,
        "run": os.path.basename(os.path.normpath(run_dir)),
    }


def build(run_dir, out_path=None):
    data = _load_run(run_dir)
    if not data["orgs"]:
        raise SystemExit(f"no orgs found in {run_dir}/orgs; is this a Darwin run directory?")
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    three_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "three.min.js")
    three = ""
    if os.path.exists(three_path):
        with open(three_path) as f:
            three = f.read().replace("</script", "<\\/script")
    html = TEMPLATE.replace("/*__DATA__*/null", payload).replace("/*__THREE__*/", three)
    out_path = out_path or os.path.join(run_dir, "viewer.html")
    with open(out_path, "w") as f:
        f.write(html)
    return out_path


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Darwin Inc. run viewer</title>
<style>
:root{
  --bg:#f4f5f2; --panel:#ffffff; --ink:#15181c; --muted:#6b717a; --line:#dfe2dc;
  --green:#3f8f1e; --green-soft:#e6f2dd; --red:#c2410c; --red-soft:#fde8dc;
  --amber:#b7791f; --amber-soft:#fdf3d8; --blue:#1f5fa8; --blue-soft:#e3edf9;
  --violet:#6b46c1; --gray-soft:#eceee9; --node:#fbfcfa;
  --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#0f1214; --panel:#171b1e; --ink:#e8ebe6; --muted:#8c949c; --line:#2a3035;
    --green:#7cc85a; --green-soft:#1d2b17; --red:#f08a5d; --red-soft:#33201a;
    --amber:#e2b04a; --amber-soft:#2e2715; --blue:#6fa8e8; --blue-soft:#17243a;
    --violet:#a78bfa; --gray-soft:#22282c; --node:#1c2125; }
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px}
header{display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;padding:18px 24px 10px}
header h1{font-size:22px;margin:0;letter-spacing:-.01em}
header .tag{color:var(--muted)}
.badge{font-family:var(--mono);font-size:11px;padding:3px 8px;border-radius:999px;border:1px solid var(--line)}
.badge.live{background:var(--green-soft);color:var(--green);border-color:transparent}
.badge.mock{background:var(--amber-soft);color:var(--amber);border-color:transparent}
main{display:grid;grid-template-columns:minmax(320px,460px) 1fr;gap:16px;padding:0 24px 24px}
@media (max-width:980px){main{grid-template-columns:1fr;padding:0 16px 16px}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;min-width:0}
.panel h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 10px;font-weight:600}
.stack{display:flex;flex-direction:column;gap:16px;min-width:0}
svg text{font-family:var(--sans)}
#lineage{width:100%;display:block}
.lnode{cursor:pointer}
.lnode rect{stroke-width:1.5}
.lnode:hover rect{filter:brightness(.97)}
.lnode.sel rect{stroke:var(--ink)!important;stroke-width:2.5}
.legend{display:flex;gap:12px;flex-wrap:wrap;color:var(--muted);font-size:12px;margin-top:8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:-1px}
#orgTitle{font-size:18px;font-weight:650;margin:0}
#orgStruct{font-family:var(--mono);font-size:12px;color:var(--muted);margin:4px 0 0;word-break:break-word}
#orgWhy{margin:8px 0 0;font-size:13px}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0 6px}
select,button{font:inherit;color:var(--ink);background:var(--node);border:1px solid var(--line);border-radius:7px;padding:6px 10px}
button{cursor:pointer}
button.primary{background:var(--ink);color:var(--panel);border-color:var(--ink)}
#orgmapWrap{width:100%;overflow-x:auto}
#view3d{display:none;width:100%;height:520px;border-radius:10px;overflow:hidden;position:relative;background:#f2efe9;cursor:grab}
#view3d.on{display:block}
#view3d canvas{display:block}
#view3d .hint{position:absolute;right:10px;bottom:8px;font-size:11px;color:#6b717a;font-family:var(--mono);pointer-events:none}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:7px;overflow:hidden}
.seg button{border:0;border-radius:0;padding:6px 12px}
.seg button.on{background:var(--ink);color:var(--panel)}
#orgmap{display:block;min-width:560px}
.snode rect{fill:var(--node);stroke:var(--line);stroke-width:1.5;transition:fill .2s,stroke .2s}
.snode.active rect{fill:var(--blue-soft);stroke:var(--blue);stroke-width:2.5}
.snode.done rect{stroke:var(--green)}
.snode.alarm rect{fill:var(--red-soft);stroke:var(--red);stroke-width:2.5}
.snode .kind{font-family:var(--mono);font-size:10px;fill:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.snode .name{font-size:13px;font-weight:600;fill:var(--ink)}
.snode .chip{font-family:var(--mono);font-size:10px}
.lane rect{fill:none;stroke:var(--line);stroke-dasharray:4 4}
.lane text{font-size:11px;fill:var(--muted);font-family:var(--mono)}
.edge{stroke:var(--muted);stroke-width:1.5;fill:none}
.back{stroke:var(--red);stroke-width:1.4;fill:none;stroke-dasharray:5 4;opacity:.55}
.gov rect{fill:var(--gray-soft);stroke:var(--ink);stroke-width:1.5}
.gov.picked rect{fill:var(--green-soft);stroke:var(--green)}
.packet{fill:var(--blue)}
.packet.bad{fill:var(--red)}
#banner{min-height:28px;margin-top:8px;font-weight:600}
#banner.page{color:var(--red)}
#banner.good{color:var(--green)}
#ticker{font-family:var(--mono);font-size:12px;max-height:180px;overflow:auto;border-top:1px solid var(--line);margin-top:8px;padding-top:6px}
#ticker div{padding:2px 0;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#ticker div.hot{color:var(--ink)}
#ticker div.bad{color:var(--red)}
#ticker div.good{color:var(--green)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:1200px){.grid2{grid-template-columns:1fr}}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:13px}
.kv b{font-family:var(--mono);font-weight:600}
.bars .row{display:grid;grid-template-columns:150px 1fr 54px;gap:8px;align-items:center;margin:5px 0;font-size:12px}
.bars .row span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--mono)}
.bars .track{height:10px;background:var(--gray-soft);border-radius:5px;overflow:hidden}
.bars .fill{height:100%;background:var(--blue);border-radius:5px}
.bars .fill.champ{background:var(--green)}
.bars .fill.human{background:var(--violet)}
.bars .num{font-family:var(--mono);text-align:right}
.exam{display:flex;gap:18px;align-items:flex-end;flex-wrap:wrap}
.exam .col{text-align:center;min-width:120px}
.exam .big{font-size:34px;font-weight:700;font-family:var(--mono);letter-spacing:-.02em}
.exam .lbl{color:var(--muted);font-size:12px}
.exam .nm{font-family:var(--mono);font-size:12px;margin-top:2px}
.empty{color:var(--muted);font-style:italic}
footer{color:var(--muted);font-size:12px;padding:0 24px 24px}
</style>
</head>
<body>
<header>
  <h1>Darwin Inc.</h1>
  <span class="tag">Human org charts are generation zero.</span>
  <span id="mode" class="badge"></span>
  <span id="runid" class="badge"></span>
</header>
<main>
  <div class="stack">
    <section class="panel">
      <h2>Evolution lineage</h2>
      <svg id="lineage" role="img" aria-label="Lineage of organizations across generations"></svg>
      <div class="legend">
        <span><i style="background:var(--violet)"></i>human seed</span>
        <span><i style="background:var(--green)"></i>kept mutant</span>
        <span><i style="background:var(--gray-soft);border:1px solid var(--line)"></i>discarded</span>
        <span>★ champion</span>
      </div>
    </section>
    <section class="panel">
      <h2>Held-out exam</h2>
      <div id="exam"></div>
    </section>
  </div>
  <div class="stack">
    <section class="panel">
      <h2>Organization</h2>
      <p id="orgTitle"></p>
      <p id="orgStruct"></p>
      <p id="orgWhy"></p>
      <div class="controls">
        <label for="taskSel" class="tag">Task</label>
        <select id="taskSel"></select>
        <button id="play" class="primary">▶ Replay</button>
        <button id="step">Step</button>
        <label class="tag" for="speed">Speed</label>
        <select id="speed"><option value="900">slow</option><option value="450" selected>normal</option><option value="160">fast</option></select>
        <span class="seg" role="group" aria-label="View"><button id="b2d" class="on">2D</button><button id="b3d">3D</button></span>
      </div>
      <div id="orgmapWrap"><svg id="orgmap" role="img" aria-label="Organization map"></svg></div>
      <div id="view3d"><span class="hint">drag to orbit · scroll to zoom</span></div>
      <div id="banner"></div>
      <div id="ticker"></div>
    </section>
    <div class="grid2">
      <section class="panel">
        <h2>Scorecard (train)</h2>
        <div id="card"></div>
      </section>
      <section class="panel">
        <h2>Per task (hidden tests)</h2>
        <div id="pertask" class="bars"></div>
      </section>
    </div>
  </div>
</main>
<footer id="foot"></footer>

<script id="data" type="application/json">/*__DATA__*/null</script>
<script>/*__THREE__*/</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const NS = "http://www.w3.org/2000/svg";
const $ = id => document.getElementById(id);
const fmt = (x, d = 3) => (x == null || isNaN(x)) ? "–" : Number(x).toFixed(d);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}
function txt(parent, x, y, s, cls, anchor) {
  const t = el("text", {x, y, class: cls || "", "text-anchor": anchor || "start"}, parent);
  t.textContent = s; return t;
}

// ------------------------------------------------------------- header
const live = (D.meta && D.meta.mode) === "live";
$("mode").textContent = live ? "LIVE · Crusoe + Nemotron" : (D.meta && D.meta.mode === "mock" ? "MOCK DATA · not results" : "run");
$("mode").className = "badge " + (live ? "live" : "mock");
$("runid").textContent = D.run || "";
$("foot").textContent = (D.meta && D.meta.worker_model ? `worker ${D.meta.worker_model} · meta ${D.meta.meta_model} · ` : "")
  + `${D.events.length} recorded events · replay only, no model calls`;

// ------------------------------------------------------------- lineage
const L = D.lineage || [];
const byName = Object.fromEntries(L.map(n => [n.name, n]));
const finalInfo = D.final || {};
const champion = finalInfo.champion || (L.length ? [...L].filter(n => n.kept).sort((a, b) => b.score - a.score || a.cost_usd - b.cost_usd)[0]?.name : null);
const bestHuman = finalInfo.best_human || null;

function shortName(n) { const i = n.indexOf("~"); return i < 0 ? n : n.slice(i + 1); }
function mutLabel(m) {
  if (!m) return "";
  const bits = [m.op];
  for (const k of ["team", "stage", "by", "n", "rule"]) if (m[k] != null && m[k] !== "") bits.push(["n","by","rule"].includes(k) ? `${k}=${m[k]}` : m[k]);
  return bits.join(" ");
}

let selected = null;
function fit(str, px, charPx) { const n = Math.max(3, Math.floor(px / charPx)); return str.length > n ? str.slice(0, n - 1) + "…" : str; }
function drawLineage() {
  const svg = $("lineage"); svg.innerHTML = "";
  if (!L.length) { svg.setAttribute("height", 40); txt(svg, 4, 24, "no lineage in this run", "empty"); return; }
  const gens = [...new Set(L.map(n => n.gen))].sort((a, b) => a - b);
  const W = svg.clientWidth || 400, gap = 14;
  const colW = (W - 8) / gens.length, nodeW = colW - gap, rowH = 42, nodeH = 32;
  // order: gen 0 as given; later gens sorted by their parent's row, so edges run straight
  const row = {}, cols = {};
  for (const g of gens) {
    let items = L.filter(n => n.gen === g);
    if (g !== gens[0]) items.sort((a, b) => (row[a.parent] ?? 99) - (row[b.parent] ?? 99) || (a.name < b.name ? -1 : 1));
    items.forEach((n, i) => row[n.name] = i);
    cols[g] = items;
  }
  const maxRows = Math.max(...gens.map(g => cols[g].length));
  const H = maxRows * rowH + 24;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("height", H);
  const pos = {};
  gens.forEach((g, gi) => {
    txt(svg, gi * colW + 4, 12, g === 0 ? "gen 0 · human" : `gen ${g}`).setAttribute("style", "font-size:11px;fill:var(--muted);font-family:var(--mono)");
    cols[g].forEach((n, ri) => { pos[n.name] = {x: gi * colW + 4, y: 20 + ri * rowH}; });
  });
  for (const n of L) {
    if (!n.parent || !pos[n.parent] || !pos[n.name]) continue;
    const a = pos[n.parent], b = pos[n.name];
    const x1 = a.x + nodeW, y1 = a.y + nodeH / 2, x2 = b.x, y2 = b.y + nodeH / 2, mx = (x1 + x2) / 2;
    el("path", {d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, class: "edge",
      style: n.kept ? "stroke:var(--green);opacity:.85" : "opacity:.3"}, svg);
  }
  for (const n of L) {
    const p = pos[n.name]; if (!p) continue;
    const g = el("g", {class: "lnode" + (n.name === selected ? " sel" : ""), transform: `translate(${p.x},${p.y})`, tabindex: 0}, svg);
    const seed = n.gen === 0;
    const fill = seed ? "var(--violet)" : n.kept ? "var(--green-soft)" : "var(--gray-soft)";
    const stroke = seed ? "var(--violet)" : n.kept ? "var(--green)" : "var(--line)";
    el("rect", {width: nodeW, height: nodeH, rx: 7, fill, stroke}, g);
    const ink = seed ? "#fff" : (n.kept ? "var(--ink)" : "var(--muted)");
    const label = (n.name === champion ? "★ " : "") + (seed ? n.name.replace(/_/g, " ") : shortName(n.name) + (n.mutation ? " " + n.mutation.op.replace(/_/g, " ") : ""));
    const t1 = txt(g, 7, 13, fit(label, nodeW - 12, 6.6));
    t1.setAttribute("style", `font-size:11.5px;font-weight:600;fill:${ink}`);
    const t2 = txt(g, 7, 26, fit(`${fmt(n.score)} · $${fmt(n.cost_usd, 4)}`, nodeW - 12, 6));
    t2.setAttribute("style", `font-size:10px;font-family:var(--mono);fill:${ink};opacity:.85`);
    const tt = el("title", {}, g);
    tt.textContent = `${n.name}\n${n.structure || ""}${n.mutation ? `\n${mutLabel(n.mutation)} (${n.kept ? "kept" : "discarded"})` : ""}`;
    g.addEventListener("click", () => selectOrg(n.name));
    g.addEventListener("keydown", e => { if (e.key === "Enter") selectOrg(n.name); });
  }
}

// ------------------------------------------------------------- exam
function drawExam() {
  const box = $("exam"); const rows = (finalInfo.heldout || []);
  if (!rows.length) { box.innerHTML = `<p class="empty">No held-out exam in this run yet.</p>`; return; }
  const col = c => {
    const role = c.org === champion && c.org !== bestHuman ? "evolved champion" : c.org === bestHuman ? "best human org" : c.org === "flat_startup" ? "baseline" : "";
    const color = role === "evolved champion" ? "var(--green)" : role === "best human org" ? "var(--violet)" : "var(--muted)";
    return `<div class="col"><div class="big" style="color:${color}">${fmt(c.score, 2)}</div>
      <div class="lbl">${esc(role)}</div><div class="nm">${esc(c.org)}</div>
      <div class="lbl">$${fmt(c.cost_usd, 4)} · ${c.solved}/${c.runs} solved</div></div>`;
  };
  box.innerHTML = `<div class="exam">${rows.map(col).join("")}</div>
    <p class="tag" style="margin:10px 0 0">Scored on tasks evolution never saw.</p>`;
}

// ------------------------------------------------------------- org map
const EV = D.events || [];
const evByOrg = {};
for (const e of EV) { if (e.org && e.task && e.task !== "*") (evByOrg[e.org] ||= []).push(e); }

const KIND = {spec: "definition of done", plan: "direction", implement: "build", select: "pick", review: "review", verify: "run tests"};
let layout = null;

function chips(s) {
  const c = [];
  if ((s.parallel || 1) > 1) c.push(`×${s.parallel}`);
  if (s.kind === "review" && (s.voters || 1) > 1) c.push(`panel ${s.voters} ${s.rule === "unanimous" ? "unan." : "maj."}`);
  if (s.blind) c.push("blind");
  if (s.search) c.push("search");
  if (s.kind === "review" && s.can_veto === false) c.push("no veto");
  return c.join(" · ");
}

function drawOrg(o) {
  const svg = $("orgmap"); svg.innerHTML = "";
  const teams = o.teams, multi = teams.length > 1, router = multi && o.decide.by === "router";
  const nodeW = 132, nodeH = 52, gapX = 34, laneH = 104, padL = router ? 110 : 18, top = 44;
  const maxStages = Math.max(...teams.map(t => t.stages.length));
  const govX = padL + maxStages * (nodeW + gapX) + 10;
  const W = govX + (multi ? 230 : 20), H = top + teams.length * laneH + 10;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("width", W); svg.setAttribute("height", H);
  const defs = el("defs", {}, svg);
  const mk = el("marker", {id: "arr", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse"}, defs);
  el("path", {d: "M0,0 L10,5 L0,10 z", fill: "var(--muted)"}, mk);
  const nodes = {}, lanes = {};
  teams.forEach((t, ti) => {
    const y = top + ti * laneH;
    const lane = el("g", {class: "lane"}, svg);
    el("rect", {x: padL - 10, y: y - 18, width: maxStages * (nodeW + gapX) - gapX + 20, height: nodeH + 30, rx: 10}, lane);
    txt(lane, padL - 4, y - 5, multi ? `${t.name}${t.isolated ? " · isolated" : ""}${t.focus ? " · " + t.focus.slice(0, 48) : ""}` : (o.shared_memory ? "shared memory" : ""));
    lanes[t.name] = {y, x0: padL, x1: padL + t.stages.length * (nodeW + gapX) - gapX};
    t.stages.forEach((s, si) => {
      const x = padL + si * (nodeW + gapX);
      if (si > 0) el("line", {x1: x - gapX, y1: y + nodeH / 2, x2: x - 2, y2: y + nodeH / 2, class: "edge", "marker-end": "url(#arr)"}, svg);
      const g = el("g", {class: "snode", transform: `translate(${x},${y})`}, svg);
      el("rect", {width: nodeW, height: nodeH, rx: 8}, g);
      txt(g, 10, 15, KIND[s.kind] || s.kind, "kind");
      txt(g, 10, 32, s.id.length > 17 ? s.id.slice(0, 16) + "…" : s.id, "name");
      const c = chips(s); if (c) { const ct = txt(g, 10, 45, c, "chip"); ct.setAttribute("fill", "var(--blue)"); }
      nodes[`${t.name}::${s.id}`] = {g, x, y, cx: x + nodeW / 2, cy: y + nodeH / 2};
    });
    for (const s of t.stages) {
      const tgt = s.on_reject || s.on_fail; if (!tgt) continue;
      const a = nodes[`${t.name}::${s.id}`], b = nodes[`${t.name}::${tgt}`]; if (!a || !b) continue;
      const dist = Math.abs(a.cx - b.cx) / (nodeW + gapX), lift = 10 + 7 * dist;
      el("path", {d: `M${a.cx - 8},${a.y} C${a.cx - 8},${a.y - lift} ${b.cx + 8},${b.y - lift} ${b.cx + 8},${b.y}`, class: "back"}, svg);
    }
  });
  let gov = null, rtr = null;
  if (multi) {
    const gy = top + (teams.length - 1) * laneH / 2;
    if (router) {
      rtr = el("g", {class: "gov", transform: `translate(6,${gy})`}, svg);
      el("rect", {width: 88, height: nodeH, rx: 8}, rtr);
      txt(rtr, 44, 22, "router", "", "middle").setAttribute("style", "font-weight:600;font-size:13px;fill:var(--ink)");
      txt(rtr, 44, 38, "assigns one", "", "middle").setAttribute("style", "font-size:10px;fill:var(--muted)");
      for (const t of teams) el("line", {x1: 94, y1: gy + nodeH / 2, x2: padL - 4, y2: lanes[t.name].y + nodeH / 2, class: "edge", "marker-end": "url(#arr)"}, svg);
    } else {
      gov = el("g", {class: "gov", transform: `translate(${govX},${gy})`}, svg);
      el("rect", {width: 210, height: nodeH, rx: 8}, gov);
      const label = {tests: "tests decide", leader: "leader decides", council: `council of ${o.decide.voters}`}[o.decide.by] || o.decide.by;
      txt(gov, 105, 22, label, "", "middle").setAttribute("style", "font-weight:600;font-size:13px;fill:var(--ink)");
      gov.vote = txt(gov, 105, 38, "", "", "middle"); gov.vote.setAttribute("style", "font-size:10px;font-family:var(--mono);fill:var(--muted)");
      for (const t of teams) el("line", {x1: lanes[t.name].x1 + 2, y1: lanes[t.name].y + nodeH / 2, x2: govX - 4, y2: gy + nodeH / 2, class: "edge", "marker-end": "url(#arr)"}, svg);
    }
  }
  layout = {svg, nodes, gov, rtr, teams, multi, defaultTeam: teams[0].name, nodeH,
            nodeW, gapX, laneH, padL, top, govX, W, H, router};
  if (V3.on) V3.build(o);
}


// ------------------------------------------------------------- 3D floor
const V3 = {
  on: false, ok: typeof THREE !== "undefined", scene: null, renderer: null, camera: null,
  stations: {}, packets: [], gov: null, rtr: null, raf: 0, org: null,
  init() {
    if (this.renderer || !this.ok) return;
    const box = $("view3d");
    try {
      this.renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
    } catch (err) { this.ok = false; return; }
    this.renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure = 1.0;
    box.prepend(this.renderer.domElement);
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 500);
    this.orbit = {theta: -0.55, phi: 0.95, r: 60, tx: 0, tz: 0};
    let drag = null;
    const cv = this.renderer.domElement;
    cv.addEventListener("pointerdown", e => { drag = {x: e.clientX, y: e.clientY}; cv.setPointerCapture(e.pointerId); box.style.cursor = "grabbing"; });
    cv.addEventListener("pointerup", e => { drag = null; box.style.cursor = "grab"; });
    cv.addEventListener("pointermove", e => { if (!drag) return;
      this.orbit.theta -= (e.clientX - drag.x) * 0.006; this.orbit.phi = Math.min(1.45, Math.max(0.25, this.orbit.phi - (e.clientY - drag.y) * 0.005));
      drag = {x: e.clientX, y: e.clientY}; });
    cv.addEventListener("wheel", e => { e.preventDefault(); this.orbit.r = Math.min(160, Math.max(15, this.orbit.r * (1 + e.deltaY * 0.001))); }, {passive: false});
    addEventListener("resize", () => this.resize());
  },
  resize() {
    if (!this.renderer) return;
    const box = $("view3d"), w = box.clientWidth || 800, h = box.clientHeight || 440;
    this.renderer.setSize(w, h, false); this.renderer.domElement.style.width = w + "px"; this.renderer.domElement.style.height = h + "px";
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  },
  label(text, sub, color) {
    const c = document.createElement("canvas"); c.width = 512; c.height = 150;
    const g = c.getContext("2d");
    g.shadowColor = "rgba(0,0,0,0.12)"; g.shadowBlur = 14; g.shadowOffsetY = 4;
    g.fillStyle = "rgba(255,255,255,0.96)"; g.beginPath(); g.roundRect(12, 10, 488, 118, 40); g.fill();
    g.shadowColor = "transparent"; g.strokeStyle = color || "rgba(21,24,28,0.10)"; g.lineWidth = 3; g.stroke();
    g.fillStyle = "#15181c"; g.font = "650 50px -apple-system, Segoe UI, Inter, sans-serif"; g.textAlign = "center";
    g.fillText(text.length > 17 ? text.slice(0, 16) + "…" : text, 256, sub ? 66 : 84);
    if (sub) { g.fillStyle = "#7a7f86"; g.font = "500 30px -apple-system, Segoe UI, Inter, sans-serif"; g.fillText(sub.slice(0, 30), 256, 108); }
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({map: tex, depthTest: false, transparent: true}));
    sp.scale.set(3.6, 1.06, 1); sp.renderOrder = 10; return sp;
  },
  rrect(w, h, r) {
    const s = new THREE.Shape(), x = -w / 2, y = -h / 2; r = Math.min(r, w / 2, h / 2);
    s.moveTo(x + r, y); s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
    s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
    s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y); return s;
  },
  slab(w, d, t, color, opts = {}) {
    const g = new THREE.ExtrudeGeometry(this.rrect(w, d, opts.r ?? 0.35), {depth: t, bevelEnabled: true, bevelThickness: 0.04, bevelSize: 0.04, bevelSegments: 2, curveSegments: 10});
    g.rotateX(-Math.PI / 2);
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({color, roughness: opts.rough ?? .7, metalness: opts.metal ?? 0, transparent: !!opts.opacity, opacity: opts.opacity ?? 1}));
    m.castShadow = !opts.flat; m.receiveShadow = true; return m;
  },
  // An original Darwin agent: capsule body, round head, glowing visor.
  agent(color, opts = {}) {
    const g = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({color, roughness: .45, metalness: .05});
    const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.34, 0.5, 6, 18), bodyMat);
    body.position.y = 0.75; body.castShadow = true; g.add(body);
    const belly = new THREE.Mesh(new THREE.SphereGeometry(0.2, 18, 12), new THREE.MeshStandardMaterial({color: 0xffffff, roughness: .6}));
    belly.scale.set(1, 1.15, .45); belly.position.set(0, 0.68, 0.27); g.add(belly);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.33, 28, 20), new THREE.MeshStandardMaterial({color: 0xf5f3ee, roughness: .35}));
    head.position.y = 1.52; head.castShadow = true; g.add(head);
    const visorMat = new THREE.MeshStandardMaterial({color: 0x1b2430, emissive: color, emissiveIntensity: .35, roughness: .2, metalness: .3});
    const visor = new THREE.Mesh(new THREE.CapsuleGeometry(0.1, 0.32, 4, 12), visorMat);
    visor.rotation.z = Math.PI / 2; visor.position.set(0, 1.55, 0.28); visor.scale.set(1, 1, .55); g.add(visor);
    if (opts.blind) {
      const band = new THREE.Mesh(new THREE.TorusGeometry(0.335, 0.075, 10, 40), new THREE.MeshStandardMaterial({color: 0x23262b, roughness: .8}));
      band.rotation.x = Math.PI / 2; band.position.y = 1.56; g.add(band); visor.visible = false;
    }
    const ant = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.22, 6), new THREE.MeshStandardMaterial({color: 0x9aa19a}));
    ant.position.y = 1.94; g.add(ant);
    const tip = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8), visorMat); tip.position.y = 2.07; g.add(tip);
    for (const sx of [-1, 1]) {
      const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.08, 0.32, 4, 8), bodyMat);
      arm.position.set(sx * 0.42, 0.82, 0.08); arm.rotation.z = sx * 0.35; arm.rotation.x = -0.5; arm.castShadow = true; g.add(arm);
    }
    if (opts.prop === "clipboard") {
      const cb = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.44, 0.04), new THREE.MeshStandardMaterial({color: 0xb98a55, roughness: .8}));
      cb.position.set(0.18, 0.9, 0.42); cb.rotation.x = -0.5; g.add(cb);
      const paper = new THREE.Mesh(new THREE.BoxGeometry(0.28, 0.34, 0.01), new THREE.MeshStandardMaterial({color: 0xffffff}));
      paper.position.set(0.18, 0.9, 0.445); paper.rotation.x = -0.5; g.add(paper);
    }
    if (opts.prop === "magnifier") {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.14, 0.025, 8, 24), new THREE.MeshStandardMaterial({color: 0x30343a, metalness: .6, roughness: .3}));
      ring.position.set(0.42, 1.12, 0.4); g.add(ring);
      const lens = new THREE.Mesh(new THREE.CircleGeometry(0.13, 20), new THREE.MeshStandardMaterial({color: 0xbfe3ff, transparent: true, opacity: .45}));
      lens.position.copy(ring.position); g.add(lens);
    }
    if (opts.crown) {
      const c = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.24, 0.14, 6, 1, true), new THREE.MeshStandardMaterial({color: 0xe0b23a, metalness: .7, roughness: .3, side: THREE.DoubleSide}));
      c.position.y = 1.86; g.add(c);
    }
    g.userData = {visorMat, tip, baseY: 0};
    return g;
  },
  screen(w, h) {
    const mat = new THREE.MeshStandardMaterial({color: 0x0e1620, emissive: 0x2a4a70, emissiveIntensity: .25, roughness: .2, metalness: .2, transparent: true, opacity: .9, side: THREE.DoubleSide});
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
    return {m, mat};
  },
  build(o) {
    this.init(); if (!this.ok) return;
    this.org = o; this.stations = {}; this.packets = []; this.checks = [];
    const S = 0.026, SZ = 0.088; // svg px -> world units: ~4.3 units between stations, ~7 between team lanes
    const scene = new THREE.Scene(); this.scene = scene;
    { const c = document.createElement("canvas"); c.width = 4; c.height = 256; const g = c.getContext("2d");
      const gr = g.createLinearGradient(0, 0, 0, 256); gr.addColorStop(0, "#fbfaf7"); gr.addColorStop(1, "#ebe6dd");
      g.fillStyle = gr; g.fillRect(0, 0, 4, 256); const tx = new THREE.CanvasTexture(c); tx.colorSpace = THREE.SRGBColorSpace; scene.background = tx; }
    scene.fog = new THREE.Fog(0xece7de, 60, 150);
    scene.add(new THREE.HemisphereLight(0xfffaf2, 0xb8b2a6, 1.35));
    const sun = new THREE.DirectionalLight(0xfff4e6, 2.4);
    sun.position.set(-14, 30, 18); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.radius = 4; Object.assign(sun.shadow.camera, {left: -50, right: 50, top: 50, bottom: -50, near: 1, far: 100});
    sun.shadow.bias = -0.0005; sun.shadow.normalBias = 0.02; scene.add(sun);
    const fill = new THREE.DirectionalLight(0xdfe8ff, 0.6); fill.position.set(20, 12, -10); scene.add(fill);
    const floor = new THREE.Mesh(new THREE.CircleGeometry(160, 64), new THREE.MeshStandardMaterial({color: 0xe9e5dd, roughness: .95}));
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);

    const L = layout, cx = (L.W * S) / 2, cz = (L.H * SZ) / 2;
    const P = (x, y) => new THREE.Vector3(x * S - cx, 0, y * SZ - cz);
    const KCOL = {spec: 0x7c5cd6, plan: 0x2f7fd0, implement: 0x3f9b3a, select: 0xd09a2a, review: 0xd2603a, verify: 0x1f9a8a};
    const RUG = [0xdfe9f5, 0xe2efd9, 0xf6ead1, 0xece2f6];
    const DESK = 0xcaa27a, BENCH = 0x6b5a4b;

    L.teams.forEach((t, ti) => {
      const y = L.top + ti * L.laneH + L.nodeH / 2;
      const x0 = L.padL - 10, w = t.stages.length * (L.nodeW + L.gapX) - L.gapX + 20;
      const rug = this.slab(w * S + 1.6, 5.0, 0.06, RUG[ti % RUG.length], {r: 0.9, flat: true, rough: 1});
      rug.position.copy(P(x0 + w / 2, y)); scene.add(rug);
      if (t.isolated) {
        const glass = new THREE.Mesh(new THREE.BoxGeometry(w * S + 2.2, 1.4, 5.6),
          new THREE.MeshStandardMaterial({color: 0xb9a6f0, transparent: true, opacity: .16, roughness: .1, metalness: .1, depthWrite: false}));
        glass.position.copy(P(x0 + w / 2, y)); glass.position.y = 0.7; scene.add(glass);
        const edge = new THREE.LineSegments(new THREE.EdgesGeometry(glass.geometry), new THREE.LineBasicMaterial({color: 0x7c5cd6, transparent: true, opacity: .7}));
        edge.position.copy(glass.position); scene.add(edge);
      }
      if (L.multi && !(t.stages.length === 1 && t.stages[0].id === t.name)) { const tl = this.label(t.name, t.isolated ? "isolated · skunkworks" : (t.focus ? "division" : "team"), "#bdb6aa");
        tl.position.copy(P(x0, y)); tl.position.x -= 3.0; tl.position.z += 1.6; tl.position.y = 0.6; tl.scale.set(3.4, 1.0, 1); scene.add(tl); }

      t.stages.forEach((s, si) => {
        const x = L.padL + si * (L.nodeW + L.gapX) + L.nodeW / 2;
        const grp = new THREE.Group(); grp.position.copy(P(x, y));
        const color = KCOL[s.kind] || 0x888888;
        const n = Math.min(5, s.kind === "implement" ? (s.parallel || 1) : s.kind === "review" ? (s.voters || 1) : 1);
        const spread = n > 1 ? 0.95 : 0, deskW = Math.max(2.2, n * 0.95 + 0.6);
        // furniture
        if (s.kind === "review") {
          const bench = this.slab(deskW, 0.8, 0.72, BENCH, {r: 0.15, rough: .6}); bench.position.set(0, 0, 0.8); grp.add(bench);
        } else if (s.kind === "implement" || s.kind === "select") {
          const top = this.slab(deskW, 1.0, 0.1, DESK, {r: 0.12, rough: .55}); top.position.set(0, 0.78, 0.7); grp.add(top);
          for (const lx of [-deskW / 2 + 0.15, deskW / 2 - 0.15]) for (const lz of [0.32, 1.08]) {
            const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.78, 8), new THREE.MeshStandardMaterial({color: 0x5b5148}));
            leg.position.set(lx, 0.39, lz); grp.add(leg);
          }
        } else if (s.kind === "verify") {
          const rig = this.slab(1.6, 0.9, 0.9, 0x3a4048, {r: 0.12, metal: .4, rough: .4}); rig.position.set(0.9, 0, 0.2); grp.add(rig);
          const bar = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.12, 0.05), new THREE.MeshStandardMaterial({color: 0x3f9b3a, emissive: 0x3f9b3a, emissiveIntensity: .8}));
          bar.position.set(0.9, 0.75, 0.66); grp.add(bar);
        } else if (s.kind === "spec" || s.kind === "plan") {
          const board = new THREE.Mesh(new THREE.BoxGeometry(1.8, 1.2, 0.06), new THREE.MeshStandardMaterial({color: 0xfafafa, roughness: .5}));
          board.position.set(0.9, 1.5, -0.55); board.castShadow = true; grp.add(board);
          for (let k = 0; k < 4; k++) { const ln = new THREE.Mesh(new THREE.BoxGeometry(1.2 - k * 0.18, 0.05, 0.01), new THREE.MeshStandardMaterial({color}));
            ln.position.set(0.8, 1.85 - k * 0.22, -0.515); grp.add(ln); }
          for (const lx of [0.15, 1.65]) { const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 1.0, 6), new THREE.MeshStandardMaterial({color: 0x6b6f75}));
            leg.position.set(lx, 0.5, -0.55); grp.add(leg); }
        }
        // agents
        const figs = [];
        for (let k = 0; k < n; k++) {
          const a = this.agent(color, {blind: !!s.blind, prop: s.kind === "spec" ? "clipboard" : s.kind === "review" ? "magnifier" : null});
          a.position.set((k - (n - 1) / 2) * spread - (s.kind === "spec" || s.kind === "plan" || s.kind === "verify" ? 0.5 : 0), 0, 0);
          if (n > 1) a.scale.setScalar(0.88);
          grp.add(a); figs.push(a);
          if (s.kind === "implement") {
            const lap = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.03, 0.32), new THREE.MeshStandardMaterial({color: 0x2b2f35, metalness: .5, roughness: .3}));
            lap.position.set(a.position.x, 0.9, 0.62); grp.add(lap);
            const lid = new THREE.Mesh(new THREE.BoxGeometry(0.46, 0.3, 0.02), new THREE.MeshStandardMaterial({color: 0x2b2f35, emissive: color, emissiveIntensity: .25, metalness: .4}));
            lid.position.set(a.position.x, 1.05, 0.47); lid.rotation.x = -0.25; grp.add(lid);
          }
        }
        // holographic status screen
        const sc = this.screen(Math.min(1.6, Math.max(1.1, deskW * 0.55)), 0.5); sc.m.position.set(0, 2.55, 0.1); grp.add(sc.m);
        const frame = new THREE.Mesh(new THREE.BoxGeometry(sc.m.geometry.parameters.width + 0.08, 0.58, 0.03), new THREE.MeshStandardMaterial({color: 0x2b2f35, metalness: .4, roughness: .4}));
        frame.position.set(0, 2.55, 0.08); grp.add(frame);
        const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 2.2, 6), new THREE.MeshStandardMaterial({color: 0x8a8f96})); pole.position.set(0, 1.4, 0.05);
        if (s.kind !== "implement" && s.kind !== "review") grp.add(pole);
        if (s.search) { const globe = new THREE.Mesh(new THREE.IcosahedronGeometry(0.22, 1), new THREE.MeshStandardMaterial({color: 0x6e44ff, emissive: 0x6e44ff, emissiveIntensity: .6, wireframe: true}));
          globe.position.set(deskW / 2 + 0.2, 2.6, 0.2); grp.add(globe); grp.userData.globe = globe; }
        const sub = [{spec: "definition of done", plan: "direction", implement: "build", select: "pick best", review: "review", verify: "run tests"}[s.kind] || s.kind,
                     (s.parallel || 1) > 1 ? `×${s.parallel} clones` : "", s.kind === "review" && (s.voters || 1) > 1 ? `panel of ${s.voters}` : "",
                     s.blind ? "blind" : "", s.search ? "You.com" : ""].filter(Boolean).join(" · ");
        const lb = this.label(s.id, sub); lb.position.set(0, 3.45, 0.1); grp.add(lb);
        scene.add(grp);
        this.stations[`${t.name}::${s.id}`] = {grp, figs, screen: sc.mat, pos: grp.position.clone()};
      });
      for (let si = 1; si < t.stages.length; si++) {
        const a = this.stations[`${t.name}::${t.stages[si - 1].id}`].pos, b = this.stations[`${t.name}::${t.stages[si].id}`].pos;
        this.floorLine(a, b, 0xb3ab9e);
      }
      for (const s of t.stages) { const tgt = s.on_reject || s.on_fail; if (!tgt) continue;
        const a = this.stations[`${t.name}::${s.id}`], b = this.stations[`${t.name}::${tgt}`]; if (a && b) this.arc(a.pos, b.pos, 0xd2603a, 0.5); }
    });

    this.gov = null; this.rtr = null;
    const hub = (pos, text, sub, kind) => {
      const g = new THREE.Group(); g.position.copy(pos);
      const base = new THREE.Mesh(new THREE.CylinderGeometry(2.3, 2.5, 0.25, 48), new THREE.MeshStandardMaterial({color: 0xd9d3c8, roughness: .7}));
      base.position.y = 0.12; base.receiveShadow = true; base.castShadow = true; g.add(base);
      const mat = new THREE.MeshStandardMaterial({color: 0xbfb6a6, roughness: .5, emissive: 0x000000});
      const figs = [];
      if (kind === "council") {
        const table = new THREE.Mesh(new THREE.CylinderGeometry(1.0, 1.0, 0.12, 40), mat); table.position.y = 0.95; table.castShadow = true; g.add(table);
        const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.2, 0.8, 12), new THREE.MeshStandardMaterial({color: 0x5b5148})); stem.position.y = 0.5; g.add(stem);
        const nv = Math.min(7, o.decide.voters || 3);
        for (let k = 0; k < nv; k++) { const ang = (k / nv) * Math.PI * 2 + Math.PI / 2;
          const a = this.agent(0x8f6bd8); a.scale.setScalar(0.82); a.position.set(Math.cos(ang) * 1.55, 0.25, Math.sin(ang) * 1.55);
          a.lookAt(new THREE.Vector3(pos.x, a.position.y, pos.z).sub(pos).add(new THREE.Vector3(0, 0, 0)));
          a.rotation.y = Math.atan2(-a.position.x, -a.position.z); g.add(a); figs.push(a); }
      } else if (kind === "leader") {
        const pod = this.slab(1.3, 1.0, 1.1, 0x6b5a4b, {r: 0.15}); pod.position.set(0, 0.25, 0.7); g.add(pod);
        const a = this.agent(0xe0b23a, {crown: true}); a.position.y = 0.25; g.add(a); figs.push(a);
      } else if (kind === "router") {
        const a = this.agent(0x2f7fd0); a.position.y = 0.25; g.add(a); figs.push(a);
        for (const sx of [-1, 1]) { const cone = new THREE.Mesh(new THREE.ConeGeometry(0.18, 0.5, 12), new THREE.MeshStandardMaterial({color: 0x2f7fd0, emissive: 0x2f7fd0, emissiveIntensity: .4}));
          cone.rotation.x = sx * Math.PI / 2; cone.position.set(0.9, 1.4, sx * 0.5); g.add(cone); }
      } else { // tests decide: an oracle
        const orb = new THREE.Mesh(new THREE.OctahedronGeometry(0.7, 0), new THREE.MeshStandardMaterial({color: 0x3f9b3a, emissive: 0x3f9b3a, emissiveIntensity: .45, roughness: .2, metalness: .2, flatShading: true}));
        orb.position.y = 1.6; orb.castShadow = true; g.add(orb); g.userData.spin = orb;
      }
      const lb = this.label(text, sub); lb.position.y = 3.2; g.add(lb); scene.add(g);
      return {grp: g, mat, figs, pos: pos.clone()};
    };
    if (L.multi) {
      const gy = L.top + (L.teams.length - 1) * L.laneH / 2 + L.nodeH / 2;
      if (L.router) {
        this.rtr = hub(P(-60, gy), "router", "assigns one division", "router");
        for (const t of L.teams) { const st = this.stations[`${t.name}::${t.stages[0].id}`]; if (st) this.floorLine(this.rtr.pos, st.pos, 0xb3ab9e); }
      } else {
        const by = o.decide.by;
        const label = {tests: "tests decide", leader: "leader decides", council: `council of ${o.decide.voters}`}[by] || by;
        this.gov = hub(P(L.govX + 40, gy), label, "governance", by);
        for (const t of L.teams) { const st = this.stations[`${t.name}::${t.stages[t.stages.length - 1].id}`]; if (st) this.floorLine(st.pos, this.gov.pos, 0xb3ab9e); }
      }
    }
    // Fit any org: distance from the footprint's width and depth for this view's aspect ratio.
    const box = $("view3d"), aspect = (box.clientWidth || 800) / (box.clientHeight || 520);
    const t = Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2);
    const wide = (L.W * S + 4) / (2 * t * aspect), deep = (L.H * SZ + 4) / (2 * t);
    this.orbit.r = Math.min(150, Math.max(12, Math.max(wide, deep * 0.85) * 1.08 + 3));
    this.orbit.tx = 0; this.orbit.tz = 0.4; this.orbit.theta = -0.26;
    this.orbit.phi = L.teams.length > 2 ? 0.72 : L.multi ? 0.82 : 0.98;
    this.resize(); this.reset(); this.loop();
  },
  floorLine(a, b, color) {
    const g = new THREE.BufferGeometry().setFromPoints([a.clone().setY(0.15), b.clone().setY(0.15)]);
    this.scene.add(new THREE.Line(g, new THREE.LineBasicMaterial({color})));
  },
  arc(a, b, color, opacity) {
    const mid = a.clone().lerp(b, .5); mid.y = 4.5 + a.distanceTo(b) * 0.25;
    const curve = new THREE.QuadraticBezierCurve3(a.clone().setY(3.4), mid, b.clone().setY(3.4));
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(40)),
      new THREE.LineDashedMaterial({color, dashSize: .5, gapSize: .35, transparent: true, opacity}));
    line.computeLineDistances(); this.scene.add(line);
  },
  packet(fromKey, toKey, bad, fromPos) {
    const a = fromPos || this.stations[fromKey]?.pos, b = this.stations[toKey]?.pos || (toKey === "#gov" && this.gov?.pos);
    if (!a || !b) return;
    const col = bad ? 0xd2603a : 0x2f7fd0;
    const m = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.04, 0.72),
      new THREE.MeshStandardMaterial({color: 0xffffff, emissive: col, emissiveIntensity: bad ? .9 : .55, roughness: .4}));
    m.castShadow = true; this.scene.add(m);
    const mid = a.clone().lerp(b, .5); mid.y = bad ? 5.5 + a.distanceTo(b) * .22 : 2.8;
    const curve = new THREE.QuadraticBezierCurve3(a.clone().setY(bad ? 2.6 : 1.3), mid, b.clone().setY(bad ? 2.6 : 1.3));
    this.packets.push({m, curve, t0: performance.now(), dur: Math.max(260, +$("speed").value * .9), spin: (Math.random() - .5) * 6});
  },
  state(key, kind) {
    const st = this.stations[key]; if (!st) return;
    const C = {active: [0x6fb6ff, 1.2, 0x2f7fd0, .9], done: [0x5fd06a, .7, 0x3f9b3a, .6], alarm: [0xff6a3d, 1.4, 0xd2603a, 1.1], idle: [null, .35, 0x2a4a70, .25]}[kind];
    for (const f of st.figs) { const u = f.userData; if (C[0] != null) u.visorMat.emissive.setHex(C[0]); else u.visorMat.emissive.setHex(u.base ?? (u.base = u.visorMat.emissive.getHex()));
      if (u.base == null) u.base = u.visorMat.emissive.getHex();
      if (kind === "idle") u.visorMat.emissive.setHex(u.base);
      u.visorMat.emissiveIntensity = C[1]; u.busy = kind === "active"; u.sad = kind === "alarm"; }
    st.screen.emissive.setHex(C[2]); st.screen.emissiveIntensity = C[3];
  },
  reset() { for (const k of Object.keys(this.stations)) this.state(k, "idle");
    if (this.gov) { this.gov.mat.emissive.setHex(0x000000); }
    for (const p of this.packets) this.scene.remove(p.m); this.packets = []; },
  key(e, role) { return `${e.team || layout.defaultTeam}::${role}`; },
  event(e) {
    if (!this.scene) return;
    switch (e.type) {
      case "stage_start": this.state(this.key(e, e.role), "active"); break;
      case "stage_end": this.state(this.key(e, e.role), e.result === "next" ? "done" : "alarm"); break;
      case "handoff": this.packet(this.key(e, e.from), this.key(e, e.to)); break;
      case "reject": case "fail": this.state(this.key(e, e.from), "alarm"); this.packet(this.key(e, e.from), this.key(e, e.to), true); break;
      case "loop_detected": this.state(this.key(e, e.role), "alarm"); break;
      case "route": if (this.rtr) { const t = layout.teams.find(t => t.name === e.to); if (t) this.packet(null, `${t.name}::${t.stages[0].id}`, false, this.rtr.pos); } break;
      case "decision": if (this.gov) { this.gov.mat.emissive.setHex(0x3f9b3a); this.gov.mat.emissiveIntensity = .5;
        const t = layout.teams.find(t => t.name === e.picked); if (t) this.packet(`${t.name}::${t.stages[t.stages.length - 1].id}`, "#gov"); } break;
    }
  },
  loop() {
    cancelAnimationFrame(this.raf);
    const frame = now => {
      if (!this.on) return;
      const o = this.orbit, c = this.camera;
      c.position.set(o.tx + o.r * Math.sin(o.phi) * Math.sin(o.theta), o.r * Math.cos(o.phi), o.tz + o.r * Math.sin(o.phi) * Math.cos(o.theta));
      c.lookAt(o.tx, 1.5, o.tz);
      for (const st of Object.values(this.stations)) {
        st.figs.forEach((f, i) => { const u = f.userData;
          const target = u.busy ? 0.12 + 0.1 * Math.abs(Math.sin(now / 140 + i)) : 0.02 * Math.sin(now / 700 + i * 1.7);
          f.position.y += (target - f.position.y) * 0.25;
          f.rotation.z = u.sad ? 0.08 * Math.sin(now / 90) : f.rotation.z * 0.85; });
        if (st.grp.userData.globe) st.grp.userData.globe.rotation.y = now / 900;
      }
      for (const h of [this.gov, this.rtr]) if (h && h.grp.userData.spin) { h.grp.userData.spin.rotation.y = now / 700; h.grp.userData.spin.position.y = 1.6 + 0.12 * Math.sin(now / 500); }
      this.packets = this.packets.filter(p => {
        const k = Math.min(1, (now - p.t0) / p.dur), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        p.m.position.copy(p.curve.getPoint(e)); p.m.rotation.y = p.spin * e; p.m.rotation.x = 0.3 * Math.sin(e * Math.PI);
        if (k >= 1) { this.scene.remove(p.m); return false; } return true;
      });
      this.renderer.render(this.scene, c);
      this.raf = requestAnimationFrame(frame);
    };
    this.raf = requestAnimationFrame(frame);
  },
  setOn(on) {
    if (on && !this.ok) { $("b3d").disabled = true; $("b3d").title = "3D needs WebGL, which is not available here"; return; }
    this.on = on;
    $("view3d").classList.toggle("on", on); $("orgmapWrap").style.display = on ? "none" : "";
    $("b3d").classList.toggle("on", on); $("b2d").classList.toggle("on", !on);
    if (on && selected) { this.build(D.orgs[selected]); if (!this.ok) { this.setOn(false); return; }
      for (let i = 0; i < qi; i++) this.event(queue[i]); }
    else cancelAnimationFrame(this.raf);
  },
};
$("b2d").addEventListener("click", () => V3.setOn(false));
$("b3d").addEventListener("click", () => V3.setOn(true));
if (!V3.ok) { $("b3d").disabled = true; $("b3d").title = "3D unavailable"; }

// ------------------------------------------------------------- replay
let timer = null, queue = [], qi = 0;
function nodeFor(e, role) { return layout.nodes[`${e.team || layout.defaultTeam}::${role}`]; }
function tick(msg, cls) {
  const d = document.createElement("div"); d.textContent = msg; d.className = cls || "";
  $("ticker").prepend(d);
}
function packet(from, to, bad) {
  if (!from || !to) return;
  const c = el("circle", {r: 6, cx: from.cx, cy: from.cy, class: "packet" + (bad ? " bad" : "")}, layout.svg);
  const dur = Math.max(140, +$("speed").value * .8), t0 = performance.now();
  const lift = bad ? -40 : 0;
  (function step(now) {
    const k = Math.min(1, (now - t0) / dur), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    const x = from.cx + (to.cx - from.cx) * e, y = from.cy + (to.cy - from.cy) * e + lift * Math.sin(Math.PI * e);
    c.setAttribute("cx", x); c.setAttribute("cy", y);
    if (k < 1) requestAnimationFrame(step); else c.remove();
  })(t0);
}
function clearMarks() {
  if (!layout) return;
  for (const n of Object.values(layout.nodes)) n.g.classList.remove("active", "done", "alarm");
  if (layout.gov) { layout.gov.classList.remove("picked"); layout.gov.vote.textContent = ""; }
  $("banner").textContent = ""; $("banner").className = ""; $("ticker").innerHTML = "";
  if (V3.on) V3.reset();
}
function apply(e) {
  if (V3.on) V3.event(e);
  const who = e.team ? `${e.team}/` : "";
  switch (e.type) {
    case "start": tick(`start · ${e.task}`, "hot"); break;
    case "route": { const lane = layout.nodes[`${e.to}::${layout.teams.find(t => t.name === e.to)?.stages[0].id}`];
      if (layout.rtr && lane) packet({cx: 50, cy: +layout.rtr.getAttribute("transform").match(/,(\d+\.?\d*)/)[1] + layout.nodeH / 2}, lane);
      tick(`router → ${e.to}`, "hot"); break; }
    case "stage_start": { const n = nodeFor(e, e.role); if (n) { n.g.classList.remove("done"); n.g.classList.add("active"); } break; }
    case "stage_end": { const n = nodeFor(e, e.role); if (n) { n.g.classList.remove("active"); if (e.result === "next") n.g.classList.add("done"); }
      const extra = e.tests != null ? ` (${e.tests} tests)` : e.candidates != null ? ` (${e.candidates} candidates)` :
        e.voters > 1 ? ` (${e.approvals}/${e.voters} approve)` : e.passed != null ? ` (${e.passed}/${e.total})` : "";
      tick(`${who}${e.role} → ${e.result}${extra}`, e.result === "next" ? "" : "bad"); break; }
    case "handoff": packet(nodeFor(e, e.from), nodeFor(e, e.to)); break;
    case "reject": case "fail": {
      const a = nodeFor(e, e.from), b = nodeFor(e, e.to); packet(a, b, true);
      if (a) a.g.classList.add("alarm");
      tick(`${who}${e.from} sent back to ${e.to}: ${(e.reason || "").slice(0, 90)}`, "bad"); break; }
    case "loop_detected": { const n = nodeFor(e, e.role); if (n) n.g.classList.add("alarm");
      tick(`${who}loop detected: resubmitted earlier work`, "bad"); break; }
    case "breaker": tick(`${who}circuit breaker: ${e.why || ""} → ${e.action}`, "bad"); break;
    case "page_human": $("banner").textContent = `⚠ Paged a human: ${e.why || ""}`; $("banner").className = "page"; tick(`${who}PAGED A HUMAN`, "bad"); break;
    case "search": tick(`${who}${e.role} searched You.com${e.hits ? "" : " (no results)"}`); break;
    case "decision": if (layout.gov) { layout.gov.classList.add("picked");
        layout.gov.vote.textContent = fit(e.votes ? "votes " + Object.entries(e.votes).map(([k, v]) => `${k}:${v}`).join(" ") : `picked ${e.picked}`, 200, 6); }
      tick(`decision by ${e.by}: ${e.picked}`, "hot"); break;
    case "done": {
      const ok = e.score >= 1;
      if (!$("banner").textContent || ok) { $("banner").textContent = `${ok ? "✓" : "•"} Hidden tests ${fmt(e.score, 2)} · ${e.outcome} · ${e.rounds} send-backs · $${fmt(e.cost_usd, 4)}`; $("banner").className = ok ? "good" : ""; }
      tick(`done · hidden score ${fmt(e.score, 2)} · ${e.outcome}`, ok ? "good" : "hot"); break; }
  }
}
function stop() { if (timer) clearInterval(timer); timer = null; $("play").textContent = "▶ Replay"; }
function load() { stop(); clearMarks(); const task = $("taskSel").value; queue = (evByOrg[selected] || []).filter(e => e.task === task); qi = 0; }
function stepOnce() { if (qi < queue.length) apply(queue[qi++]); if (qi >= queue.length) stop(); }
$("play").addEventListener("click", () => {
  if (timer) { stop(); return; }
  if (qi >= queue.length || qi === 0) load();
  $("play").textContent = "❚❚ Pause";
  timer = setInterval(stepOnce, +$("speed").value);
});
$("step").addEventListener("click", () => { if (qi >= queue.length) load(); stop(); stepOnce(); });
$("taskSel").addEventListener("change", load);
$("speed").addEventListener("change", () => { if (timer) { stop(); $("play").click(); } });

// ------------------------------------------------------------- selection
function selectOrg(name) {
  if (!D.orgs[name]) return;
  selected = name; stop(); drawLineage();
  const o = D.orgs[name], n = byName[name] || {};
  $("orgTitle").textContent = name + (name === champion ? "  ★ champion" : "");
  $("orgStruct").textContent = n.structure || "";
  const m = n.mutation;
  $("orgWhy").innerHTML = m ? `<b>${esc(mutLabel(m))}</b> on <code>${esc(n.parent)}</code> → ${n.kept ? "<span style='color:var(--green)'>kept</span>" : "discarded"}${m.reason ? ` · <span class="tag">“${esc(m.reason)}”</span>` : ""}`
    : `<span class="tag">${esc(o.description || "")}</span>`;
  drawOrg(o);
  const tasks = [...new Set((evByOrg[name] || []).filter(e => e.type === "start").map(e => e.task))];
  $("taskSel").innerHTML = tasks.map(t => `<option>${esc(t)}</option>`).join("") || "<option>(no recorded tasks)</option>";
  const pick = tasks.find(t => (evByOrg[name] || []).some(e => e.task === t && (e.type === "reject" || e.type === "decision"))) || tasks[0];
  if (pick) $("taskSel").value = pick;
  load();
  $("card").innerHTML = n.name ? `<div class="kv">
    <span>score</span><b>${fmt(n.score)}</b><span>solved</span><b>${n.solved}/${n.runs}</b>
    <span>cost</span><b>$${fmt(n.cost_usd, 4)}</b><span>breakers</span><b>${n.breakers ?? 0}</b>
    <span>errors</span><b>${n.errors ?? 0}</b><span>generation</span><b>${n.gen}</b></div>` : `<p class="empty">Not in lineage.</p>`;
  const per = {};
  for (const e of (evByOrg[name] || [])) if (e.type === "done") { const k = e.task.split("#")[0]; (per[k] ||= []).push(e.score); }
  const split = k => (D.splits || {})[k] || "";
  const rows = Object.entries(per).sort((a, b) => (split(a[0]) === "heldout") - (split(b[0]) === "heldout") || (a[0] < b[0] ? -1 : 1));
  $("pertask").innerHTML = rows.length ? rows.map(([k, v]) => { const s = v.reduce((a, b) => a + b, 0) / v.length;
    return `<div class="row"><span title="${esc(k)}">${esc(k)}${split(k) === "heldout" ? ' <em style="color:var(--violet);font-style:normal">held-out</em>' : ""}</span><div class="track"><div class="fill${name === champion ? " champ" : (byName[name]?.gen === 0 ? " human" : "")}" style="width:${(s * 100).toFixed(1)}%"></div></div><span class="num">${fmt(s, 2)}</span></div>`; }).join("")
    : `<p class="empty">No task results recorded.</p>`;
}

drawExam();
const first = champion && D.orgs[champion] ? champion : Object.keys(D.orgs)[0];
selected = first; drawLineage(); selectOrg(first);
addEventListener("resize", () => drawLineage());
</script>
</body>
</html>
"""
