"""The evolution loop, as a library so it can be tested and reused.

  generation 0  score the seed (human) orgs on the train tasks
  each gen      the top `parents` orgs each get `children` mutants; a mutant
                joins the population only if `gate()` says it beat its parent
  finally       held-out exam on tasks evolution never saw: best human org vs
                evolved champion vs the startup baseline
"""
import json
import os
import time

from . import engine, evaluate, evolve, llm, org as orgmod


def rank_key(card):
    return (card["score"], -card["cost_usd"])


def gate(child_card, parent_card, cost_margin=0.8):
    """Keep a mutant only for a measurable improvement: a higher score, or the
    same score at clearly lower cost. Never keep one tainted by API errors."""
    if child_card["errors"]:
        return False
    if child_card["score"] > parent_card["score"]:
        return True
    return (child_card["score"] == parent_card["score"]
            and child_card["cost_usd"] < cost_margin * parent_card["cost_usd"])


def table(cards, title, say=print):
    say(f"\n{title}")
    say(f"{'org':34} {'score':>6} {'solved':>8} {'cost $':>8} {'breaker':>7} {'err':>4}")
    for c in sorted(cards, key=lambda c: (-c["score"], c["cost_usd"])):
        say(f"{c['org'][:34]:34} {c['score']:>6.3f} {c['solved']:>3}/{c['runs']:<4} "
            f"{c['cost_usd']:>8.4f} {c['breakers']:>7} {c['errors']:>4}")
    if not llm.MOCK:
        say(f"spent so far: ${llm.LEDGER.spent:.4f} of ${llm.LEDGER.budget:.2f} over {llm.LEDGER.calls} calls")


def load_resume(rdir):
    """Rebuild population, history and lineage from a previous run directory."""
    lineage = json.load(open(os.path.join(rdir, "lineage.json")))
    pop, history = [], []
    for node in lineage:
        card_path = os.path.join(rdir, "cards", f"{node['name']}.json")
        org_path = os.path.join(rdir, "orgs", f"{node['name']}.yaml")
        if node["kept"] and os.path.exists(card_path) and os.path.exists(org_path):
            pop.append((orgmod.load(org_path), json.load(open(card_path))))
        if node.get("mutation"):
            history.append({"mutation": f"{evolve.describe(node['mutation'])} on {node['parent']}",
                            "result": f"-> {node['score']} ({'kept' if node['kept'] else 'discarded'})"})
    start_gen = max(n["gen"] for n in lineage) + 1
    return lineage, history, pop, start_gen


def run(seed_orgs, out_dir, log=None, generations=3, parents=2, children=2, seeds=1,
        final_seeds=2, random_mutations=False, resume=None, train="train", heldout="heldout",
        say=print):
    """Run evolution. Writes lineage.json, cards/, orgs/ and final.json into
    `out_dir`. Returns {"lineage", "best_human", "champion", "final", "stopped"}."""
    os.makedirs(os.path.join(out_dir, "orgs"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "cards"), exist_ok=True)
    log = log or engine.EventLog(os.path.join(out_dir, "events.jsonl"))
    names, stopped = set(), None

    def record(o, card, gen, parent=None, mutation=None, kept=True):
        names.add(o["name"])
        orgmod.dump(o, os.path.join(out_dir, "orgs", f"{o['name']}.yaml"))
        evaluate.save(card, os.path.join(out_dir, "cards", f"{o['name']}.json"))
        lineage.append({"name": o["name"], "gen": gen, "parent": parent, "mutation": mutation,
                        "kept": kept, "structure": orgmod.summary(o), "score": card["score"],
                        "solved": card["solved"], "runs": card["runs"], "cost_usd": card["cost_usd"],
                        "breakers": card["breakers"], "errors": card["errors"]})
        evaluate.save(lineage, os.path.join(out_dir, "lineage.json"))

    def unique_name(parent_name, gen):
        root = parent_name.split("~")[0]
        for k in range(26 * 4):
            cand = f"{root}~g{gen}{chr(97 + k % 26)}{'' if k < 26 else k // 26}"
            if cand not in names:
                return cand
        return f"{root}~g{gen}_{int(time.time() * 1000)}"

    if resume:
        lineage, history, pop, start_gen = load_resume(resume)
        names.update(n["name"] for n in lineage)
        evaluate.save(lineage, os.path.join(out_dir, "lineage.json"))
        for o, c in pop:
            orgmod.dump(o, os.path.join(out_dir, "orgs", f"{o['name']}.yaml"))
            evaluate.save(c, os.path.join(out_dir, "cards", f"{o['name']}.json"))
        gen0 = [(o, c) for o, c in pop if "~" not in o["name"]]
        say(f"resumed {len(pop)} kept orgs from {resume}, continuing at generation {start_gen}")
    else:
        lineage, history, pop, start_gen = [], [], [], 1
        say("generation 0: human org charts")
        for o in seed_orgs:  # BudgetExceeded here propagates: nothing to compare yet
            card = evaluate.evaluate(o, train, seeds=seeds, log=log)
            pop.append((o, card))
            record(o, card, 0)
        table([c for _, c in pop], "gen 0 (train)", say)
        gen0 = list(pop)

    best_human = max(gen0 or pop, key=lambda p: rank_key(p[1]))

    try:
        for g in range(start_gen, start_gen + generations):
            ranked = sorted(pop, key=lambda p: (-p[1]["score"], p[1]["cost_usd"]))[:parents]
            for parent, pcard in ranked:
                for _ in range(children):
                    child, mut = (evolve.random_mutation(parent) if random_mutations
                                  else evolve.meta_mutation(parent, pcard, history))
                    if not child:
                        continue
                    child["name"] = unique_name(parent["name"], g)
                    child["description"] = f"Mutant of {parent['name']}: {evolve.describe(mut)}"
                    card = evaluate.evaluate(child, train, seeds=seeds, log=log)
                    kept = gate(card, pcard)
                    log.emit(org=child["name"], task="*", type="spawn", parent=parent["name"],
                             mutation=mut, score=card["score"], kept=kept)
                    record(child, card, g, parent["name"], mut, kept=kept)
                    history.append({"mutation": f"{evolve.describe(mut)} on {parent['name']}",
                                    "result": f"{pcard['score']} -> {card['score']} "
                                              f"({'kept' if kept else 'discarded'})"})
                    say(f"  g{g} {child['name']:30} {evolve.describe(mut)[:34]:34} "
                        f"{pcard['score']:.3f} -> {card['score']:.3f}  {'KEPT' if kept else 'discarded'}"
                        f"{'  (errors: ' + str(card['errors']) + ')' if card['errors'] else ''}")
                    if kept:
                        pop.append((child, card))
            table([c for _, c in pop], f"population after gen {g}", say)
    except llm.BudgetExceeded as e:
        stopped = str(e)
        say(f"\n{e}; stopping evolution and moving to the held-out exam.")
    except KeyboardInterrupt:
        stopped = "interrupted"
        say("\nstopped by you; moving to the held-out exam (Ctrl-C again to quit).")

    champion = max(pop, key=lambda p: rank_key(p[1]))
    say(f"\nHELD-OUT EXAM (tasks evolution never saw), seeds={final_seeds}")
    say(f"best human org : {best_human[0]['name']}  {orgmod.summary(best_human[0])}")
    say(f"evolved champion: {champion[0]['name']}  {orgmod.summary(champion[0])}")
    contenders, seen = [], set()
    baseline = [o for o, _ in pop if o["name"] == "flat_startup"]
    for o in [best_human[0], champion[0]] + baseline:
        if o["name"] not in seen:
            seen.add(o["name"])
            contenders.append(o)
    final = []
    for o in contenders:
        try:
            final.append(evaluate.evaluate(o, heldout, seeds=final_seeds, log=log))
        except llm.BudgetExceeded as e:
            say(f"{e}; held-out exam incomplete.")
            break
        evaluate.save({"best_human": best_human[0]["name"], "champion": champion[0]["name"],
                       "heldout": final}, os.path.join(out_dir, "final.json"))
    if final:
        table(final, "HELD-OUT", say)
    return {"lineage": lineage, "best_human": best_human[0], "champion": champion[0],
            "final": final, "stopped": stopped}
