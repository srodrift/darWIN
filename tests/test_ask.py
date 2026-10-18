"""Ask Darwin: grounded context and the offline fallback used on stage when the API is unreachable."""
import glob
import os

import pytest

from darwin import ask, llm, viewer


def _run():
    runs = [d for d in glob.glob("runs/*") if os.path.isfile(os.path.join(d, "final.json"))]
    if not runs:
        pytest.skip("no finished run in runs/")
    return viewer._load_run(max(runs, key=lambda d: len(glob.glob(os.path.join(d, "orgs", "*")))))


def test_context_has_real_scores():
    d = _run()
    ctx = ask.run_context(d)
    assert "Champion" in ctx and "Lineage" in ctx


def test_falls_back_offline_when_model_fails(monkeypatch):
    d = _run()
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(llm, "chat", boom)
    out = ask.ask(d, "Why did the winner win?")
    assert out["answer"].startswith("(Offline)") and out["cost_usd"] == 0
    tests = ask.ask(d, "", task="luhn", want_tests=True)
    assert "edge cases" in tests["answer"]


def test_pretty_matches_viewer_names():
    assert ask._pretty("research_lab~g1c") == "Research lab · round 1 · idea C"
    assert ask._pretty("council_of_peers") == "Council of peers"
