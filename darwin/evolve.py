"""Evolution: a meta-agent (Nemotron Super) reads how each org failed and
proposes ONE structural mutation. A mutant survives only if it beats its
parent on the training tasks. Prompts never change, only structure.

Structure includes the shape of the whole organization, not just one
pipeline: teams can be spun off, isolated, merged away, and governance can
move between evidence (tests), a single leader, and a council of peers.
"""
import copy
import json
import random
import re

from . import llm, org as orgmod

MAX_TEAMS = 4

OPS = {
    # --- inside one team (give `team`; defaults to the first team)
    "add_review":       "insert a reviewer with veto power after the team's implement stage",
    "add_blind_review": "insert a BLIND reviewer (sees tests and results, never the code)",
    "set_panel":        "turn a review stage into a panel of `n` voters (1, 3 or 5) with `rule` majority|unanimous (give `stage`)",
    "remove_stage":     "remove one non-implement stage (give `stage`)",
    "toggle_blind":     "flip a reviewer between blind and sighted (give `stage`)",
    "toggle_veto":      "flip whether a reviewer can send work back (give `stage`)",
    "set_parallel":     "set how many disposable clones attempt the implementation (give `n`: 1, 3 or 5)",
    "toggle_search":    "give or take away You.com web search for a stage (give `stage`)",
    "add_spec":         "add a role that writes the definition of done as tests before any work",
    "add_verify":       "add a step that runs the team's own tests before shipping",
    # --- the shape of the organization
    "add_skunkworks":   "spin up a new small ISOLATED team (one implementer with web search) that works in secret",
    "fork_team":        "clone an existing team (give `team`) as a new isolated team that competes with it",
    "remove_team":      "dissolve a team (give `team`); at least one team must remain",
    "toggle_isolated":  "cut a team off from (or reconnect it to) the others' shared findings (give `team`)",
    "set_governance":   "change how teams are governed: `by` tests|leader|council (teams compete, one answer is chosen) or router (a dispatcher sends each task to ONE team, like divisions); council size `n` (3 or 5)",
    "toggle_shared_memory": "turn instant shared memory across non-isolated teams on or off",
    "set_max_rounds":   "change how many send-backs a team gets before the circuit breaker (give `n`: 1-6)",
    "flip_breaker":     "switch the circuit breaker between escalate-to-human and ship-best-so-far",
}


# Which parameters each mutation actually uses (others are dropped from logs).
PARAMS = {
    "add_review": ("team",), "add_blind_review": ("team",),
    "set_panel": ("team", "stage", "n", "rule"), "remove_stage": ("team", "stage"),
    "toggle_blind": ("team", "stage"), "toggle_veto": ("team", "stage"),
    "set_parallel": ("team", "n"), "toggle_search": ("team", "stage"),
    "add_spec": ("team",), "add_verify": ("team",), "add_skunkworks": (),
    "fork_team": ("team",), "remove_team": ("team",), "toggle_isolated": ("team",),
    "set_governance": ("by", "n"), "toggle_shared_memory": (), "set_max_rounds": ("n",),
    "flip_breaker": (),
}
assert set(PARAMS) == set(OPS)


def _relevant(op, args):
    return {k: args[k] for k in PARAMS.get(op, ()) if args.get(k) is not None}


def _team(o, name):
    if name is not None:
        return next((t for t in o["teams"] if t["name"] == name), None)
    return o["teams"][0]


def _impl_index(st):
    return next(i for i, s in enumerate(st) if s["kind"] == "implement")


def _uid(items, base, key="id"):
    taken = {x[key] for x in items}
    n, cand = 1, base
    while cand in taken:
        n += 1
        cand = f"{base}_{n}"
    return cand


def apply(o, op, team=None, stage=None, n=None, by=None, rule=None):
    """Apply one mutation. Returns the new org, or None if it doesn't apply."""
    o = copy.deepcopy(o)
    if team is None and stage is not None:  # infer the team from the stage
        team = next((t["name"] for t in o["teams"] if any(s["id"] == stage for s in t["stages"])), None)
    t = _team(o, team)
    if t is None:
        return None
    st = t["stages"]
    before = json.dumps(o, sort_keys=True)
    named = next((s for s in st if s["id"] == stage), None)
    ii = _impl_index(st)
    impl_id = st[ii]["id"]

    def after_impl():
        j = ii + 1
        while j < len(st) and st[j]["kind"] == "select":
            j += 1
        return j

    if op in ("add_review", "add_blind_review"):
        blind = op == "add_blind_review"
        st.insert(after_impl(), {"id": _uid(st, "blind_reviewer" if blind else "reviewer"),
                                 "kind": "review", "blind": blind, "can_veto": True,
                                 "on_reject": impl_id, "search": False})
    elif op == "set_panel":
        if not named or named["kind"] != "review":
            return None
        named["voters"] = max(1, min(5, int(n or random.choice([1, 3, 5]))))
        named["rule"] = rule if rule in orgmod.RULES else random.choice(sorted(orgmod.RULES))
    elif op == "remove_stage":
        if not named or named["kind"] == "implement":
            return None
        st.remove(named)
        for s in st:  # repoint back-edges at the removed stage
            for k in ("on_reject", "on_fail"):
                if s.get(k) == named["id"]:
                    s[k] = impl_id
        if not any(s["kind"] == "spec" for s in st):
            st[:] = [s for s in st if s["kind"] != "verify"]
    elif op in ("toggle_blind", "toggle_veto"):
        if not named or named["kind"] != "review":
            return None
        key = "blind" if op == "toggle_blind" else "can_veto"
        named[key] = not named.get(key, key == "can_veto")
    elif op == "set_parallel":
        n = max(1, min(5, int(n or random.choice([1, 3, 5]))))
        st[ii]["parallel"] = n
        has_select = ii + 1 < len(st) and st[ii + 1]["kind"] == "select"
        if n > 1 and not has_select:
            st.insert(ii + 1, {"id": _uid(st, "selector"), "kind": "select", "by": "tests", "search": False})
        if n == 1 and has_select:
            st.pop(ii + 1)
    elif op == "toggle_search":
        if not named:
            return None
        named["search"] = not named.get("search", False)
    elif op == "add_spec":
        if any(s["kind"] == "spec" for s in st):
            return None
        st.insert(0, {"id": _uid(st, "spec_writer"), "kind": "spec", "search": False})
    elif op == "add_verify":
        if any(s["kind"] == "verify" for s in st):
            return None
        if not any(s["kind"] == "spec" for s in st):
            st.insert(0, {"id": _uid(st, "spec_writer"), "kind": "spec", "search": False})
        st.append({"id": _uid(st, "verifier"), "kind": "verify", "on_fail": impl_id, "search": False})
    elif op == "add_skunkworks":
        if len(o["teams"]) >= MAX_TEAMS:
            return None
        o["teams"].append({"name": _uid(o["teams"], "skunkworks", key="name"), "isolated": True,
                           "stages": [{"id": "builder", "kind": "implement", "parallel": 1, "search": True}]})
    elif op == "fork_team":
        if len(o["teams"]) >= MAX_TEAMS:
            return None
        clone = copy.deepcopy(t)
        clone["name"] = _uid(o["teams"], f"{t['name']}_fork", key="name")
        clone["isolated"] = True
        o["teams"].append(clone)
    elif op == "remove_team":
        if len(o["teams"]) <= 1:
            return None
        o["teams"].remove(t)
    elif op == "toggle_isolated":
        if len(o["teams"]) <= 1:
            return None
        t["isolated"] = not t["isolated"]
    elif op == "set_governance":
        by = by if by in orgmod.DECIDE_BY else random.choice(sorted(orgmod.DECIDE_BY))
        o["decide"] = {"by": by, "voters": max(3, min(5, int(n or 3))) if by == "council" else 1}
    elif op == "toggle_shared_memory":
        o["shared_memory"] = not o["shared_memory"]
    elif op == "set_max_rounds":
        o["max_rounds"] = max(1, min(6, int(n or random.choice([1, 2, 4, 6]))))
    elif op == "flip_breaker":
        o["on_breaker"] = "ship" if o["on_breaker"] == "escalate" else "escalate"
    else:
        return None

    if json.dumps(o, sort_keys=True) == before:
        return None  # no-op mutation: nothing to test
    try:
        return orgmod.normalize(o)
    except (AssertionError, KeyError, ValueError, TypeError):
        return None


def random_mutation(o):
    for _ in range(40):
        op = random.choice(list(OPS))
        t = random.choice(o["teams"])
        stage = random.choice(t["stages"])["id"]
        child = apply(o, op, team=t["name"], stage=stage)
        if child:
            return child, {"op": op, **_relevant(op, {"team": t["name"], "stage": stage}),
                           "source": "random"}
    return None, None


META_PROMPT = """You redesign the ORGANIZATIONAL STRUCTURE of AI agents that fix vague
software issues. You cannot change prompts or models, only the structure.
Do not assume a single boss is best. Consider independent competing teams,
isolated skunkworks, councils of peers that vote, evidence-based decisions,
or one simple team. AI agents are cheap, can be cloned, can share memory
instantly, and never get tired or offended.

Allowed mutations (choose exactly ONE):
{ops}

Parameters: `team` (team name), `stage` (stage id), `n` (number),
`by` (tests|leader|council|router), `rule` (majority|unanimous).
Reply with ONLY a JSON object, for example
{{"op": "add_skunkworks", "reason": "..."}}
{{"op": "set_governance", "by": "council", "n": 3, "reason": "..."}}
{{"op": "set_panel", "team": "team", "stage": "attending", "n": 3, "rule": "majority", "reason": "..."}}
"""


def meta_mutation(o, card, history):
    """Ask the meta-agent for a mutation grounded in this org's failures."""
    ops = "\n".join(f"- {k}: {v}" for k, v in OPS.items())
    tried = "\n".join(f"- {h['mutation']} -> {h['result']}" for h in history[-8:]) or "(none yet)"
    shape = {"teams": o["teams"], "decide": o["decide"], "shared_memory": o["shared_memory"],
             "max_rounds": o["max_rounds"], "on_breaker": o["on_breaker"]}
    user = (f"CURRENT ORG: {orgmod.summary(o)}\n\nSTRUCTURE:\n{json.dumps(shape, indent=1)}\n\n"
            f"SCORECARD: score={card['score']} solved={card['solved']}/{card['runs']} "
            f"cost=${card['cost_usd']} escalations={card['escalations']}\n\n"
            f"WHERE IT FAILED (team notes):\n{json.dumps(card['failures'], indent=1)[:3500]}\n\n"
            f"MUTATIONS ALREADY TRIED AND THEIR RESULTS:\n{tried}\n\n"
            f"Propose the single structural change most likely to raise the score.")
    try:
        msgs = [{"role": "system", "content": META_PROMPT.format(ops=ops)},
                {"role": "user", "content": user}]
        try:
            text, _ = llm.chat(msgs, model=llm.META_MODEL, max_tokens=1500, temperature=0.8)
        except llm.FatalAPIError as e:
            if llm.META_MODEL == llm.WORKER_MODEL:
                raise
            # Meta model unavailable: keep evolving with the worker model.
            print(f"  (meta model unavailable, using {llm.WORKER_MODEL}: {str(e)[:120]})")
            llm.META_MODEL = llm.WORKER_MODEL
            text, _ = llm.chat(msgs, model=llm.META_MODEL, max_tokens=1500, temperature=0.8)
        m = re.search(r"\{.*\}", text, re.S)
        spec = json.loads(m.group(0)) if m else {}
        args = {k: spec.get(k) for k in ("team", "stage", "n", "by", "rule")}
        child = apply(o, spec.get("op"), **args)
        if child:
            return child, {"op": spec.get("op"), **_relevant(spec.get("op"), args),
                           "reason": str(spec.get("reason", ""))[:300], "source": "meta-agent"}
    except (llm.BudgetExceeded, llm.FatalAPIError):
        raise
    except Exception:
        pass
    return random_mutation(o)  # fall back so evolution never stalls


def describe(mut):
    """Short human-readable label for a mutation, e.g. 'set_panel attending n=3 majority'."""
    if not mut:
        return "?"
    bits = [str(mut.get("op"))]
    for k in ("team", "stage", "by", "n", "rule"):
        v = mut.get(k)
        if v is not None and v != "":
            bits.append(f"{k}={v}" if k in ("n", "by", "rule") else str(v))
    return " ".join(bits)
