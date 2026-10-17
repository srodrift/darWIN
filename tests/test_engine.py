import glob
import json
import os

import pytest

from darwin import engine, llm, org

ROOT = engine.ROOT
SEEDS = [org.load(p) for p in sorted(glob.glob(os.path.join(ROOT, "orgs", "**", "*.yaml"), recursive=True))]
TASK = engine.load_task(os.path.join(ROOT, "tasks", "train", "median"))
REF = open(os.path.join(ROOT, "reference", "median", "solution.py")).read()


@pytest.mark.parametrize("text,want", [
    ("```python\ndef median(x):\n    return 1\n```", "def median"),
    ("```Python\ndef median(x):\n    return 1\n```", "def median"),
    ("```py\ndef median(x):\n    return 1\n```", "def median"),
    ("```\ndef median(x):\n    return 1\n```", "def median"),
    ("Here:\n```python\ndef median(x):\n    return 1\n", "def median"),          # cut off
    ("def median(x):\n    return 1\n", "def median"),                             # unfenced
])
def test_code_block_variants(text, want):
    assert want in engine._code_block(text, must_contain="def median(")


def test_code_block_prefers_function_over_tests():
    text = ("```python\nfrom solution import median\ndef test_a():\n    assert median([1]) == 1\n"
            "def test_b():\n    assert median([1, 2]) == 1.5\n```\n"
            "```python\ndef median(x):\n    return 1\n```")
    assert "def median(" in engine._code_block(text, must_contain="def median(")


def test_code_block_none_when_empty():
    assert engine._code_block("no code here") is None


@pytest.mark.parametrize("o", SEEDS, ids=lambda o: o["name"])
def test_every_seed_org_runs(o, tmp_path):
    log = engine.EventLog(str(tmp_path / "events.jsonl"))
    r = engine.run(o, TASK, log)
    assert 0.0 <= r["score"] <= 1.0
    assert r["outcome"] in ("shipped", "escalated")
    events = [json.loads(l) for l in open(tmp_path / "events.jsonl")]
    assert events[0]["type"] == "start" and events[-1]["type"] == "done"


def _scripted(review_text, impl_code):
    def chat(messages, **kw):
        sysp = messages[0]["content"]
        if "VERDICT" in sysp:
            return review_text, 0.0
        if "pytest tests" in sysp:
            return "```python\nfrom solution import median\ndef test_a():\n    assert median([1]) == 1\n```", 0.0
        return f"```python\n{impl_code}```", 0.0
    return chat


def test_loop_detection_trips_breaker(monkeypatch, tmp_path):
    # Reviewer always rejects, implementer always resubmits the same code.
    monkeypatch.setattr(llm, "chat", _scripted("**VERDICT: REJECT**\n- nope", REF))
    hospital = next(o for o in SEEDS if o["name"] == "crusoe_general")
    log = engine.EventLog(str(tmp_path / "e.jsonl"))
    r = engine.run(hospital, TASK, log)
    types = [json.loads(l)["type"] for l in open(tmp_path / "e.jsonl")]
    assert "loop_detected" in types and "page_human" in types
    assert r["outcome"] == "escalated" and r["breaker"] == "loop detected"


def test_reviewer_approve_parsing(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "chat", _scripted("Verdict - Approve. Nothing to reject here.", REF))
    hospital = next(o for o in SEEDS if o["name"] == "crusoe_general")
    r = engine.run(hospital, TASK, engine.EventLog(str(tmp_path / "e.jsonl")))
    assert r["outcome"] == "shipped" and r["score"] == 1.0


def test_non_compiling_code_is_rejected_as_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "chat", _scripted("VERDICT: APPROVE", "def median(:\n"))
    startup = next(o for o in SEEDS if o["name"] == "flat_startup")
    r = engine.run(startup, TASK, engine.EventLog(str(tmp_path / "e.jsonl")))
    assert r["code"] == TASK["starter"]  # falls back to the unchanged module


def test_budget_stops_run(monkeypatch, tmp_path):
    monkeypatch.setattr(llm.LEDGER, "budget", 0.0)
    startup = next(o for o in SEEDS if o["name"] == "flat_startup")
    r = engine.run(startup, TASK, engine.EventLog(str(tmp_path / "e.jsonl")))
    assert r["outcome"] == "budget"


GOOD = REF
BAD = "def median(xs):\n    return xs[0]\n"


def _multi(decide, teams=2, isolated=(False, False), shared=False):
    return org.normalize({"name": "multi", "shared_memory": shared, "decide": decide, "teams": [
        {"name": f"t{i}", "isolated": isolated[i],
         "stages": [{"id": "spec", "kind": "spec"}, {"id": f"b{i}", "kind": "implement"}]}
        for i in range(teams)]})


def _by_team(code_for_call):
    """Scripted model: the Nth implement call returns code_for_call(N)."""
    counter = {"n": 0}

    def chat(messages, **kw):
        sysp, user = messages[0]["content"], messages[-1]["content"]
        if "pytest tests" in sysp:
            return ("```python\nfrom solution import median\n"
                    "def test_even():\n    assert median([1, 2, 3, 4]) == 2.5\n```"), 0.0
        if "select the best" in sysp:
            return chat.vote, 0.0
        counter["n"] += 1
        return f"```python\n{code_for_call(counter['n'])}```", 0.0
    chat.vote = "CHOICE: 1"
    return chat


def test_tests_governance_picks_better_team(monkeypatch, tmp_path):
    import threading
    lock = threading.Lock()
    seq = iter([BAD, GOOD])

    def code(_):
        with lock:
            return next(seq)
    monkeypatch.setattr(llm, "chat", _by_team(code))
    r = engine.run(_multi({"by": "tests"}), TASK, engine.EventLog(str(tmp_path / "e.jsonl")))
    assert r["score"] == 1.0
    events = [json.loads(l) for l in open(tmp_path / "e.jsonl")]
    dec = [e for e in events if e["type"] == "decision"]
    assert dec and dec[0]["by"] == "tests"
    assert any("team" in e for e in events if e["type"] == "stage_start")


def test_council_governance_counts_votes(monkeypatch, tmp_path):
    fake = _by_team(lambda n: GOOD)
    fake.vote = "After deliberation: CHOICE: 2"
    monkeypatch.setattr(llm, "chat", fake)
    o = _multi({"by": "council", "voters": 3})
    r = engine.run(o, TASK, engine.EventLog(str(tmp_path / "e.jsonl")))
    dec = [json.loads(l) for l in open(tmp_path / "e.jsonl") if '"decision"' in l][0]
    assert dec["by"] == "council" and dec["picked"] == "t1" and dec["votes"]["t1"] == 3
    assert r["picked_team"] == "t1"


def test_isolated_team_does_not_see_shared_notes(monkeypatch, tmp_path):
    seen = []

    def chat(messages, **kw):
        user = messages[-1]["content"]
        if "pytest tests" in messages[0]["content"]:
            return "```python\nfrom solution import median\ndef test_a():\n    assert median([1]) == 1\n```", 0.0
        seen.append(user)
        return f"```python\n{GOOD}```", 0.0
    monkeypatch.setattr(llm, "chat", chat)
    # Team t0 is connected, t1 is isolated. Spec notes from t0 must never reach t1.
    o = _multi({"by": "tests"}, isolated=(False, True), shared=True)
    engine.run(o, TASK, engine.EventLog(str(tmp_path / "e.jsonl")))
    assert not any("[t0/" in u for u in seen if "[t1/" in u)
    assert all("[t0/" not in u for u in seen if "TEAM NOTES" in u and "[t1/" in u)


def test_panel_unanimous_rejects_on_one_no(monkeypatch, tmp_path):
    import itertools
    import threading
    lock = threading.Lock()
    verdicts = itertools.cycle(["VERDICT: APPROVE", "VERDICT: APPROVE", "VERDICT: REJECT\n- missing case"])

    def chat(messages, **kw):
        if "VERDICT" in messages[0]["content"]:
            with lock:
                return next(verdicts), 0.0
        return f"```python\n{GOOD}```", 0.0
    monkeypatch.setattr(llm, "chat", chat)
    o = org.normalize({"name": "panel", "max_rounds": 1, "on_breaker": "ship", "stages": [
        {"id": "b", "kind": "implement"},
        {"id": "p", "kind": "review", "voters": 3, "rule": "unanimous", "on_reject": "b"}]})
    r = engine.run(o, TASK, engine.EventLog(str(tmp_path / "e.jsonl")))
    assert r["breaker"]  # 2/3 is not unanimous -> rejected -> breaker at max_rounds=1
    o["teams"][0]["stages"][1]["rule"] = "majority"
    r2 = engine.run(o, TASK, engine.EventLog(str(tmp_path / "e2.jsonl")))
    assert not r2["breaker"]  # 2/3 is a majority -> approved


def test_router_sends_task_to_one_division(monkeypatch, tmp_path):
    calls = []

    def chat(messages, **kw):
        sysp = messages[0]["content"]
        if "route an incoming issue" in sysp:
            return "TEAM: utilities_division\nmedian is everyday utility code.", 0.0
        calls.append(sysp[:30])
        if "VERDICT" in sysp:
            return "VERDICT: APPROVE", 0.0
        return f"```python\n{GOOD}```", 0.0
    monkeypatch.setattr(llm, "chat", chat)
    div = next(o for o in SEEDS if o["name"] == "divisional")
    r = engine.run(div, TASK, engine.EventLog(str(tmp_path / "e.jsonl")))
    events = [json.loads(l) for l in open(tmp_path / "e.jsonl")]
    route = [e for e in events if e["type"] == "route"]
    assert route and route[0]["to"] == "utilities_division"
    worked = {e.get("team") for e in events if e["type"] == "stage_start"}
    assert worked == {"utilities_division"}  # the other division never ran
    assert r["picked_team"] == "utilities_division" and r["score"] == 1.0


def test_router_garbage_falls_back_to_first_team(monkeypatch, tmp_path):
    def chat(messages, **kw):
        if "route an incoming issue" in messages[0]["content"]:
            return "I cannot decide.", 0.0
        if "VERDICT" in messages[0]["content"]:
            return "VERDICT: APPROVE", 0.0
        if "pytest tests" in messages[0]["content"]:
            return "```python\nfrom solution import median\ndef test_a():\n    assert median([1]) == 1\n```", 0.0
        return f"```python\n{GOOD}```", 0.0
    monkeypatch.setattr(llm, "chat", chat)
    div = next(o for o in SEEDS if o["name"] == "divisional")
    r = engine.run(div, TASK, engine.EventLog(str(tmp_path / "e.jsonl")))
    assert r["picked_team"] == div["teams"][0]["name"]


def test_search_is_never_claimed_without_a_key(monkeypatch, tmp_path):
    monkeypatch.delenv("YDC_API_KEY", raising=False)
    hospital = next(o for o in SEEDS if o["name"] == "crusoe_general")  # triage has search: true
    engine.run(hospital, TASK, engine.EventLog(str(tmp_path / "e.jsonl")))
    ev = [json.loads(l) for l in open(tmp_path / "e.jsonl") if '"search"' in l]
    assert ev and all(e["ran"] is False for e in ev)
