#!/usr/bin/env python3
"""Darwin Inc.: human org charts are generation zero.

  python run.py check                                  # Crusoe key + Nemotron models OK?
  python run.py once --org hospital --task median      # one org, one task, verbose
  python run.py compare --split train                  # the three human orgs, head to head
  python run.py evolve --generations 3 --children 2    # walk away: evolve past them

Every run writes runs/<id>/events.jsonl (for the 3D replay view), plus
scorecards, the lineage of every org tried, and each org as YAML.
Set DARWIN_MOCK=1 to run offline, DARWIN_BUDGET=<usd> to cap spend.
"""
import argparse
import glob
import os
import time

from darwin import engine, evaluate, evolve, llm, org as orgmod

ROOT = os.path.dirname(os.path.abspath(__file__))


def seed_orgs():
    return [orgmod.load(p) for p in sorted(glob.glob(os.path.join(ROOT, "orgs", "*.yaml")))]


def new_run_dir(tag):
    d = os.path.join(ROOT, "runs", time.strftime("%H%M%S") + "_" + tag)
    os.makedirs(os.path.join(d, "orgs"), exist_ok=True)
    return d


def table(cards, title):
    print(f"\n{title}")
    print(f"{'org':34} {'score':>6} {'solved':>8} {'cost $':>8} {'escal.':>6}")
    for c in sorted(cards, key=lambda c: (-c["score"], c["cost_usd"])):
        print(f"{c['org'][:34]:34} {c['score']:>6.3f} {c['solved']:>3}/{c['runs']:<4} "
              f"{c['cost_usd']:>8.4f} {c['escalations']:>6}")
    print(f"total spent so far: ${llm.LEDGER.spent:.4f} over {llm.LEDGER.calls} calls")


def cmd_check(a):
    """Confirm the Crusoe key works and the Nemotron models exist."""
    client = llm._get_client()
    ids = [m.id for m in client.models.list().data]
    nemo = [i for i in ids if "nemotron" in i.lower()]
    print("Nemotron models on your Crusoe project:\n  " + "\n  ".join(nemo or ["(none found)"]))
    for role, model in (("worker", llm.WORKER_MODEL), ("meta", llm.META_MODEL)):
        print(f"{role} model {model}: {'OK' if model in ids else 'NOT FOUND, set DARWIN_' + role.upper() + '_MODEL'}")
    text, cost = llm.chat([{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=50)
    print(f"test call -> {text.strip()[:40]!r} (${cost:.6f})")
    import os as _os
    print("You.com key:", "set" if _os.environ.get("YDC_API_KEY") else "not set (search disabled)")


def cmd_once(a):
    o = orgmod.load(os.path.join(ROOT, "orgs", f"{a.org}.yaml"))
    t = engine.load_task(glob.glob(os.path.join(ROOT, "tasks", "*", a.task))[0])
    d = new_run_dir("once")
    print(orgmod.summary(o))
    r = engine.run(o, t, engine.EventLog(os.path.join(d, "events.jsonl")))
    for n in r["notes"]:
        print("  ", n)
    print(f"\nhidden tests: {r['passed']}/{r['total']}  outcome={r['outcome']}  "
          f"rounds={r['rounds']}  cost=${r['cost_usd']}")
    print(f"\nfinal code:\n{r['code']}")


def cmd_compare(a):
    d = new_run_dir("compare")
    log = engine.EventLog(os.path.join(d, "events.jsonl"))
    cards = []
    for o in seed_orgs():
        cards.append(evaluate.evaluate(o, a.split, seeds=a.seeds, log=log))
        table(cards, f"{a.split} (seeds={a.seeds})")
    evaluate.save(cards, os.path.join(d, f"compare_{a.split}.json"))
    print(f"\nsaved {d}")


def cmd_evolve(a):
    d = new_run_dir("evolve")
    log = engine.EventLog(os.path.join(d, "events.jsonl"))
    lineage, history, pop = [], [], []

    def record(o, card, gen, parent=None, mutation=None, kept=True):
        orgmod.dump(o, os.path.join(d, "orgs", f"{o['name']}.yaml"))
        lineage.append({"name": o["name"], "gen": gen, "parent": parent, "mutation": mutation,
                        "kept": kept, "structure": orgmod.summary(o), "score": card["score"],
                        "solved": card["solved"], "runs": card["runs"], "cost_usd": card["cost_usd"],
                        "escalations": card["escalations"]})
        evaluate.save(lineage, os.path.join(d, "lineage.json"))

    print("generation 0: human org charts")
    for o in seed_orgs():
        card = evaluate.evaluate(o, "train", seeds=a.seeds, log=log)
        pop.append((o, card))
        record(o, card, 0)
    table([c for _, c in pop], "gen 0 (train)")
    best_human = max(pop, key=lambda p: (p[1]["score"], -p[1]["cost_usd"]))

    try:
        for g in range(1, a.generations + 1):
            parents = sorted(pop, key=lambda p: (-p[1]["score"], p[1]["cost_usd"]))[:a.parents]
            for parent, pcard in parents:
                for k in range(a.children):
                    child, mut = (evolve.meta_mutation(parent, pcard, history) if not a.random
                                  else evolve.random_mutation(parent))
                    if not child:
                        continue
                    child["name"] = f"{parent['name'].split('~')[0]}~g{g}{chr(97 + k)}"
                    child["description"] = f"Mutant of {parent['name']}: {mut}"
                    card = evaluate.evaluate(child, "train", seeds=a.seeds, log=log)
                    better = card["score"] > pcard["score"] or (
                        card["score"] == pcard["score"] and card["cost_usd"] < 0.8 * pcard["cost_usd"])
                    log.emit(org=child["name"], task="*", type="spawn", parent=parent["name"],
                             mutation=mut, score=card["score"], kept=better)
                    record(child, card, g, parent["name"], mut, kept=better)
                    history.append({"mutation": f"{mut.get('op')} {mut.get('stage') or mut.get('n') or ''} on {parent['name']}",
                                    "result": f"{pcard['score']} -> {card['score']} ({'kept' if better else 'discarded'})"})
                    verdict = "KEPT" if better else "discarded"
                    print(f"  g{g} {child['name']:30} {mut['op']:22} {pcard['score']:.3f} -> {card['score']:.3f}  {verdict}")
                    if better:
                        pop.append((child, card))
            table([c for _, c in pop], f"population after gen {g}")
    except llm.BudgetExceeded as e:
        print(f"\n{e}; stopping evolution and moving to the held-out exam.")

    champion = max(pop, key=lambda p: (p[1]["score"], -p[1]["cost_usd"]))
    print(f"\nHELD-OUT EXAM (tasks evolution never saw), seeds={a.final_seeds}")
    print(f"best human org: {best_human[0]['name']}  {orgmod.summary(best_human[0])}")
    print(f"evolved champion: {champion[0]['name']}  {orgmod.summary(champion[0])}")
    final = []
    contenders = [best_human[0]] + ([champion[0]] if champion[0]["name"] != best_human[0]["name"] else [])
    if all(o["name"] != "flat_startup" for o in contenders):  # always include the baseline
        contenders += [o for o, _ in pop if o["name"] == "flat_startup"]
    for o in contenders:
        try:
            final.append(evaluate.evaluate(o, "heldout", seeds=a.final_seeds, log=log))
        except llm.BudgetExceeded as e:
            print(e)
            break
    table(final, "HELD-OUT")
    evaluate.save({"best_human": best_human[0]["name"], "champion": champion[0]["name"],
                   "heldout": final, "lineage": lineage}, os.path.join(d, "final.json"))
    print(f"\nsaved {d}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    s = sub.add_parser("once"); s.add_argument("--org", default="hospital"); s.add_argument("--task", default="median")
    s = sub.add_parser("compare"); s.add_argument("--split", default="train"); s.add_argument("--seeds", type=int, default=1)
    s = sub.add_parser("evolve")
    s.add_argument("--generations", type=int, default=3)
    s.add_argument("--parents", type=int, default=2)
    s.add_argument("--children", type=int, default=2)
    s.add_argument("--seeds", type=int, default=1)
    s.add_argument("--final-seeds", type=int, default=2)
    s.add_argument("--random", action="store_true", help="random mutations instead of the meta-agent")
    a = p.parse_args()
    {"check": cmd_check, "once": cmd_once, "compare": cmd_compare, "evolve": cmd_evolve}[a.cmd](a)


if __name__ == "__main__":
    main()
