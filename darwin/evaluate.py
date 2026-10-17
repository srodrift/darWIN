"""Score orgs on a task split. Same tasks, same hidden tests, same frozen
prompts for every org: only the structure differs."""
import glob
import json
import os
import statistics
from concurrent.futures import ThreadPoolExecutor

from . import engine, llm

ROOT = engine.ROOT


def tasks(split):
    return [engine.load_task(d) for d in sorted(glob.glob(os.path.join(ROOT, "tasks", split, "*")))]


def evaluate(org, split="train", seeds=1, log=None, workers=4):
    """Run org on every task in `split`, `seeds` times. Returns a scorecard."""
    jobs = [(t, s) for t in tasks(split) for s in range(seeds)]

    def one(job):
        t, s = job
        try:
            return engine.run(org, t, log, run_tag=f"#{s}" if seeds > 1 else "")
        except llm.BudgetExceeded:
            raise
        except Exception as e:  # one broken run must not kill the experiment
            return {"org": org["name"], "task": t["name"], "score": 0.0, "outcome": f"error: {e}",
                    "rounds": 0, "cost_usd": 0.0, "notes": [], "code": ""}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, jobs))

    card = {
        "org": org["name"],
        "split": split,
        "score": round(statistics.mean(r["score"] for r in results), 3),
        "spread": round(statistics.pstdev([r["score"] for r in results]), 3),
        "solved": sum(r["score"] == 1.0 for r in results),
        "runs": len(results),
        "cost_usd": round(sum(r["cost_usd"] for r in results), 4),
        "escalations": sum(r["outcome"] == "escalated" for r in results),
        "breakers": sum(r["rounds"] >= org["max_rounds"] for r in results),
        "per_task": {r["task"]: r["score"] for r in results},
        "failures": [{"task": r["task"], "score": r["score"], "notes": r["notes"][-6:]}
                     for r in results if r["score"] < 1.0][:8],
    }
    return card


def save(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
