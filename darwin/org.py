"""An organization is a YAML file. Only STRUCTURE lives here; the prompts for
each kind of work are frozen in prompts/ and shared by every org, so any
difference in score comes from how the organization is shaped.

An org is one or more TEAMS plus a GOVERNANCE rule:

  teams:          independent groups that work the same problem in parallel
    isolated      the team sees nothing from other teams (a skunkworks)
    stages        the team's own pipeline (see stage kinds below)
  decide:         how the final answer is chosen between teams
    by: tests     evidence decides: candidate passing the most team tests
    by: leader    one decision-maker picks (a CEO)
    by: council   `voters` peers vote; plurality wins (an oligarchy)
    by: router    a dispatcher sends each task to ONE team (divisions that
                  split the work instead of competing); teams may carry a
                  `focus` that the dispatcher reads
  shared_memory   non-isolated roles see every finding so far
  max_rounds      send-backs allowed per team before the circuit breaker
  on_breaker      "escalate" (page a human) or "ship" (ship best so far)

A single-team org may skip `teams:` and list `stages:` at the top level.

Stage kinds:
  spec       writes the team's definition of done as pytest tests
  plan       writes direction for implementers
  implement  writes code; `parallel: N` runs N independent attempts
  select     picks one of several candidates ("tests" or "judge")
  review     verdict; `voters: N` + `rule: majority|unanimous` makes it a
             panel; `can_veto` sends work back to `on_reject`; `blind`
             reviewers see tests and results, never the code
  verify     runs the team's own tests (no LLM); failure goes to `on_fail`
"""
import copy

import yaml

KINDS = {"spec", "plan", "implement", "select", "review", "verify"}
DECIDE_BY = {"tests", "leader", "council", "router"}
RULES = {"majority", "unanimous"}


def load(path):
    with open(path) as f:
        return normalize(yaml.safe_load(f))


def dump(org, path):
    with open(path, "w") as f:
        yaml.safe_dump(org, f, sort_keys=False)


def _normalize_stage(s):
    s.setdefault("search", False)
    if s["kind"] == "implement":
        s.setdefault("parallel", 1)
    if s["kind"] == "review":
        s.setdefault("blind", False)
        s.setdefault("can_veto", True)
        s.setdefault("voters", 1)
        s.setdefault("rule", "majority")
    if s["kind"] == "select":
        s.setdefault("by", "tests")
    return s


def normalize(org):
    """Return the canonical form: always `teams` + `decide`."""
    org = copy.deepcopy(org)
    if "teams" not in org:
        assert "stages" in org, f"org {org.get('name')} needs `teams` or `stages`"
        org["teams"] = [{"name": "team", "stages": org.pop("stages")}]
    org.pop("stages", None)
    org.setdefault("description", "")
    org.setdefault("shared_memory", False)
    org.setdefault("max_rounds", 3)
    org.setdefault("on_breaker", "escalate")
    d = org.setdefault("decide", {})
    d.setdefault("by", "tests")
    d.setdefault("voters", 3 if d["by"] == "council" else 1)
    for t in org["teams"]:
        t.setdefault("isolated", False)
        t.setdefault("focus", "")
        for s in t["stages"]:
            _normalize_stage(s)
    validate(org)
    return org


def validate(org):
    assert org.get("name"), "org needs a name"
    assert org["teams"], "org needs at least one team"
    names = [t["name"] for t in org["teams"]]
    assert len(names) == len(set(names)), f"duplicate team names in {org['name']}"
    assert org["decide"]["by"] in DECIDE_BY, f"decide.by must be one of {DECIDE_BY}"
    assert 1 <= int(org["decide"]["voters"]) <= 7, "decide.voters must be 1-7"
    assert int(org["max_rounds"]) >= 1
    assert org["on_breaker"] in ("escalate", "ship")
    for t in org["teams"]:
        assert isinstance(t.get("focus", ""), str), "team focus must be text"
        st = t["stages"]
        ids = [s["id"] for s in st]
        assert len(ids) == len(set(ids)), f"duplicate stage ids in team {t['name']}"
        assert any(s["kind"] == "implement" for s in st), f"team {t['name']} needs an implement stage"
        for s in st:
            assert s["kind"] in KINDS, f"unknown kind {s['kind']}"
            if s["kind"] == "review":
                assert 1 <= int(s["voters"]) <= 7 and s["rule"] in RULES
            for key in ("on_reject", "on_fail"):
                if key in s:
                    assert s[key] in ids, f"{s['id']}.{key} -> unknown stage {s[key]}"
                    assert ids.index(s[key]) < ids.index(s["id"]), f"{s['id']}.{key} must point backwards"
    return True


def _team_summary(t):
    parts = []
    for s in t["stages"]:
        tag = s["id"]
        if s.get("parallel", 1) > 1:
            tag += f"×{s['parallel']}"
        if s["kind"] == "review" and s.get("voters", 1) > 1:
            tag += f"[panel {s['voters']} {s['rule']}]"
        if s.get("blind"):
            tag += "(blind)"
        if s.get("search"):
            tag += "+search"
        parts.append(tag)
    return " → ".join(parts)


def summary(org):
    """One-line description of the structure, for logs and the UI."""
    teams = org["teams"]
    if len(teams) == 1:
        body = _team_summary(teams[0])
    else:
        body = " | ".join(f"{t['name']}{' (isolated)' if t['isolated'] else ''}: {_team_summary(t)}"
                          for t in teams)
        d = org["decide"]
        rule = {"tests": "tests decide", "leader": "leader decides",
                "council": f"council of {d['voters']} votes",
                "router": "router assigns one team"}[d["by"]]
        body += f"  ⇒ {rule}"
    extras = []
    if org["shared_memory"]:
        extras.append("shared-memory")
    extras.append(f"max{org['max_rounds']}→{org['on_breaker']}")
    return body + "  [" + ", ".join(extras) + "]"
