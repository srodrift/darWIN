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
    # fully offline: nothing is loaded from the network (namespace strings inside
    # three.js are fine, they are identifiers, not requests)
    loads = re.findall(r"""(?:src|href)\s*=\s*["']https?:|url\(\s*["']?https?:|@import|import\s*\(\s*["']https?:""", html)
    assert not loads, loads[:3]
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


def test_viewer_embeds_threejs_for_offline_3d(tmp_path):
    (tmp_path / "orgs").mkdir()
    org.dump(org.load(os.path.join(ROOT, "orgs", "startup.yaml")), str(tmp_path / "orgs" / "flat_startup.yaml"))
    html = open(viewer.build(str(tmp_path))).read()
    assert "Three.js Authors" in html and 'id="b3d"' in html
    assert html.count("<script") == html.count("</script>")  # no early script termination


def test_any_org_renders_in_2d_and_3d(tmp_path):
    """Random orgs from long mutation chains must draw every team, station and
    governance hub in both views. Runs only where Playwright + Chromium exist."""
    pw = __import__("pytest").importorskip("playwright.sync_api")
    import glob
    import random
    from darwin import evolve
    random.seed(5)
    seeds = [org.load(p) for p in sorted(glob.glob(os.path.join(ROOT, "orgs", "**", "*.yaml"), recursive=True))]
    (tmp_path / "orgs").mkdir()
    expect = {}
    for i in range(16):
        o = random.choice(seeds)
        for _ in range(random.randint(1, 10)):
            c, _ = evolve.random_mutation(o)
            o = c or o
        o["name"] = f"r{i:02d}"
        org.dump(o, str(tmp_path / "orgs" / f"{o['name']}.yaml"))
        multi = len(o["teams"]) > 1
        expect[o["name"]] = (sum(len(t["stages"]) for t in o["teams"]), len(o["teams"]),
                             multi and o["decide"]["by"] != "router", multi and o["decide"]["by"] == "router")
    path = viewer.build(str(tmp_path))
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        except Exception as e:
            __import__("pytest").skip(f"no Chromium: {e}")
        pg = b.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto("file://" + path)
        for mode in ("2d", "3d"):
            if mode == "3d":
                pg.click("#b3d")
            for name, (stations, teams, gov, rtr) in expect.items():
                r = pg.evaluate("n => { selectOrg(n); return [document.querySelectorAll('#orgmap .snode').length,"
                                " layout.teams.length, !!layout.gov, !!layout.rtr,"
                                " V3.on ? Object.keys(V3.stations).length : null] }", name)
                assert r[:4] == [stations, teams, gov, rtr], (mode, name, r)
                if mode == "3d" and pg.evaluate("V3.ok"):
                    assert r[4] == stations, (name, r)
        b.close()
    assert not errors, errors
