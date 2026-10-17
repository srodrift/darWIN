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


def build(run_dir, out_path=None, data=None):
    data = data or _load_run(run_dir)
    if not data["orgs"]:
        raise SystemExit(f"no orgs found in {run_dir}/orgs; is this a Darwin run directory?")
    return render(data, out_path or os.path.join(run_dir, "viewer.html"))


def render(data, out_path):
    """Write the Darwin HQ page (3D evolution staircase) for already-loaded run data."""
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "viewer_hq.html")) as f:
        template = f.read()
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    three = ""
    three_path = os.path.join(here, "vendor", "three.min.js")
    if os.path.exists(three_path):
        with open(three_path) as f:
            three = f.read().replace("</script", "<\\/script")
    html = template.replace("/*__DATA__*/null", payload, 1).replace("/*__THREE__*/", three, 1)
    with open(out_path, "w") as f:
        f.write(html)
    return out_path
