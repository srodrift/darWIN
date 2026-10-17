#!/usr/bin/env bash
# Stage demo, one keystroke per step. Run from the repo root:  ./scripts/demo.sh
#   step 1 starts a LIVE mini-evolution on Crusoe in the background (about 2 minutes)
#   steps 2-4 show the org as code, the champion's diff and the full run's results
#   step 5 opens the 3D view of the live run that just finished (or the full run if it is still going)
set -u
cd "$(dirname "$0")/.."
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
B=$'\e[1m'; G=$'\e[32m'; D=$'\e[2m'; N=$'\e[0m'
pause() { echo; read -r -p "${D}[enter] ${1}${N}" _; clear; }
# The recorded full run: DARWIN_DEMO_RUN if set, else the finished run with the most orgs in its lineage.
latest_full() {
  if [ -n "${DARWIN_DEMO_RUN:-}" ]; then echo "$DARWIN_DEMO_RUN"; return; fi
  for d in runs/*_evolve; do [ -f "$d/final.json" ] && [ -f "$d/lineage.json" ] && \
    echo "$("$PY" -c "import json,sys;print(len(json.load(open(sys.argv[1]))))" "$d/lineage.json") $d"; done 2>/dev/null | sort -n | tail -1 | cut -d" " -f2
}

FULL=$(latest_full)   # the recorded full run, fixed before the live run starts
clear
echo "${B}DARWIN INC.${N}  Human org charts are generation zero."
echo
echo "Audience: which team should evolve live?"
echo "  ${B}1${N} startup (one worker)   ${B}2${N} hospital   ${B}3${N} research lab   ${B}4${N} council of peers"
read -r -p "pick [1-4, default 1]: " PICK
case "${PICK:-1}" in
  2) ORG=hospital; NAME="the teaching hospital";;
  3) ORG=lab; NAME="the research lab";;
  4) ORG=council; NAME="the council of peers";;
  *) ORG=startup; NAME="the one-person startup";;
esac
clear

# ---- 1. live mini-evolution in the background, on the audience's pick
mkdir -p runs
LIVE_LOG=runs/live_demo.log
before=$(ls -d runs/*_evolve 2>/dev/null | wc -l)
DARWIN_BUDGET=0.3 DARWIN_WORKERS=6 DARWIN_MAX_CONCURRENCY=12 "$PY" run.py evolve --orgs "$ORG" --generations 1 --parents 1 --children 2 \
  --seeds 1 --final-seeds 1 > "$LIVE_LOG" 2>&1 &
LIVE_PID=$!
echo "${G}Live evolution started on Crusoe + Nemotron, on ${NAME}.${N}"
echo "An AI consultant will study where it struggles and try 2 structural changes. The gate keeps only what wins."
echo "${D}log: $LIVE_LOG${N}"
pause "show an org chart as code"

# ---- 2. the org as code
SHOW=$(ls orgs/$ORG.yaml 2>/dev/null || echo orgs/hospital.yaml)
echo "${B}An org chart is a file.${N}  $SHOW"; echo
cat "$SHOW"
pause "show what evolution changed"

# ---- 3. the champion's diff vs its parent (from the full run)
if [ -n "$FULL" ]; then
  "$PY" - "$FULL" <<'PYEOF'
import json, sys, difflib, os, yaml
d = sys.argv[1]
fin = json.load(open(f"{d}/final.json")); lin = {n["name"]: n for n in json.load(open(f"{d}/lineage.json"))}
champ = fin["champion"]; parent = lin.get(champ, {}).get("parent")
if not parent:
    print(f"\033[1mThe best org was a human design ({champ}):\033[0m no mutation beat it on practice tasks this run."); sys.exit()
print(f"\033[1mWhat the AI consultant changed:\033[0m  {parent}  ->  {champ}\n")
def text(n):
    o = yaml.safe_load(open(f"{d}/orgs/{n}.yaml")); o.pop("description", None); o.pop("name", None)
    return yaml.safe_dump(o, sort_keys=False).splitlines()
for line in difflib.unified_diff(text(parent), text(champ), parent, champ, lineterm="", n=2):
    c = "\033[32m" if line.startswith("+") and not line.startswith("+++") else "\033[31m" if line.startswith("-") and not line.startswith("---") else ""
    print(f"{c}{line}\033[0m")
m = lin[champ].get("mutation") or {}
if m.get("reason"): print(f"\n\033[2mmeta-agent's reason: {m['reason'][:300]}\033[0m")
PYEOF
else echo "(no finished full run found)"; fi
pause "show the results"

# ---- 4. results with spread
[ -n "$FULL" ] && "$PY" run.py report "$FULL"
pause "check the live evolution"

# ---- 5. the live run
if kill -0 "$LIVE_PID" 2>/dev/null; then
  echo "${D}Live evolution still running...${N}"; tail -n 12 "$LIVE_LOG"
  echo; read -r -p "${D}[enter] wait for it, or Ctrl-C to skip${N}" _
  wait "$LIVE_PID" 2>/dev/null
fi
echo "${B}Live run on ${NAME}, just now:${N}"; grep -E "g1 |HELD-OUT|best human|champion|budget" "$LIVE_LOG" | head -20
grep -q "STOPPED\|Traceback" "$LIVE_LOG" && { echo "${D}(the live run hit a problem; showing the recorded full run instead)${N}"; }
after=$(ls -d runs/*_evolve 2>/dev/null | wc -l)
LIVE_DIR=$(ls -d runs/*_evolve | tail -1)
{ [ "$after" -le "$before" ] || [ "$LIVE_DIR" = "$FULL" ] || [ ! -f "$LIVE_DIR/final.json" ]; } && LIVE_DIR=$FULL
pause "open the 3D view"
"$PY" run.py viewer "$LIVE_DIR" >/dev/null && open "$LIVE_DIR/viewer.html" 2>/dev/null || xdg-open "$LIVE_DIR/viewer.html" 2>/dev/null
echo "${G}Opened $LIVE_DIR/viewer.html${N}"
