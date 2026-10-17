import glob
import json
import os

import pytest

from darwin import engine, llm, org

ROOT = engine.ROOT
SEEDS = [org.load(p) for p in sorted(glob.glob(os.path.join(ROOT, "orgs", "*.yaml")))]
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
