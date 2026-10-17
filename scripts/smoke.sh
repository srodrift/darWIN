#!/usr/bin/env bash
# First live check on Crusoe: key, models, one real task, spend. Costs cents.
# Output is saved to runs/smoke.log so a teammate (or Claude) can read it.
set -u
cd "$(dirname "$0")/.."
mkdir -p runs
grep -q '^DARWIN_BUDGET=' .env 2>/dev/null || echo 'DARWIN_BUDGET=1' >> .env
grep -q '^DARWIN_TOTAL_BUDGET=' .env 2>/dev/null || echo 'DARWIN_TOTAL_BUDGET=10' >> .env
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
{
  echo "== $(date) =="
  "$PY" -m pip install -q -r requirements.txt
  "$PY" run.py check && "$PY" run.py once --org hospital --task median
  "$PY" run.py spend
} 2>&1 | tee runs/smoke.log
