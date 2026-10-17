"""Self-evolution, demonstrated end to end, offline and free.

Run it and watch the story:
    python -m pytest tests/test_evolution_demo.py -v -s

The scripted world has one hidden rule: an engineer writes correct code only
when the team wrote a definition of done (tests) first. Evolution starts from
the one-person startup, which has no such role, and must discover it:

  gen 1  meta-agent proposes shared memory  -> no better        -> DISCARDED
         meta-agent proposes a spec writer  -> solves the tasks -> KEPT
  gen 2  meta-agent proposes 5 clones       -> same score, 5x cost -> DISCARDED
         meta-agent proposes removing spec  -> worse            -> DISCARDED
  exam   the evolved org beats the startup on tasks it never trained on.

Nothing here calls a real model; every number comes from the real engine,
sandbox, hidden tests, gate and evolution loop.
"""
import json
import os
import re
import threading

import pytest

from darwin import engine, evolution, evolve, llm, org

ROOT = engine.ROOT
COST_PER_CALL = 0.001


class ScriptedWorld:
    """Stands in for Nemotron. Workers follow the hidden rule; the meta-agent
    proposes a fixed sequence of mutations so the story is reproducible."""

    def __init__(self, proposals):
        self.proposals = list(proposals)
        self.meta_prompts = []
        self._lock = threading.Lock()

    def chat(self, messages, model=None, **kw):
        system, user = messages[0]["content"], messages[-1]["content"]
        fn = re.search(r"def (\w+)\(", user)
        func = fn.group(1) if fn else "f"
        if "redesign the ORGANIZATIONAL STRUCTURE" in system:  # the meta-agent
            with self._lock:
                self.meta_prompts.append(user)
                return json.dumps(self.proposals.pop(0)), COST_PER_CALL
        if "as pytest tests" in system:  # spec writer: a definition of done
            return (f"```python\nfrom solution import {func}\n\n"
                    f"def test_exists():\n    assert callable({func})\n```"), COST_PER_CALL
        if "VERDICT" in system:
            return "VERDICT: APPROVE", COST_PER_CALL
        if "CHOICE" in system:
            return "CHOICE: 1", COST_PER_CALL
        if "TEAM:" in system:
            return "TEAM: team", COST_PER_CALL
        # implementer: THE HIDDEN RULE
        if "DEFINITION OF DONE" in user:
            return f"```python\n{llm._mock_reference(func)}```", COST_PER_CALL
        starter = re.search(r"CURRENT MODULE:\n```python\n(.*?)```", user, re.S).group(1)
        return f"```python\n{starter}```", COST_PER_CALL


SCRIPT = [
    # generation 1, parent = flat_startup
    {"op": "toggle_shared_memory", "reason": "maybe the engineer needs more context"},
    {"op": "add_spec", "team": "team", "reason": "the engineer guesses what 'correct' means; "
                                                  "write the definition of done first"},
    # generation 2, parent = the kept mutant
    {"op": "set_parallel", "team": "team", "n": 5, "reason": "more attempts might help"},
    {"op": "remove_stage", "team": "team", "stage": "spec_writer", "reason": "save a call"},
]


@pytest.fixture
def world(monkeypatch):
    w = ScriptedWorld(SCRIPT)
    monkeypatch.setattr(llm, "chat", w.chat)
    return w


def test_self_evolution_story(world, tmp_path, capsys):
    startup = org.load(os.path.join(ROOT, "orgs", "startup.yaml"))
    lines = []

    def say(msg=""):
        lines.append(msg)
        print(msg)

    print("\n" + "=" * 72)
    print("SELF-EVOLUTION DEMO: starting from a one-person startup")
    print("hidden rule: code is only right if a definition of done was written first")
    print("=" * 72)
    result = evolution.run([startup], str(tmp_path), generations=2, parents=1, children=2,
                           seeds=1, final_seeds=1, say=say)
    lineage = {n["name"]: n for n in result["lineage"]}

    print("\nLINEAGE")
    for n in result["lineage"]:
        mut = evolve.describe(n["mutation"]) if n["mutation"] else "(seed: human org chart)"
        verdict = "seed" if n["gen"] == 0 else ("KEPT" if n["kept"] else "discarded")
        print(f"  gen {n['gen']}  {n['name']:22} {mut:34} score {n['score']:.3f} "
              f"cost ${n['cost_usd']:.3f}  {verdict}")
        print(f"         structure: {n['structure']}")

    # --- generation 1: the useless mutation is discarded, the useful one kept
    g1 = [n for n in result["lineage"] if n["gen"] == 1]
    assert [n["mutation"]["op"] for n in g1] == ["toggle_shared_memory", "add_spec"]
    assert g1[0]["kept"] is False, "shared memory did not help, so the gate must discard it"
    assert g1[1]["kept"] is True, "a definition of done solves the tasks, so it must be kept"
    assert g1[1]["score"] == 1.0 > lineage["flat_startup"]["score"]

    # --- generation 2: evolution builds on the winner, and the gate stays strict
    g2 = [n for n in result["lineage"] if n["gen"] == 2]
    assert all(n["parent"] == g1[1]["name"] for n in g2), "gen 2 must mutate the gen 1 winner"
    clones, no_spec = g2
    assert clones["score"] == 1.0 and clones["cost_usd"] > g1[1]["cost_usd"]
    assert clones["kept"] is False, "same score at higher cost must be discarded"
    assert no_spec["score"] < 1.0 and no_spec["kept"] is False, "regressions must be discarded"

    # --- the meta-agent reasons from evidence: it saw the parent's failures and history
    assert "WHERE IT FAILED" in world.meta_prompts[0]
    assert "toggle_shared_memory" in world.meta_prompts[2], "gen 2 prompt must include gen 1 history"

    # --- held-out exam: the evolved org wins on tasks evolution never saw
    final = {c["org"]: c for c in result["final"]}
    champ = result["champion"]["name"]
    assert champ == g1[1]["name"]
    assert final[champ]["score"] == 1.0 > final["flat_startup"]["score"]
    assert any(s["kind"] == "spec" for s in result["champion"]["teams"][0]["stages"])

    # --- artifacts a judge (or the 3D replay) can inspect
    for f in ("lineage.json", "final.json", "events.jsonl"):
        assert (tmp_path / f).exists()
    spawns = [json.loads(l) for l in open(tmp_path / "events.jsonl") if '"spawn"' in l]
    assert [s["kept"] for s in spawns] == [False, True, False, False]

    print(f"\nRESULT: evolution discovered that '{evolve.describe(g1[1]['mutation'])}' fixes the org.")
    print(f"held-out: startup {final['flat_startup']['score']:.3f} -> evolved {final[champ]['score']:.3f}")


def test_gate_rules():
    base = {"score": 0.5, "cost_usd": 1.0, "errors": 0}
    assert evolution.gate({**base, "score": 0.6}, base)                     # better score
    assert not evolution.gate({**base, "score": 0.4}, base)                 # worse score
    assert not evolution.gate(dict(base), base)                             # same, same cost
    assert evolution.gate({**base, "cost_usd": 0.5}, base)                  # same score, much cheaper
    assert not evolution.gate({**base, "cost_usd": 0.9}, base)              # only slightly cheaper
    assert not evolution.gate({**base, "score": 0.9, "errors": 1}, base)    # tainted by API errors


def test_random_evolution_never_breaks(monkeypatch, tmp_path):
    """Many random mutations across all seed orgs: every mutant must still run."""
    import random
    random.seed(11)
    monkeypatch.setattr(llm, "chat", ScriptedWorld([]).chat)
    seeds = [org.load(p) for p in sorted(
        __import__("glob").glob(os.path.join(ROOT, "orgs", "*.yaml")))]
    result = evolution.run(seeds, str(tmp_path), generations=2, parents=3, children=2,
                           final_seeds=1, random_mutations=True, say=lambda *a: None)
    assert len([n for n in result["lineage"] if n["gen"] > 0]) == 12
    assert all(n["errors"] == 0 for n in result["lineage"])
    assert result["final"]
