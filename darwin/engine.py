"""Run one org on one task. Every step is written to an event log so the
3D view can replay it later without calling any model."""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import llm, sandbox, search

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPTS = {k: open(os.path.join(ROOT, "prompts", f"{k}.md")).read()
           for k in ("spec", "plan", "implement", "review", "select")}
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
    """What this role gets to see. Shared memory = everything; otherwise only
    the issue plus the direct handoff artifacts."""
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
        parts.append("TEAM NOTES (shared memory):\n" + "\n".join(state["notes"][-12:]))
    return "\n\n".join(parts)


# ---------------------------------------------------------------- stages
def _run_stage(stage, state, org, log, task_name):
    kind, sid = stage["kind"], stage["id"]
    if stage.get("search") and "references" not in state:
        q = f"{state['task']['issue']} python {state['task']['func']} edge cases specification"
        state["references"] = search.web_search(q)
        log.emit(org=org["name"], task=task_name, type="search", role=sid,
                 hits=bool(state["references"]))

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
        state["notes"].append(f"[{sid}] wrote {n} acceptance tests" if n else
                              f"[{sid}] could not write valid tests")
        return "next", {"tests": n}

    if kind == "plan":
        text, cost = _ask("plan", _context(state, org, stage), max_tokens=800)
        state["cost"] += cost
        state["plan"] = text.strip()[:2000]
        state["notes"].append(f"[{sid}] set direction")
        return "next", {}

    if kind == "implement":
        n = max(1, int(stage.get("parallel", 1)))
        ctx = _context(state, org, stage)
        with ThreadPoolExecutor(max_workers=n) as ex:
            outs = list(ex.map(lambda _: _ask("implement", ctx, max_tokens=3000), range(n)))
        cands = []
        for text, cost in outs:
            state["cost"] += cost
            code = _code_block(text, must_contain=f"def {state['task']['func']}(")
            if code and _compiles(code) and f"def {state['task']['func']}(" in code:
                cands.append(code)
        state["candidates"] = cands or [state.get("code") or state["task"]["starter"]]
        state["code"] = state["candidates"][0]
        state["feedback"] = ""
        state["notes"].append(f"[{sid}] produced {len(cands)} candidate(s)")
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
            m = re.search(r"CHOICE:\s*(\d+)", text)
            pick = min(len(cands), max(1, int(m.group(1)))) - 1 if m else 0
        state["code"] = cands[pick]
        state["candidates"] = [cands[pick]]
        state["notes"].append(f"[{sid}] picked candidate {pick + 1} of {len(cands)}")
        return "next", {"picked": pick, "of": len(cands)}

    if kind == "verify":
        if not state.get("team_tests"):
            return "next", {"skipped": True}
        r = sandbox.run_tests(state["code"], state["team_tests"])
        ok = r["total"] > 0 and r["passed"] == r["total"]
        state["notes"].append(f"[{sid}] team tests {r['passed']}/{r['total']}")
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
        text, cost = _ask("review", user, max_tokens=800)
        state["cost"] += cost
        m = re.search(r"VERDICT\W*(APPROVE|REJECT)", text.upper())
        approve = (m.group(1) == "APPROVE") if m else ("REJECT" not in text.upper())
        reasons = text.split("\n", 1)[1].strip()[:800] if "\n" in text else ""
        state["notes"].append(f"[{sid}] {'approved' if approve else 'rejected: ' + reasons[:160]}")
        if approve or not stage.get("can_veto", True):
            if not approve:
                state["feedback"] = reasons  # advisory only
            return "next", {"approve": approve}
        state["feedback"] = reasons
        return "reject", {"approve": False}

    raise ValueError(f"unknown kind {kind}")


# ---------------------------------------------------------------- run
def run(org, task, log=None, run_tag=""):
    """Run `org` on `task`. Returns a result dict with hidden-test score."""
    log = log or EventLog()
    name = f"{task['name']}{run_tag}"
    state = {"task": task, "code": task["starter"], "notes": [], "cost": 0.0, "feedback": ""}
    stages = org["stages"]
    ids = [s["id"] for s in stages]
    i, rounds, steps, outcome = 0, 0, 0, "shipped"
    seen_code = set()  # loop detection: an implementer re-submitting old work
    log.emit(org=org["name"], task=name, type="start")

    def trip_breaker(role, why):
        state["breaker"] = why
        log.emit(org=org["name"], task=name, type="breaker", role=role, rounds=rounds,
                 action=org["on_breaker"], why=why)
        if org["on_breaker"] == "escalate":
            log.emit(org=org["name"], task=name, type="page_human", role=role, why=why,
                     last_feedback=state["feedback"][:300])
            return "escalated"
        return "shipped"

    while i < len(stages):
        steps += 1
        if steps > MAX_STEPS:
            outcome = trip_breaker(stages[i]["id"], "step limit")
            break
        stage = stages[i]
        log.emit(org=org["name"], task=name, type="stage_start", role=stage["id"], kind=stage["kind"])
        try:
            result, info = _run_stage(stage, state, org, log, name)
        except llm.BudgetExceeded:
            outcome = "budget"
            break
        log.emit(org=org["name"], task=name, type="stage_end", role=stage["id"], result=result, **info)

        if stage["kind"] == "implement":
            key = state["code"].strip()
            if rounds > 0 and key in seen_code:
                log.emit(org=org["name"], task=name, type="loop_detected", role=stage["id"], rounds=rounds)
                state["notes"].append(f"[{stage['id']}] loop detected: resubmitted earlier work")
                outcome = trip_breaker(stage["id"], "loop detected")
                break
            seen_code.add(key)

        if result == "next":
            if i + 1 < len(stages):
                log.emit(org=org["name"], task=name, type="handoff", **{"from": stage["id"]}, to=stages[i + 1]["id"])
            i += 1
            continue

        # Work sent back: reject (review) or fail (verify).
        rounds += 1
        target = stage.get("on_reject") if result == "reject" else stage.get("on_fail")
        if rounds >= org["max_rounds"]:
            outcome = trip_breaker(stage["id"], f"{rounds} send-backs")
            break
        target = target or next(s["id"] for s in stages if s["kind"] == "implement")
        log.emit(org=org["name"], task=name, type=result, **{"from": stage["id"]}, to=target,
                 reason=state["feedback"][:200])
        i = ids.index(target)

    hidden = sandbox.run_tests(state["code"], task["hidden"])
    score = hidden["passed"] / hidden["total"] if hidden["total"] else 0.0
    res = {"org": org["name"], "task": task["name"], "score": round(score, 3),
           "passed": hidden["passed"], "total": hidden["total"], "outcome": outcome,
           "rounds": rounds, "cost_usd": round(state["cost"], 5), "code": state["code"],
           "notes": state["notes"], "breaker": state.get("breaker")}
    log.emit(org=org["name"], task=name, type="done", outcome=outcome, score=res["score"],
             rounds=rounds, cost_usd=res["cost_usd"])
    return res
