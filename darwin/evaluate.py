"""Score orgs on a task split. Same tasks, same hidden tests, same frozen
prompts for every org: only the structure differs."""
import glob
import json
import os
import statistics
from concurrent.futures import ThreadPoolExecutor

from . import engine, llm

ROOT = engine.ROOT
WORKERS = int(os.environ.get("DARWIN_WORKERS", "4"))


def tasks(split):
    found = [engine.load_task(d) for d in sorted(glob.glob(os.path.join(ROOT, "tasks", split, "*")))]
    if not found:
        raise SystemExit(f"no tasks found for split '{split}' (expected tasks/{split}/<name>/)")
    return found


def _error_result(org, t, seed, err):
    return {"org": org["name"], "task": t["name"], "seed": seed, "score": 0.0,
            "outcome": "error", "error": str(err)[:300], "rounds": 0, "cost_usd": 0.0,
            "notes": [f"infrastructure error: {str(err)[:160]}"], "code": "", "breaker": None}


def evaluate(org, split="train", seeds=1, log=None, workers=None):
    """Run org on every task in `split`, `seeds` times. Returns a scorecard.

    An infrastructure error (API outage, timeout) is retried once so a flaky
    network doesn't get blamed on the org's structure; errors that remain
    are counted separately in the scorecard."""
    jobs = [(t, s) for t in tasks(split) for s in range(seeds)]

    def one(job):
        t, s = job
        tag = f"#{s}" if seeds > 1 else ""
        for attempt in range(2):
            try:
                r = engine.run(org, t, log, run_tag=tag)
                r["seed"] = s
                return r
            except (llm.BudgetExceeded, llm.FatalAPIError):
                raise
            except Exception as e:
                if attempt == 1:
                    return _error_result(org, t, s, e)

    with ThreadPoolExecutor(max_workers=workers or WORKERS) as ex:
        results = list(ex.map(one, jobs))

    scores = [r["score"] for r in results]
    seed_means = [statistics.mean(r["score"] for r in results if r["seed"] == s) for s in range(seeds)]
    per_task = {}
    for r in results:
        per_task.setdefault(r["task"], []).append(r["score"])

    return {
        "org": org["name"],
        "split": split,
        "seeds": seeds,
        "score": round(statistics.mean(scores), 3),
        # spread between repeated seeds (0 when seeds == 1)
        "seed_spread": round(statistics.pstdev(seed_means), 3) if seeds > 1 else 0.0,
        "seed_means": [round(m, 3) for m in seed_means],
        "solved": sum(s == 1.0 for s in scores),
        "runs": len(results),
        "cost_usd": round(sum(r["cost_usd"] for r in results), 4),
        "escalations": sum(r["outcome"] == "escalated" for r in results),
        "breakers": sum(bool(r.get("breaker")) for r in results),
        "loops": sum(r.get("breaker") == "loop detected" for r in results),
        "errors": sum(r["outcome"] == "error" for r in results),
        "per_task": {k: round(statistics.mean(v), 3) for k, v in per_task.items()},
        "failures": [{"task": r["task"], "score": r["score"], "outcome": r["outcome"],
                      "notes": r["notes"][-6:]} for r in results if r["score"] < 1.0][:8],
    }


def save(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)  # atomic: a crash never leaves a half-written file
