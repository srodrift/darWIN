"""Evolution: a meta-agent (Nemotron Super) reads how each org failed and
proposes ONE structural mutation. A mutant survives only if it beats its
parent on the training tasks. Prompts never change, only structure.

Mutation menu (non-human options included: disposable parallel clones,
blind reviewers, instant shared memory):
"""
import copy
import json
import random
import re

from . import llm, org as orgmod

OPS = {
    "add_review":      "insert a reviewer with veto power after the implement stage",
    "add_blind_review": "insert a BLIND reviewer (sees tests and results, never the code)",
    "remove_stage":    "remove one non-implement stage (give `stage`)",
    "toggle_blind":    "flip a reviewer between blind and sighted (give `stage`)",
    "toggle_veto":     "flip whether a reviewer can send work back (give `stage`)",
    "set_parallel":    "set how many independent clones attempt the implementation (give `n`: 1, 3 or 5)",
    "toggle_shared_memory": "turn instant shared memory across all roles on or off",
    "toggle_search":   "give or take away You.com web search for a stage (give `stage`)",
    "add_spec":        "add a role that writes the definition of done as tests before any work",
    "add_verify":      "add a step that runs the team's own tests before shipping",
    "set_max_rounds":  "change how many send-backs are allowed before the circuit breaker (give `n`: 1-6)",
    "flip_breaker":    "switch the circuit breaker between escalate-to-human and ship-best-so-far",
}


def _impl_index(o):
    return next(i for i, s in enumerate(o["stages"]) if s["kind"] == "implement")


def _impl_id(o):
    return o["stages"][_impl_index(o)]["id"]


def _uid(o, base):
    ids = {s["id"] for s in o["stages"]}
    n, cand = 1, base
    while cand in ids:
        n += 1
        cand = f"{base}_{n}"
    return cand


def apply(o, op, stage=None, n=None):
    """Apply one mutation. Returns the new org, or None if it doesn't apply."""
    o = copy.deepcopy(o)
    st = o["stages"]
    ids = [s["id"] for s in st]
    named = next((s for s in st if s["id"] == stage), None)
    ii = _impl_index(o)

    def last_after_impl():
        # Insert right after implement (and after a select stage that follows it).
        j = ii + 1
        while j < len(st) and st[j]["kind"] == "select":
            j += 1
        return j

    if op in ("add_review", "add_blind_review"):
        blind = op == "add_blind_review"
        st.insert(last_after_impl(), {"id": _uid(o, "blind_reviewer" if blind else "reviewer"),
                                      "kind": "review", "blind": blind, "can_veto": True,
                                      "on_reject": _impl_id(o), "search": False})
    elif op == "remove_stage":
        if not named or named["kind"] == "implement":
            return None
        st.remove(named)
        for s in st:  # repoint any back-edges at the removed stage
            for k in ("on_reject", "on_fail"):
                if s.get(k) == named["id"]:
                    s[k] = _impl_id(o)
        if not any(s["kind"] in ("spec",) for s in st):
            for s in list(st):
                if s["kind"] == "verify":
                    st.remove(s)
    elif op in ("toggle_blind", "toggle_veto"):
        if not named or named["kind"] != "review":
            return None
        key = "blind" if op == "toggle_blind" else "can_veto"
        named[key] = not named.get(key, key == "can_veto")
    elif op == "set_parallel":
        n = int(n or random.choice([1, 3, 5]))
        n = max(1, min(5, n))
        impl = st[ii]
        if impl.get("parallel", 1) == n:
            return None
        impl["parallel"] = n
        has_select = ii + 1 < len(st) and st[ii + 1]["kind"] == "select"
        if n > 1 and not has_select:
            st.insert(ii + 1, {"id": _uid(o, "selector"), "kind": "select", "by": "tests", "search": False})
        if n == 1 and has_select:
            st.pop(ii + 1)
    elif op == "toggle_shared_memory":
        o["shared_memory"] = not o["shared_memory"]
    elif op == "toggle_search":
        if not named:
            return None
        named["search"] = not named.get("search", False)
    elif op == "add_spec":
        if any(s["kind"] == "spec" for s in st):
            return None
        st.insert(0, {"id": _uid(o, "spec_writer"), "kind": "spec", "search": False})
    elif op == "add_verify":
        if any(s["kind"] == "verify" for s in st):
            return None
        if not any(s["kind"] == "spec" for s in st):
            st.insert(0, {"id": _uid(o, "spec_writer"), "kind": "spec", "search": False})
        st.append({"id": _uid(o, "verifier"), "kind": "verify", "on_fail": _impl_id(o), "search": False})
    elif op == "set_max_rounds":
        n = max(1, min(6, int(n or random.choice([1, 2, 4, 6]))))
        if o["max_rounds"] == n:
            return None
        o["max_rounds"] = n
    elif op == "flip_breaker":
        o["on_breaker"] = "ship" if o["on_breaker"] == "escalate" else "escalate"
    else:
        return None

    if ids == [s["id"] for s in o["stages"]] and op in ("add_review", "add_blind_review", "add_spec", "add_verify", "remove_stage"):
        return None
    try:
        return orgmod.normalize(o)
    except AssertionError:
        return None


def random_mutation(o):
    for _ in range(30):
        op = random.choice(list(OPS))
        stage = random.choice(o["stages"])["id"]
        child = apply(o, op, stage=stage)
        if child:
            return child, {"op": op, "stage": stage, "by": "random"}
    return None, None


META_PROMPT = """You redesign the ORGANIZATIONAL STRUCTURE of a team of AI agents that fixes
vague software issues. You cannot change prompts or models, only the structure.
You may use structures no human company would use: AI agents are cheap, can be
cloned, can share memory instantly, and never get tired or offended.

Allowed mutations (choose exactly ONE):
{ops}

Reply with ONLY a JSON object, e.g.
{{"op": "set_parallel", "n": 5, "reason": "..."}} or
{{"op": "toggle_blind", "stage": "attending", "reason": "..."}}
"""


def meta_mutation(o, card, history):
    """Ask the meta-agent for a mutation grounded in this org's failures."""
    ops = "\n".join(f"- {k}: {v}" for k, v in OPS.items())
    tried = "\n".join(f"- {h['mutation']} -> {h['result']}" for h in history[-8:]) or "(none yet)"
    user = (f"CURRENT ORG: {orgmod.summary(o)}\n\nSTRUCTURE:\n{json.dumps(o['stages'], indent=1)}\n\n"
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
        child = apply(o, spec.get("op"), stage=spec.get("stage"), n=spec.get("n"))
        if child:
            return child, {"op": spec.get("op"), "stage": spec.get("stage"), "n": spec.get("n"),
                           "reason": str(spec.get("reason", ""))[:300], "by": "meta-agent"}
    except (llm.BudgetExceeded, llm.FatalAPIError):
        raise
    except Exception:
        pass
    return random_mutation(o)  # fall back so evolution never stalls
