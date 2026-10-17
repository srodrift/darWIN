import glob
import os
import random

import pytest

from darwin import engine, evolve, llm, org

SEEDS = [org.load(p) for p in sorted(glob.glob(os.path.join(engine.ROOT, "orgs", "**", "*.yaml"), recursive=True))]


@pytest.mark.parametrize("seed", SEEDS, ids=lambda o: o["name"])
@pytest.mark.parametrize("op", list(evolve.OPS))
def test_every_mutation_is_valid_or_skipped(seed, op):
    for team in [t["name"] for t in seed["teams"]] + [None]:
        stages = next((t["stages"] for t in seed["teams"] if t["name"] == team), seed["teams"][0]["stages"])
        for st in [s["id"] for s in stages] + [None]:
            for n in (None, 1, 3, 5):
                for by in (None, "tests", "leader", "council"):
                    child = evolve.apply(seed, op, team=team, stage=st, n=n, by=by)
                    if child is not None:
                        assert org.validate(child)
                        assert child != seed


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
    assert any(s["kind"] == "select" for s in five["teams"][0]["stages"])
    one = evolve.apply(five, "set_parallel", n=1)
    assert not any(s["kind"] == "select" for s in one["teams"][0]["stages"])


def test_meta_agent_garbage_falls_back(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: ("I refuse to output JSON", 0.0))
    card = {"score": 0.5, "solved": 1, "runs": 2, "cost_usd": 0.0, "escalations": 0, "failures": []}
    child, mut = evolve.meta_mutation(SEEDS[0], card, [])
    assert child is not None and mut["source"] == "random"


def test_meta_agent_valid_proposal(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (
        'Sure: {"op": "set_parallel", "n": 5, "reason": "clones are cheap"}', 0.0))
    card = {"score": 0.5, "solved": 1, "runs": 2, "cost_usd": 0.0, "escalations": 0, "failures": []}
    startup = org.load(os.path.join(engine.ROOT, "orgs", "startup.yaml"))
    child, mut = evolve.meta_mutation(startup, card, [])
    assert mut["source"] == "meta-agent"
    assert any(s.get("parallel") == 5 for s in child["teams"][0]["stages"])


def _startup():
    return org.load(os.path.join(engine.ROOT, "orgs", "startup.yaml"))


def test_org_shape_mutations():
    o = _startup()
    sk = evolve.apply(o, "add_skunkworks")
    assert len(sk["teams"]) == 2 and sk["teams"][1]["isolated"]
    fork = evolve.apply(sk, "fork_team", team="team")
    assert len(fork["teams"]) == 3 and fork["teams"][2]["name"].startswith("team_fork")
    gone = evolve.apply(fork, "remove_team", team="skunkworks")
    assert [t["name"] for t in gone["teams"]] == ["team", fork["teams"][2]["name"]]
    assert evolve.apply(o, "remove_team", team="team") is None  # never remove the last team
    council = evolve.apply(sk, "set_governance", by="council", n=5)
    assert council["decide"] == {"by": "council", "voters": 5}
    connected = evolve.apply(sk, "toggle_isolated", team="skunkworks")
    assert connected["teams"][1]["isolated"] is False


def test_team_cap():
    o = _startup()
    for _ in range(evolve.MAX_TEAMS - 1):
        o = evolve.apply(o, "add_skunkworks")
    assert len(o["teams"]) == evolve.MAX_TEAMS
    assert evolve.apply(o, "add_skunkworks") is None


def test_panel_mutation():
    h = org.load(os.path.join(engine.ROOT, "orgs", "hospital.yaml"))
    p = evolve.apply(h, "set_panel", stage="attending", n=3, rule="unanimous")
    att = next(s for s in p["teams"][0]["stages"] if s["id"] == "attending")
    assert att["voters"] == 3 and att["rule"] == "unanimous"


def test_describe():
    assert evolve.describe({"op": "set_governance", "by": "council", "n": 3}) == "set_governance by=council n=3"


def test_governance_can_become_router():
    o = evolve.apply(_startup(), "add_skunkworks")
    r = evolve.apply(o, "set_governance", by="router")
    assert r["decide"]["by"] == "router" and "router assigns one team" in org.summary(r)
