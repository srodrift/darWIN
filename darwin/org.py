"""An organization is a YAML file. Only STRUCTURE lives here; the prompts for
each kind of work are frozen in prompts/ and shared by every org, so any
difference in score comes from how the team is organized.

Stage kinds:
  spec       writes the team's definition of done as pytest tests
  plan       writes direction for implementers (a PI, a design lead)
  implement  writes code; `parallel: N` runs N independent attempts
  select     picks one of several candidates ("tests" = by team tests, "judge" = LLM)
  review     LLM verdict; `can_veto` sends work back to `on_reject`;
             `blind` reviewer sees tests and results but never the code
  verify     runs the team's own tests (no LLM); failure goes to `on_fail`

Org-level:
  shared_memory  every role sees every finding so far (vs only its handoff)
  max_rounds     send-backs allowed before the circuit breaker trips
  on_breaker     "escalate" (stop and page a human) or "ship" (ship best so far)
"""
import copy

import yaml

KINDS = {"spec", "plan", "implement", "select", "review", "verify"}


def load(path):
    with open(path) as f:
        return normalize(yaml.safe_load(f))


def dump(org, path):
    with open(path, "w") as f:
        yaml.safe_dump(org, f, sort_keys=False)


def normalize(org):
    org = copy.deepcopy(org)
    org.setdefault("description", "")
    org.setdefault("shared_memory", False)
    org.setdefault("max_rounds", 3)
    org.setdefault("on_breaker", "escalate")
    for s in org["stages"]:
        s.setdefault("search", False)
        if s["kind"] == "implement":
            s.setdefault("parallel", 1)
        if s["kind"] == "review":
            s.setdefault("blind", False)
            s.setdefault("can_veto", True)
        if s["kind"] == "select":
            s.setdefault("by", "tests")
    validate(org)
    return org


def validate(org):
    ids = [s["id"] for s in org["stages"]]
    assert len(ids) == len(set(ids)), f"duplicate stage ids in {org['name']}"
    assert any(s["kind"] == "implement" for s in org["stages"]), "org needs an implement stage"
    for s in org["stages"]:
        assert s["kind"] in KINDS, f"unknown kind {s['kind']}"
        for key in ("on_reject", "on_fail"):
            if key in s:
                assert s[key] in ids, f"{s['id']}.{key} -> unknown stage {s[key]}"
                assert ids.index(s[key]) < ids.index(s["id"]), f"{s['id']}.{key} must point backwards"
    return True


def summary(org):
    """One-line description of the structure, for logs and the UI."""
    parts = []
    for s in org["stages"]:
        tag = s["id"]
        if s.get("parallel", 1) > 1:
            tag += f"×{s['parallel']}"
        if s.get("blind"):
            tag += "(blind)"
        if s.get("search"):
            tag += "+search"
        parts.append(tag)
    extras = []
    if org["shared_memory"]:
        extras.append("shared-memory")
    extras.append(f"max{org['max_rounds']}→{org['on_breaker']}")
    return " → ".join(parts) + "  [" + ", ".join(extras) + "]"
