"""Run one org on one task. Each team runs its own pipeline in parallel, then
the org's governance rule picks the answer. Every step goes to an event log
so a run can be replayed later without calling any model."""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import llm, org as orgmod, sandbox, search

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPTS = {k: open(os.path.join(ROOT, "prompts", f"{k}.md")).read()
           for k in ("spec", "plan", "implement", "review", "select", "route")}
MAX_STEPS = 40  # hard stop on any pathological org


# ---------------------------------------------------------------- tasks
def load_task(task_dir):
    t = {"name": os.path.basename(task_dir), "dir": task_dir}
    for key, fname in (("issue", "issue.md"), ("starter", "starter.py"),
                       ("hidden", "hidden_test.py")):
        with open(os.path.join(task_dir, fname)) as f:
            t[key] = f.read()
    m = re.search(r"def (\w+)\(", t["starter"])
    t["func"] = m.group(1) if m else "solution"
    return t


# ---------------------------------------------------------------- events
class EventLog:
    def __init__(self, path=None):
        self.path = path
        self.t0 = time.time()
        self._lock = threading.Lock()
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)

    def emit(self, **ev):
        ev["t"] = round(time.time() - self.t0, 2)
        if self.path:
            with self._lock, open(self.path, "a") as f:
                f.write(json.dumps(ev) + "\n")
        return ev


# ---------------------------------------------------------------- helpers
def _compiles(code):
    try:
        compile(code, "<candidate>", "exec")
        return True
    except (SyntaxError, ValueError):
        return False


def _code_block(text, must_contain=None):
    """Extract runnable Python from a model reply. Tolerates any fence tag,
    a missing closing fence (reply cut off) and unfenced code. Prefers the
    block that contains `must_contain` and compiles."""
    text = text or ""
    blocks = re.findall(r"```[ \t]*[\w+-]*[ \t]*\n(.*?)```", text, re.S)
    if not blocks:
        tail = re.split(r"```[ \t]*[\w+-]*[ \t]*\n", text)
        if len(tail) > 1:
            blocks = [tail[-1]]  # unterminated fence: take what we got
        elif re.search(r"^\s*(def |import |from |class )", text, re.M):
            blocks = [text]
    blocks = [b.strip() + "\n" for b in blocks if b.strip()]
    if must_contain:
        preferred = [b for b in blocks if must_contain in b]
        blocks = preferred or blocks
    good = [b for b in blocks if _compiles(b)]
    pool = good or blocks
    return max(pool, key=len) if pool else None


def _ask(kind, user, model=None, max_tokens=2048):
    return llm.chat([{"role": "system", "content": PROMPTS[kind]},
                     {"role": "user", "content": user}], model=model, max_tokens=max_tokens)


def _context(state, org, stage):
    """What this role gets to see. Shared memory = every finding so far
    (across all non-isolated teams); otherwise only the issue plus the
    direct handoff artifacts."""
    parts = [f"ISSUE: {state['task']['issue']}",
             f"CURRENT MODULE:\n```python\n{state['task']['starter']}```"]
    if stage.get("search") and state.get("references"):
        parts.append(f"REFERENCES (web search):\n{state['references']}")
    if state.get("plan"):
        parts.append(f"DIRECTION:\n{state['plan']}")
    if state.get("team_tests") and stage["kind"] in ("implement", "review", "select"):
        parts.append(f"DEFINITION OF DONE (team tests):\n```python\n{state['team_tests']}```")
    if state.get("feedback") and stage["kind"] == "implement":
        parts.append("SENT BACK. Fix these problems:\n" + state["feedback"])
        if state.get("code"):
            parts.append(f"YOUR PREVIOUS ATTEMPT:\n```python\n{state['code']}```")
    if org["shared_memory"] and state["notes"]:
        parts.append("TEAM NOTES (shared memory):\n" + "\n".join(list(state["notes"])[-12:]))
    return "\n\n".join(parts)


def _note(state, text):
    line = f"[{state['team']}/{text}" if state["multi"] else f"[{text}"
    state["notes"].append(line)
    state["own_notes"].append(line)


def _parallel(fn, n):
    with ThreadPoolExecutor(max_workers=max(1, n)) as ex:
        return list(ex.map(lambda _: fn(), range(n)))


# ---------------------------------------------------------------- stages
def _run_stage(stage, state, org, emit):
    kind, sid = stage["kind"], stage["id"]
    if stage.get("search") and "references" not in state:
        q = f"{state['task']['issue']} python {state['task']['func']} edge cases specification"
        state["references"] = search.web_search(q)
        emit(type="search", role=sid, hits=bool(state["references"]))

    if kind == "spec":
        tests = ""
        for _attempt in range(2):  # one retry if the tests don't even compile
            text, cost = _ask("spec", _context(state, org, stage))
            state["cost"] += cost
            tests = _code_block(text, must_contain="def test_") or ""
            if tests and _compiles(tests) and "def test_" in tests:
                break
            tests = ""
        state["team_tests"] = tests
        n = len(re.findall(r"\ndef test_", "\n" + tests))
        _note(state, f"{sid}] wrote {n} acceptance tests" if n else f"{sid}] could not write valid tests")
        return "next", {"tests": n}

    if kind == "plan":
        text, cost = _ask("plan", _context(state, org, stage), max_tokens=800)
        state["cost"] += cost
        state["plan"] = text.strip()[:2000]
        _note(state, f"{sid}] set direction")
        return "next", {}

    if kind == "implement":
        n = max(1, int(stage.get("parallel", 1)))
        ctx = _context(state, org, stage)
        outs = _parallel(lambda: _ask("implement", ctx, max_tokens=3000), n)
        func = f"def {state['task']['func']}("
        cands = []
        for text, cost in outs:
            state["cost"] += cost
            code = _code_block(text, must_contain=func)
            if code and _compiles(code) and func in code:
                cands.append(code)
        state["candidates"] = cands or [state.get("code") or state["task"]["starter"]]
        state["code"] = state["candidates"][0]
        state["feedback"] = ""
        _note(state, f"{sid}] produced {len(cands)} candidate(s)")
        return "next", {"candidates": len(cands)}

    if kind == "select":
        cands = state.get("candidates") or [state["code"]]
        if len(cands) == 1:
            return "next", {"picked": 0}
        if stage.get("by") == "tests" and state.get("team_tests"):
            scores = [sandbox.run_tests(c, state["team_tests"])["passed"] for c in cands]
            pick = max(range(len(cands)), key=lambda i: scores[i])
        else:
            listing = "\n\n".join(f"CANDIDATE {i + 1}:\n```python\n{c}```" for i, c in enumerate(cands))
            text, cost = _ask("select", _context(state, org, stage) + "\n\n" + listing, max_tokens=400)
            state["cost"] += cost
            pick = _parse_choice(text, len(cands))
        state["code"] = cands[pick]
        state["candidates"] = [cands[pick]]
        _note(state, f"{sid}] picked candidate {pick + 1} of {len(cands)}")
        return "next", {"picked": pick, "of": len(cands)}

    if kind == "verify":
        if not state.get("team_tests"):
            return "next", {"skipped": True}
        r = sandbox.run_tests(state["code"], state["team_tests"])
        ok = r["total"] > 0 and r["passed"] == r["total"]
        _note(state, f"{sid}] team tests {r['passed']}/{r['total']}")
        if ok:
            return "next", {"passed": r["passed"], "total": r["total"]}
        state["feedback"] = f"Team tests failing ({r['passed']}/{r['total']}):\n{r['output'][-1200:]}"
        return "fail", {"passed": r["passed"], "total": r["total"]}

    if kind == "review":
        if stage.get("blind"):
            # Blind reviewer: judges evidence (tests + results), never the code.
            evidence = "No team tests were written."
            if state.get("team_tests"):
                r = sandbox.run_tests(state["code"], state["team_tests"])
                evidence = f"Team tests passed {r['passed']}/{r['total']}.\n{r['output'][-800:]}"
            user = (f"ISSUE: {state['task']['issue']}\n\nYou may NOT see the code. Judge only "
                    f"whether the definition of done is complete and the evidence shows it is met.\n\n"
                    f"DEFINITION OF DONE:\n```python\n{state.get('team_tests', '')}```\n\nEVIDENCE:\n{evidence}")
        else:
            user = _context(state, org, stage) + f"\n\nPROPOSED MODULE:\n```python\n{state['code']}```"
        voters = max(1, int(stage.get("voters", 1)))
        outs = _parallel(lambda: _ask("review", user, max_tokens=800), voters)
        approvals, reasons = 0, []
        for text, cost in outs:
            state["cost"] += cost
            m = re.search(r"VERDICT\W*(APPROVE|REJECT)", text.upper())
            ok = (m.group(1) == "APPROVE") if m else ("REJECT" not in text.upper())
            approvals += ok
            if not ok and "\n" in text:
                reasons.append(text.split("\n", 1)[1].strip()[:400])
        approve = approvals == voters if stage.get("rule") == "unanimous" else approvals * 2 > voters
        feedback = "\n".join(dict.fromkeys(reasons))[:900]
        tally = f" ({approvals}/{voters} approve)" if voters > 1 else ""
        _note(state, f"{sid}] {'approved' if approve else 'rejected'}{tally}"
                     f"{'' if approve else ': ' + feedback[:140]}")
        info = {"approve": approve, "approvals": approvals, "voters": voters}
        if approve or not stage.get("can_veto", True):
            if not approve:
                state["feedback"] = feedback  # advisory only
            return "next", info
        state["feedback"] = feedback
        return "reject", info

    raise ValueError(f"unknown kind {kind}")


def _parse_choice(text, n):
    m = re.search(r"CHOICE\W*(\d+)", text or "", re.I)
    return min(n, max(1, int(m.group(1)))) - 1 if m else 0


# ---------------------------------------------------------------- one team
def _run_team(org, team, task, emit, shared_notes):
    multi = len(org["teams"]) > 1
    own = []
    notes = shared_notes if (org["shared_memory"] and not team["isolated"]) else own
    state = {"task": task, "team": team["name"], "multi": multi, "code": task["starter"],
             "notes": notes, "own_notes": [], "cost": 0.0, "feedback": "", "team_tests": ""}
    stages = team["stages"]
    ids = [s["id"] for s in stages]
    max_rounds = int(team.get("max_rounds", org["max_rounds"]))
    i, rounds, steps, outcome = 0, 0, 0, "shipped"
    seen_code = set()  # loop detection: an implementer re-submitting old work

    def trip_breaker(role, why):
        state["breaker"] = why
        emit(type="breaker", role=role, rounds=rounds, action=org["on_breaker"], why=why)
        if org["on_breaker"] == "escalate":
            emit(type="page_human", role=role, why=why, last_feedback=state["feedback"][:300])
            return "escalated"
        return "shipped"

    while i < len(stages):
        steps += 1
        if steps > MAX_STEPS:
            outcome = trip_breaker(stages[i]["id"], "step limit")
            break
        stage = stages[i]
        emit(type="stage_start", role=stage["id"], kind=stage["kind"])
        try:
            result, info = _run_stage(stage, state, org, emit)
        except llm.BudgetExceeded:
            outcome = "budget"
            break
        emit(type="stage_end", role=stage["id"], result=result, **info)

        if stage["kind"] == "implement":
            key = state["code"].strip()
            if rounds > 0 and key in seen_code:
                emit(type="loop_detected", role=stage["id"], rounds=rounds)
                _note(state, f"{stage['id']}] loop detected: resubmitted earlier work")
                outcome = trip_breaker(stage["id"], "loop detected")
                break
            seen_code.add(key)

        if result == "next":
            if i + 1 < len(stages):
                emit(type="handoff", **{"from": stage["id"]}, to=stages[i + 1]["id"])
            i += 1
            continue

        rounds += 1  # work sent back: reject (review) or fail (verify)
        if rounds >= max_rounds:
            outcome = trip_breaker(stage["id"], f"{rounds} send-backs")
            break
        target = stage.get("on_reject") if result == "reject" else stage.get("on_fail")
        target = target or next(s["id"] for s in stages if s["kind"] == "implement")
        emit(type=result, **{"from": stage["id"]}, to=target, reason=state["feedback"][:200])
        i = ids.index(target)

    return {"team": team["name"], "code": state["code"], "cost": state["cost"],
            "team_tests": state.get("team_tests", ""), "outcome": outcome, "rounds": rounds,
            "breaker": state.get("breaker"), "notes": state["own_notes"]}


# ---------------------------------------------------------------- governance
def _decide(org, task, results, emit):
    """Pick one team's answer. Returns (index, cost)."""
    eligible = [i for i, r in enumerate(results) if r["outcome"] not in ("escalated", "budget")]
    pool = eligible or list(range(len(results)))
    if len(pool) == 1:
        emit(type="decision", by="only_candidate", picked=results[pool[0]]["team"])
        return pool[0], 0.0
    d = org["decide"]
    all_tests = [r["team_tests"] for r in results if r["team_tests"]]

    def test_scores():
        return {i: sum(sandbox.run_tests(results[i]["code"], t)["passed"] for t in all_tests) for i in pool}

    by = d["by"] if not (d["by"] == "tests" and not all_tests) else "leader"
    if by == "tests":
        scores = test_scores()
        pick = max(pool, key=lambda i: (scores[i], -results[i]["cost"]))
        emit(type="decision", by="tests", picked=results[pick]["team"],
             scores={results[i]["team"]: s for i, s in scores.items()})
        return pick, 0.0

    listing = "\n\n".join(f"CANDIDATE {k + 1} (from team {results[i]['team']}):\n```python\n{results[i]['code']}```"
                          for k, i in enumerate(pool))
    user = f"ISSUE: {task['issue']}\n\nCURRENT MODULE:\n```python\n{task['starter']}```\n\n{listing}"
    voters = 1 if by == "leader" else max(1, int(d["voters"]))
    outs = _parallel(lambda: _ask("select", user, max_tokens=400), voters)
    cost = sum(c for _, c in outs)
    votes = [pool[_parse_choice(t, len(pool))] for t, _ in outs]
    tally = {i: votes.count(i) for i in pool}
    top = max(tally.values())
    leaders = [i for i in pool if tally[i] == top]
    if len(leaders) > 1 and all_tests:  # tie: evidence breaks it
        scores = test_scores()
        leaders.sort(key=lambda i: -scores[i])
    pick = leaders[0]
    emit(type="decision", by=by, picked=results[pick]["team"],
         votes={results[i]["team"]: tally[i] for i in pool})
    return pick, cost


def _route(org, task):
    """Divisional governance: a dispatcher assigns the task to one team."""
    listing = "\n".join(f"- {t['name']}: focus: {t.get('focus') or '(none)'}; "
                        f"structure: {orgmod.summary({**org, 'teams': [t]}).split('  [')[0]}"
                        for t in org["teams"])
    text, cost = _ask("route", f"ISSUE: {task['issue']}\n\nDIVISIONS:\n{listing}", max_tokens=300)
    m = re.search(r"TEAM\W*([\w-]+)", text or "", re.I)
    names = {t["name"]: t for t in org["teams"]}
    if m and m.group(1) in names:
        return names[m.group(1)], cost
    for t in org["teams"]:  # tolerate a name mentioned without the TEAM: prefix
        if t["name"] in (text or ""):
            return t, cost
    return org["teams"][0], cost


# ---------------------------------------------------------------- run
def run(org, task, log=None, run_tag=""):
    """Run `org` on `task`. Returns a result dict with the hidden-test score."""
    log = log or EventLog()
    name = f"{task['name']}{run_tag}"

    def emitter(team=None):
        def emit(**ev):
            base = {"org": org["name"], "task": name}
            if team is not None and len(org["teams"]) > 1:
                base["team"] = team
            return log.emit(**base, **ev)
        return emit

    emit = emitter()
    emit(type="start", teams=[t["name"] for t in org["teams"]])
    shared_notes = []
    teams = org["teams"]
    route_cost = 0.0
    if org["decide"]["by"] == "router" and len(teams) > 1:
        try:
            chosen_team, route_cost = _route(org, task)
        except llm.BudgetExceeded:
            chosen_team = teams[0]
        emit(type="route", to=chosen_team["name"])
        teams = [chosen_team]
    with ThreadPoolExecutor(max_workers=len(teams)) as ex:
        futs = [ex.submit(_run_team, org, t, task, emitter(t["name"]), shared_notes) for t in teams]
        results = [f.result() for f in futs]  # re-raises FatalAPIError

    decision_cost = route_cost
    if len(results) == 1:
        pick = 0
    else:
        try:
            pick, cost_d = _decide(org, task, results, emit)
            decision_cost += cost_d
        except llm.BudgetExceeded:
            pick = 0
    chosen = results[pick]
    outcomes = {r["outcome"] for r in results}
    if outcomes == {"escalated"}:
        outcome = "escalated"
    elif "budget" in outcomes and chosen["outcome"] == "budget":
        outcome = "budget"
    else:
        outcome = chosen["outcome"] if chosen["outcome"] != "escalated" else "shipped"

    hidden = sandbox.run_tests(chosen["code"], task["hidden"])
    score = hidden["passed"] / hidden["total"] if hidden["total"] else 0.0
    cost = sum(r["cost"] for r in results) + decision_cost
    breakers = [r["breaker"] for r in results if r["breaker"]]
    res = {"org": org["name"], "task": task["name"], "score": round(score, 3),
           "passed": hidden["passed"], "total": hidden["total"], "outcome": outcome,
           "rounds": sum(r["rounds"] for r in results), "cost_usd": round(cost, 5),
           "code": chosen["code"], "picked_team": chosen["team"],
           "notes": [n for r in results for n in r["notes"]],
           "breaker": chosen["breaker"] or (breakers[0] if outcome == "escalated" and breakers else None)}
    emit(type="done", outcome=outcome, score=res["score"], rounds=res["rounds"],
         cost_usd=res["cost_usd"], picked=chosen["team"])
    return res
