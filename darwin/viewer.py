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
    html = TEMPLATE.replace("/*__DATA__*/null", payload)
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
      </div>
      <div id="orgmapWrap"><svg id="orgmap" role="img" aria-label="Organization map"></svg></div>
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
  layout = {svg, nodes, gov, rtr, teams, multi, defaultTeam: teams[0].name, nodeH};
}

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
}
function apply(e) {
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
