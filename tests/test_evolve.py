import glob
import os
import random

import pytest

from darwin import engine, evolve, llm, org

SEEDS = [org.load(p) for p in sorted(glob.glob(os.path.join(engine.ROOT, "orgs", "*.yaml")))]


@pytest.mark.parametrize("seed", SEEDS, ids=lambda o: o["name"])
@pytest.mark.parametrize("op", list(evolve.OPS))
def test_every_mutation_is_valid_or_skipped(seed, op):
    for st in [s["id"] for s in seed["stages"]] + [None]:
        for n in (None, 1, 3, 5):
            child = evolve.apply(seed, op, stage=st, n=n)
            if child is not None:
                assert org.validate(child)
                assert child is not seed


def test_random_mutation_chains_stay_valid():
    random.seed(7)
    for seed in SEEDS:
        o = seed
        for _ in range(40):
            child, mut = evolve.random_mutation(o)
            if child:
                org.validate(child)
                o = child


def test_parallel_adds_and_removes_selector():
    o = org.load(os.path.join(engine.ROOT, "orgs", "startup.yaml"))
    five = evolve.apply(o, "set_parallel", n=5)
    assert any(s["kind"] == "select" for s in five["stages"])
    one = evolve.apply(five, "set_parallel", n=1)
    assert not any(s["kind"] == "select" for s in one["stages"])


def test_meta_agent_garbage_falls_back(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: ("I refuse to output JSON", 0.0))
    card = {"score": 0.5, "solved": 1, "runs": 2, "cost_usd": 0.0, "escalations": 0, "failures": []}
    child, mut = evolve.meta_mutation(SEEDS[0], card, [])
    assert child is not None and mut["by"] == "random"


def test_meta_agent_valid_proposal(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (
        'Sure: {"op": "set_parallel", "n": 5, "reason": "clones are cheap"}', 0.0))
    card = {"score": 0.5, "solved": 1, "runs": 2, "cost_usd": 0.0, "escalations": 0, "failures": []}
    startup = org.load(os.path.join(engine.ROOT, "orgs", "startup.yaml"))
    child, mut = evolve.meta_mutation(startup, card, [])
    assert mut["by"] == "meta-agent"
    assert any(s.get("parallel") == 5 for s in child["stages"])
