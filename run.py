#!/usr/bin/env python3
"""Darwin Inc.: human org charts are generation zero.

  python run.py check                                  # Crusoe key + Nemotron models OK?
  python run.py spend                                  # estimated credits used, caps left
  python run.py viewer [runs/<id>]                     # offline HTML: lineage, org replay, exam
  python run.py once --org hospital --task median      # one org, one task, verbose
  python run.py compare --split train                  # the three human orgs, head to head
  python run.py evolve --generations 3 --children 2    # walk away: evolve past them
  python run.py evolve --resume runs/<id>              # continue a run that stopped

Every run writes runs/<id>/: meta.json (live or mock, models, settings),
events.jsonl (every step), lineage.json, cards/ (full scorecards), orgs/
(each org as YAML) and final.json (held-out exam).
Set DARWIN_MOCK=1 to run offline, DARWIN_BUDGET=<usd> to cap spend.
Ctrl-C during evolve stops evolving and goes straight to the held-out exam.
"""
import argparse
import glob
import json
import os
import sys
import time

from darwin import engine, evaluate, evolution, llm, org as orgmod

ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- helpers
def seed_orgs(spec="orgs/*.yaml"):
    """Load generation 0 from a comma-separated list of globs or org file names,
    e.g. "orgs/*.yaml", "orgs/catalog/*.yaml", or "startup,hospital,matrix"."""
    paths = []
    for item in [x.strip() for x in spec.split(",") if x.strip()]:
        if "/" in item or item.endswith(".yaml"):
            found = sorted(glob.glob(os.path.join(ROOT, item), recursive=True))
        else:
            found = sorted(glob.glob(os.path.join(ROOT, "orgs", "**", f"{item}.yaml"), recursive=True))
        if not found:
            sys.exit(f"no org files match '{item}'")
        paths += [p for p in found if p not in paths]
    orgs = [orgmod.load(p) for p in paths]
    names = [o["name"] for o in orgs]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        sys.exit(f"duplicate org names in '{spec}': {sorted(dupes)}")
    return orgs


def budget_banner():
    if llm.MOCK:
        print("MOCK MODE: fake model, no credits used, scores are meaningless.\n")
        return
    print(f"budget: this run ${llm.LEDGER.budget:.2f} | all runs so far ${llm.LEDGER.lifetime():.4f} "
          f"of ${llm.LEDGER.total_budget:.2f} lifetime cap (estimates; Crusoe console is the truth)\n")


def new_run_dir(tag, args=None):
    budget_banner()
    d = os.path.join(ROOT, "runs", time.strftime("%Y%m%d-%H%M%S") + "_" + tag)
    os.makedirs(os.path.join(d, "orgs"), exist_ok=True)
    os.makedirs(os.path.join(d, "cards"), exist_ok=True)
    evaluate.save({
        "mode": "mock" if llm.MOCK else "live",
        "note": "MOCK DATA: fake model, scores are meaningless" if llm.MOCK else "live Crusoe run",
        "worker_model": llm.WORKER_MODEL, "meta_model": llm.META_MODEL,
        "budget_usd": llm.LEDGER.budget, "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "command": tag, "args": vars(args) if args else {},
        "search": bool(os.environ.get("YDC_API_KEY")),
    }, os.path.join(d, "meta.json"))
    return d


table = evolution.table


def pages_summary(d):
    path = os.path.join(d, "events.jsonl")
    if not os.path.exists(path):
        return
    pages = [json.loads(l) for l in open(path) if '"page_human"' in l]
    if pages:
        print(f"\n{len(pages)} task(s) paged a human (see events.jsonl, type=page_human)")


# ---------------------------------------------------------------- commands
def cmd_check(a):
    """Confirm the Crusoe key works and the Nemotron models exist."""
    if llm.MOCK:
        print("DARWIN_MOCK=1 is set: running offline, nothing to check.")
        return
    try:
        client = llm._get_client()
        ids = [m.id for m in client.models.list().data]
    except Exception as e:
        sys.exit(f"Could not reach Crusoe: {e}")
    nemo = [i for i in ids if "nemotron" in i.lower()]
    print("Nemotron models on your Crusoe project:\n  " + "\n  ".join(nemo or ["(none found)"]))
    ok = True
    for role in ("worker", "meta"):
        model = getattr(llm, f"{role.upper()}_MODEL")
        exact = llm.resolve_model(model, ids)
        if exact and exact != model:
            setattr(llm, f"{role.upper()}_MODEL", exact)
            print(f"{role} model {model}: OK, using exact ID {exact} "
                  f"(set DARWIN_{role.upper()}_MODEL={exact} in .env)")
        elif exact:
            print(f"{role} model {model}: OK")
        else:
            ok = False
            print(f"{role} model {model}: NOT FOUND -> set DARWIN_{role.upper()}_MODEL=<id from the list> in .env")
    if ok:
        for model in (llm.WORKER_MODEL, llm.META_MODEL):
            try:
                text, cost = llm.chat([{"role": "user", "content": "Reply with the single word: ready"}],
                                      model=model, max_tokens=60)
                print(f"test call {model} -> {text.strip()[:40]!r} (${cost:.6f})")
            except Exception as e:
                print(f"test call {model} FAILED: {e}")
    print("You.com key:", "set" if os.environ.get("YDC_API_KEY") else "not set (search disabled)")


def cmd_spend(a):
    """Show estimated spend across all runs and the caps that protect your credits."""
    total = llm.read_lifetime()
    print(f"estimated spend, all live runs: ${total:.4f}")
    print(f"lifetime cap (DARWIN_TOTAL_BUDGET): ${llm.LEDGER.total_budget:.2f}  "
          f"-> ${max(0.0, llm.LEDGER.total_budget - total):.4f} left")
    print(f"per-run cap (DARWIN_BUDGET): ${llm.LEDGER.budget:.2f}")
    print(f"ledger file: {llm.SPEND_FILE}")
    print("These are local estimates from token counts; check the Crusoe console for actual billing.")


def cmd_viewer(a):
    """Write runs/<id>/viewer.html: lineage, org map with replay, held-out exam."""
    from darwin import viewer
    run_dir = a.run_dir
    if not run_dir:
        dirs = sorted(d for d in glob.glob(os.path.join(ROOT, "runs", "*"))
                      if os.path.isdir(os.path.join(d, "orgs")))
        if not dirs:
            sys.exit("no runs yet; run `python run.py evolve` or `compare` first")
        run_dir = dirs[-1]
    path = viewer.build(run_dir)
    print(f"viewer written: {path}")
    print(f"open it with:   open '{path}'")


def cmd_once(a):
    org_path = next(iter(glob.glob(os.path.join(ROOT, "orgs", "**", f"{a.org}.yaml"), recursive=True)),
                    os.path.join(ROOT, "orgs", f"{a.org}.yaml"))
    task_dirs = glob.glob(os.path.join(ROOT, "tasks", "*", a.task))
    if not os.path.exists(org_path):
        sys.exit(f"unknown org '{a.org}'. Options: " + ", ".join(
            os.path.splitext(os.path.basename(p))[0]
            for p in glob.glob(os.path.join(ROOT, "orgs", "**", "*.yaml"), recursive=True)))
    if not task_dirs:
        sys.exit(f"unknown task '{a.task}'. Options: " + ", ".join(
            os.path.basename(p) for p in sorted(glob.glob(os.path.join(ROOT, "tasks", "*", "*")))))
    o, t = orgmod.load(org_path), engine.load_task(task_dirs[0])
    d = new_run_dir("once", a)
    print(f"{o['name']}: {orgmod.summary(o)}\ntask: {t['name']}: {t['issue'].strip()}\n")
    r = engine.run(o, t, engine.EventLog(os.path.join(d, "events.jsonl")))
    for n in r["notes"]:
        print("  ", n)
    print(f"\nhidden tests: {r['passed']}/{r['total']}  outcome={r['outcome']}  "
          f"rounds={r['rounds']}  cost=${r['cost_usd']}")
    print(f"\nfinal code:\n{r['code']}")
    evaluate.save({k: v for k, v in r.items()}, os.path.join(d, "result.json"))


def cmd_compare(a):
    d = new_run_dir("compare", a)
    log = engine.EventLog(os.path.join(d, "events.jsonl"))
    cards = []
    try:
        for o in seed_orgs(a.orgs):
            orgmod.dump(o, os.path.join(d, "orgs", f"{o['name']}.yaml"))
            cards.append(evaluate.evaluate(o, a.split, seeds=a.seeds, log=log))
            evaluate.save(cards, os.path.join(d, f"compare_{a.split}.json"))
            table(cards, f"{a.split} (seeds={a.seeds})")
    except llm.BudgetExceeded as e:
        print(f"\n{e}; saved what finished.")
    except KeyboardInterrupt:
        print("\ninterrupted; saved what finished.")
    pages_summary(d)
    print(f"\nsaved {d}")


def cmd_evolve(a):
    d = new_run_dir("evolve", a)
    seeds = [] if a.resume else seed_orgs(a.orgs)
    try:
        evolution.run(seeds, d, generations=a.generations, parents=a.parents, children=a.children,
                      seeds=a.seeds, final_seeds=a.final_seeds, random_mutations=a.random,
                      resume=a.resume)
    except llm.BudgetExceeded as e:
        sys.exit(f"{e} before generation 0 finished; raise DARWIN_BUDGET.")
    pages_summary(d)
    print(f"\nsaved {d}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("spend")
    s = sub.add_parser("viewer")
    s.add_argument("run_dir", nargs="?", help="a runs/<id> directory (default: the latest run)")
    s = sub.add_parser("once")
    s.add_argument("--org", default="hospital")
    s.add_argument("--task", default="median")
    s = sub.add_parser("compare")
    s.add_argument("--orgs", default="orgs/*.yaml", help='comma-separated globs or names, e.g. "orgs/catalog/*.yaml" or "startup,hospital"')
    s.add_argument("--split", default="train")
    s.add_argument("--seeds", type=int, default=1)
    s = sub.add_parser("evolve")
    s.add_argument("--orgs", default="orgs/*.yaml", help='generation 0: comma-separated globs or names, e.g. "startup,hospital"')
    s.add_argument("--generations", type=int, default=3)
    s.add_argument("--parents", type=int, default=2)
    s.add_argument("--children", type=int, default=2)
    s.add_argument("--seeds", type=int, default=1)
    s.add_argument("--final-seeds", type=int, default=2)
    s.add_argument("--random", action="store_true", help="random mutations instead of the meta-agent")
    s.add_argument("--resume", help="continue from a previous runs/<id> directory")
    a = p.parse_args()
    try:
        {"check": cmd_check, "spend": cmd_spend, "viewer": cmd_viewer, "once": cmd_once, "compare": cmd_compare, "evolve": cmd_evolve}[a.cmd](a)
    except llm.FatalAPIError as e:
        sys.exit(f"\nSTOPPED: {e}\nEverything finished so far is saved under runs/. "
                 f"For evolve, fix the problem and continue with --resume runs/<id>.")


if __name__ == "__main__":
    main()
