"""Ask Darwin: answer questions about a finished run, grounded in its real data.

Used by `python run.py serve`. The browser never sees an API key: questions go to
this local server, which calls Nemotron on Crusoe (and You.com search when a key
is set and the question needs outside context).
"""
import glob
import json
import os

from darwin import llm, search

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_context(data, limit=9000):
    """Compact, factual summary of a run for the model. Only real numbers."""
    fin = data.get("final") or {}
    lines = [f"Run: {data.get('run', '')}",
             f"Champion (best training score): {fin.get('champion')}",
             f"Best human org (generation 0): {fin.get('best_human')}"]
    for c in fin.get("heldout") or []:
        lines.append(f"Final exam (held-out tasks): {c.get('org')} scored {c.get('score', 0):.2f} "
                     f"({c.get('solved')}/{c.get('runs')} solved, ${c.get('cost_usd', 0):.4f})")
    lines.append("Lineage (name | generation | parent | training score | kept by gate? | mutation and reason):")
    for n in data.get("lineage") or []:
        m = n.get("mutation") or {}
        mut = (m.get("op", "") + (" n=" + str(m["n"]) if m.get("n") else "")
               + (" on " + m["team"] if m.get("team") else "") + (": " + m["reason"] if m.get("reason") else ""))
        lines.append(f"- {n['name']} | gen {n['gen']} | {n.get('parent') or '-'} | {n.get('score', 0):.2f} | "
                     f"{'kept' if n.get('kept') else ('seed' if n['gen'] == 0 else 'discarded')} | {mut[:220]}")
    lines.append("Org structures (teams and stages):")
    for name, o in (data.get("orgs") or {}).items():
        teams = []
        for t in o.get("teams") or []:
            stages = ", ".join(f"{s.get('id')}({s.get('kind')}{' x' + str(s['parallel']) if (s.get('parallel') or 1) > 1 else ''})"
                               for s in t.get("stages") or [])
            teams.append(f"{t.get('name')}{' [isolated]' if t.get('isolated') else ''}: {stages}")
        dec = (o.get("decide") or {}).get("by", "tests")
        lines.append(f"- {name} (decided by {dec}): " + " | ".join(teams))
    text = "\n".join(lines)
    return text[:limit]


def task_issue(task):
    for split in ("train", "heldout"):
        p = os.path.join(ROOT, "tasks", split, task, "issue.md")
        if os.path.exists(p):
            with open(p) as f:
                return split, f.read()[:3000]
    return None, ""


SYSTEM = ("You are Darwin, the guide inside Darwin Inc., a system that evolves AI-agent org charts. "
          "Answer ONLY from the run data provided; if the data does not say, say so. Never invent scores. "
          "Be clear and friendly; default to 3-6 short sentences unless asked for more. "
          "Scores are the share of hidden tests passed (0 to 1).")


def ask(data, question, task=None, want_tests=False):
    """Return {answer, sources, searched, model, cost_usd}."""
    question = (question or "").strip()[:800]
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "RUN DATA\n" + run_context(data)}]
    searched, sources = False, ""
    if want_tests:
        split, issue = task_issue(task or "")
        if not issue:
            return {"answer": f"I don't know a task called '{task}'.", "searched": False, "sources": "", "cost_usd": 0}
        msgs.append({"role": "user", "content":
                     f"TASK '{task}' ({split} split) ISSUE:\n{issue}\n\n"
                     "Suggest 6 NEW test cases a grader should add for this task, especially edge cases. "
                     "Return a short intro line, then a Python pytest snippet (one assert per case, with a short "
                     "comment explaining why each matters). Do not claim these are already in the hidden tests."
                     + (f"\nUser note: {question}" if question else "")})
    else:
        if search.available() and any(w in question.lower() for w in ("industry", "real world", "research", "paper", "company", "companies", "compare", "state of the art", "who else", "news")):
            sources = search.web_search(question, count=4)
            searched = bool(sources) and not sources.startswith("(search failed")
            if searched:
                msgs.append({"role": "user", "content": "WEB RESULTS (You.com), cite as [title](url) when used:\n" + sources})
        msgs.append({"role": "user", "content": question or "Summarize this run in plain words."})
    try:
        text, cost = _chat_with_deadline(msgs, deadline=float(os.environ.get("DARWIN_ASK_TIMEOUT", "30")))
    except Exception as e:  # network down, key missing, budget hit, slow API: never leave the stage empty
        return {"answer": offline_answer(data, question, task, want_tests), "searched": False, "sources": "",
                "model": "offline answer (from run data)", "cost_usd": 0, "offline_reason": str(e)[:160]}
    return {"answer": text.strip(), "searched": searched, "sources": sources if searched else "",
            "model": llm.META_MODEL, "cost_usd": round(cost, 5)}


def _chat_with_deadline(msgs, deadline=30.0):
    import concurrent.futures as cf
    ex = cf.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(llm.chat, msgs, llm.META_MODEL, 900, 0.3)
    try:
        return fut.result(timeout=deadline)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def _pretty(name):
    """research_lab~g1c -> Research lab · round 1 · idea C (same naming as the viewer)."""
    import re
    s = str(name or "")
    m = re.match(r"^(.*?)~g(\d+)([a-z])$", s)
    base = (m.group(1) if m else s).replace("_", " ").replace("~", " · ")
    base = base[:1].upper() + base[1:]
    return f"{base} · round {m.group(2)} · idea {m.group(3).upper()}" if m else base


def offline_answer(data, question, task=None, want_tests=False):
    """Deterministic answer built only from the run's own numbers (used when the model is unreachable)."""
    lin = {n["name"]: n for n in data.get("lineage") or []}
    fin = data.get("final") or {}
    champ, human = fin.get("champion"), fin.get("best_human")
    exam = {c.get("org"): c for c in fin.get("heldout") or []}
    if want_tests:
        return (f"(Offline) The model is unreachable, so here are standard edge cases worth adding for '{task}':\n"
                "- empty input\n- a single element / shortest valid value\n- boundary values (zero, max length, off-by-one)\n"
                "- invalid types or malformed input should raise a clear error\n- very large input (performance)\n"
                "- unicode / whitespace / mixed case where text is involved")
    q = (question or "").lower()
    n = lin.get(champ) or {}
    par = lin.get(n.get("parent")) or {}
    m = n.get("mutation") or {}
    tried = sum(1 for x in lin.values() if x.get("gen", 0) > 0)
    kept = sum(1 for x in lin.values() if x.get("gen", 0) > 0 and x.get("kept"))
    ex_c, ex_h = exam.get(champ, {}).get("score"), exam.get(human, {}).get("score")
    exam_line = (f" On the final exam (tasks it never saw) it scored {ex_c:.2f} vs {ex_h:.2f} for the best human design."
                 if ex_c is not None and ex_h is not None else "")
    if "5th" in q or "grader" in q or "simple" in q:
        return (f"(Offline) Imagine teams of robot workers. We started with {sum(1 for x in lin.values() if x.get('gen', 0) == 0)} teams "
                f"organized like human companies. A coach robot kept suggesting new ways to organize them, {tried} ideas in total. "
                f"We only kept an idea if the team got better at its homework. Only {kept} idea made the cut: "
                f"{_pretty(m.get('op', 'a change'))} on {_pretty(n.get('parent'))}.{exam_line}")
    if champ and champ == human:
        return f"(Offline) Nothing beat the human design in this run, so the gate kept {_pretty(human)}. {tried} changes were tried, {kept} kept."
    return (f"(Offline) The winner, {_pretty(champ)}, came from {_pretty(n.get('parent'))} with one change: "
            f"{_pretty(m.get('op', '?'))}{(' — ' + m['reason']) if m.get('reason') else ''}. "
            f"Its practice score rose from {par.get('score', 0):.2f} to {n.get('score', 0):.2f}, so the gate kept it "
            f"(rule: keep only if the score goes up, or stays equal for under 80% of the cost). "
            f"Of {tried} changes tried, {kept} survived.{exam_line}")
