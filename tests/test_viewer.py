"""The viewer must build from any run, offline, with all data embedded."""
import json
import os
import re

from darwin import evolution, llm, org, viewer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _embedded(path):
    html = open(path).read()
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    return html, json.loads(m.group(1))


def test_viewer_from_evolution_run(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda m, **k: (
        "VERDICT: APPROVE" if "VERDICT" in m[0]["content"] else
        '{"op": "add_skunkworks", "reason": "try a secret team"}' if "redesign" in m[0]["content"] else
        "```python\ndef median(xs):\n    return 0\n```", 0.0))
    seeds = [org.load(os.path.join(ROOT, "orgs", f)) for f in ("startup.yaml", "council.yaml")]
    evolution.run(seeds, str(tmp_path), generations=1, parents=1, children=1, final_seeds=1,
                  say=lambda *a: None)
    html, data = _embedded(viewer.build(str(tmp_path)))
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")  # fully offline
    assert "https://" not in html
    assert {"flat_startup", "council_of_peers"} <= set(data["orgs"])
    assert data["lineage"] and data["events"] and data["final"]["heldout"]
    assert data["splits"]["median"] == "train" and data["splits"]["roman"] == "heldout"


def test_viewer_survives_truncated_log(tmp_path):
    (tmp_path / "orgs").mkdir()
    org.dump(org.load(os.path.join(ROOT, "orgs", "startup.yaml")), str(tmp_path / "orgs" / "flat_startup.yaml"))
    (tmp_path / "events.jsonl").write_text('{"org": "flat_startup", "task": "median", "type": "start", "t": 0}\n{"org": "flat_')
    _, data = _embedded(viewer.build(str(tmp_path)))
    assert len(data["events"]) == 1 and data["lineage"] == []


def test_viewer_escapes_script_breakout(tmp_path):
    (tmp_path / "orgs").mkdir()
    o = org.load(os.path.join(ROOT, "orgs", "startup.yaml"))
    o["description"] = "</script><script>alert(1)</script>"
    org.dump(o, str(tmp_path / "orgs" / "x.yaml"))
    html = open(viewer.build(str(tmp_path))).read()
    assert "</script><script>alert(1)" not in html
