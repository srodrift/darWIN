#!/usr/bin/env bash
# Live self-evolution on Crusoe + Nemotron, with a hard spend cap.
#   ./scripts/evolve_demo.sh          quick: startup + hospital, 1 generation (~5 min, cents)
#   ./scripts/evolve_demo.sh full     all 5 human orgs, 2 generations (~20 min, well under $1)
# Output is saved to runs/evolve_demo.log; results to runs/<timestamp>_evolve/.
set -u
cd "$(dirname "$0")/.."
mkdir -p runs
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
if [ "${1:-quick}" = "full" ]; then
  ORGS="orgs/*.yaml"; GENS=2; FINAL=2; CAP=1
else
  ORGS="startup,hospital"; GENS=1; FINAL=1; CAP=0.5
fi
DARWIN_BUDGET=$CAP "$PY" run.py evolve --orgs "$ORGS" --generations $GENS --parents 2 \
  --children 2 --final-seeds $FINAL 2>&1 | tee runs/evolve_demo.log
