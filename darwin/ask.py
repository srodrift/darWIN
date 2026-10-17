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
    text, cost = llm.chat(msgs, model=llm.META_MODEL, max_tokens=900, temperature=0.3)
    return {"answer": text.strip(), "searched": searched, "sources": sources if searched else "",
            "model": llm.META_MODEL, "cost_usd": round(cost, 5)}
