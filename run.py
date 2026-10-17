#!/usr/bin/env python3
"""Darwin Inc.: human org charts are generation zero.

  python run.py check                                  # Crusoe key + Nemotron models OK?
  python run.py spend                                  # estimated credits used, caps left
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

from darwin import engine, evaluate, evolve, llm, org as orgmod

ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- helpers
def seed_orgs(pattern="orgs/*.yaml"):
    """Load generation 0. `pattern` is a glob relative to the repo, e.g.
    "orgs/catalog/*.yaml" or "orgs/**/*.yaml"."""
    paths = sorted(glob.glob(os.path.join(ROOT, pattern), recursive=True))
    if not paths:
        sys.exit(f"no org files match '{pattern}'")
    orgs = [orgmod.load(p) for p in paths]
    names = [o["name"] for o in orgs]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        sys.exit(f"duplicate org names in '{pattern}': {sorted(dupes)}")
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


def rank_key(card):
    return (card["score"], -card["cost_usd"])


def table(cards, title):
    print(f"\n{title}")
    print(f"{'org':34} {'score':>6} {'solved':>8} {'cost $':>8} {'breaker':>7} {'err':>4}")
    for c in sorted(cards, key=lambda c: (-c["score"], c["cost_usd"])):
        print(f"{c['org'][:34]:34} {c['score']:>6.3f} {c['solved']:>3}/{c['runs']:<4} "
              f"{c['cost_usd']:>8.4f} {c['breakers']:>7} {c['errors']:>4}")
    print(f"spent so far: ${llm.LEDGER.spent:.4f} of ${llm.LEDGER.budget:.2f} over {llm.LEDGER.calls} calls")


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


def _load_resume(rdir):
    """Rebuild the population and history from a previous evolve run."""
    lineage = json.load(open(os.path.join(rdir, "lineage.json")))
    pop, history = [], []
    for node in lineage:
        card_path = os.path.join(rdir, "cards", f"{node['name']}.json")
        org_path = os.path.join(rdir, "orgs", f"{node['name']}.yaml")
        if node["kept"] and os.path.exists(card_path) and os.path.exists(org_path):
            pop.append((orgmod.load(org_path), json.load(open(card_path))))
        if node.get("mutation"):
            m = node["mutation"]
            history.append({"mutation": f"{evolve.describe(m)} on {node['parent']}",
                            "result": f"-> {node['score']} ({'kept' if node['kept'] else 'discarded'})"})
    start_gen = max(n["gen"] for n in lineage) + 1
    return lineage, history, pop, start_gen


def cmd_evolve(a):
    d = new_run_dir("evolve", a)
    log = engine.EventLog(os.path.join(d, "events.jsonl"))
    names = set()

    def record(o, card, gen, parent=None, mutation=None, kept=True):
        names.add(o["name"])
        orgmod.dump(o, os.path.join(d, "orgs", f"{o['name']}.yaml"))
        evaluate.save(card, os.path.join(d, "cards", f"{o['name']}.json"))
        lineage.append({"name": o["name"], "gen": gen, "parent": parent, "mutation": mutation,
                        "kept": kept, "structure": orgmod.summary(o), "score": card["score"],
                        "solved": card["solved"], "runs": card["runs"], "cost_usd": card["cost_usd"],
                        "breakers": card["breakers"], "errors": card["errors"]})
        evaluate.save(lineage, os.path.join(d, "lineage.json"))

    def unique_name(parent_name, gen):
        root = parent_name.split("~")[0]
        for k in range(26 * 4):
            cand = f"{root}~g{gen}{chr(97 + k % 26)}{'' if k < 26 else k // 26}"
            if cand not in names:
                return cand
        return f"{root}~g{gen}_{int(time.time() * 1000)}"

    if a.resume:
        lineage, history, pop, start_gen = _load_resume(a.resume)
        for node in lineage:
            names.add(node["name"])
        evaluate.save(lineage, os.path.join(d, "lineage.json"))
        for o, c in pop:
            orgmod.dump(o, os.path.join(d, "orgs", f"{o['name']}.yaml"))
            evaluate.save(c, os.path.join(d, "cards", f"{o['name']}.json"))
        gen0 = [(o, c) for o, c in pop if "~" not in o["name"]]
        print(f"resumed {len(pop)} kept orgs from {a.resume}, continuing at generation {start_gen}")
    else:
        lineage, history, pop, start_gen = [], [], [], 1
        print("generation 0: human org charts")
        try:
            for o in seed_orgs(a.orgs):
                card = evaluate.evaluate(o, "train", seeds=a.seeds, log=log)
                pop.append((o, card))
                record(o, card, 0)
        except llm.BudgetExceeded as e:
            sys.exit(f"{e} before generation 0 finished; raise DARWIN_BUDGET.")
        table([c for _, c in pop], "gen 0 (train)")
        gen0 = list(pop)

    best_human = max(gen0, key=lambda p: rank_key(p[1])) if gen0 else max(pop, key=lambda p: rank_key(p[1]))

    try:
        for g in range(start_gen, start_gen + a.generations):
            parents = sorted(pop, key=lambda p: (-p[1]["score"], p[1]["cost_usd"]))[:a.parents]
            for parent, pcard in parents:
                for _ in range(a.children):
                    child, mut = (evolve.random_mutation(parent) if a.random
                                  else evolve.meta_mutation(parent, pcard, history))
                    if not child:
                        continue
                    child["name"] = unique_name(parent["name"], g)
                    child["description"] = f"Mutant of {parent['name']}: {evolve.describe(mut)}"
                    card = evaluate.evaluate(child, "train", seeds=a.seeds, log=log)
                    # Gate: keep only a measurable improvement, never one tainted by API errors.
                    better = card["errors"] == 0 and (
                        card["score"] > pcard["score"] or
                        (card["score"] == pcard["score"] and card["cost_usd"] < 0.8 * pcard["cost_usd"]))
                    log.emit(org=child["name"], task="*", type="spawn", parent=parent["name"],
                             mutation=mut, score=card["score"], kept=better)
                    record(child, card, g, parent["name"], mut, kept=better)
                    history.append({"mutation": f"{evolve.describe(mut)} on {parent['name']}",
                                    "result": f"{pcard['score']} -> {card['score']} ({'kept' if better else 'discarded'})"})
                    print(f"  g{g} {child['name']:30} {evolve.describe(mut)[:34]:34} "
                          f"{pcard['score']:.3f} -> {card['score']:.3f}  {'KEPT' if better else 'discarded'}"
                          f"{'  (errors: ' + str(card['errors']) + ')' if card['errors'] else ''}")
                    if better:
                        pop.append((child, card))
            table([c for _, c in pop], f"population after gen {g}")
    except llm.BudgetExceeded as e:
        print(f"\n{e}; stopping evolution and moving to the held-out exam.")
    except KeyboardInterrupt:
        print("\nstopped by you; moving to the held-out exam (Ctrl-C again to quit).")

    champion = max(pop, key=lambda p: rank_key(p[1]))
    print(f"\nHELD-OUT EXAM (tasks evolution never saw), seeds={a.final_seeds}")
    print(f"best human org : {best_human[0]['name']}  {orgmod.summary(best_human[0])}")
    print(f"evolved champion: {champion[0]['name']}  {orgmod.summary(champion[0])}")
    contenders, seen = [], set()
    baseline = [o for o, _ in pop if o["name"] == "flat_startup"]
    for o in [best_human[0], champion[0]] + baseline:
        if o["name"] not in seen:
            seen.add(o["name"])
            contenders.append(o)
    final = []
    for o in contenders:
        try:
            final.append(evaluate.evaluate(o, "heldout", seeds=a.final_seeds, log=log))
        except llm.BudgetExceeded as e:
            print(f"{e}; held-out exam incomplete.")
            break
        evaluate.save({"best_human": best_human[0]["name"], "champion": champion[0]["name"],
                       "heldout": final}, os.path.join(d, "final.json"))
    if final:
        table(final, "HELD-OUT")
    pages_summary(d)
    print(f"\nsaved {d}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("spend")
    s = sub.add_parser("once")
    s.add_argument("--org", default="hospital")
    s.add_argument("--task", default="median")
    s = sub.add_parser("compare")
    s.add_argument("--orgs", default="orgs/*.yaml", help='glob of org files, e.g. "orgs/catalog/*.yaml"')
    s.add_argument("--split", default="train")
    s.add_argument("--seeds", type=int, default=1)
    s = sub.add_parser("evolve")
    s.add_argument("--orgs", default="orgs/*.yaml", help='glob of org files for generation 0')
    s.add_argument("--generations", type=int, default=3)
    s.add_argument("--parents", type=int, default=2)
    s.add_argument("--children", type=int, default=2)
    s.add_argument("--seeds", type=int, default=1)
    s.add_argument("--final-seeds", type=int, default=2)
    s.add_argument("--random", action="store_true", help="random mutations instead of the meta-agent")
    s.add_argument("--resume", help="continue from a previous runs/<id> directory")
    a = p.parse_args()
    try:
        {"check": cmd_check, "spend": cmd_spend, "once": cmd_once, "compare": cmd_compare, "evolve": cmd_evolve}[a.cmd](a)
    except llm.FatalAPIError as e:
        sys.exit(f"\nSTOPPED: {e}\nEverything finished so far is saved under runs/. "
                 f"For evolve, fix the problem and continue with --resume runs/<id>.")


if __name__ == "__main__":
    main()
