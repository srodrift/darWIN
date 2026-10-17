"""End-to-end: the real CLI, offline, including budget stop and resume."""
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args, budget="100"):
    env = {**os.environ, "DARWIN_MOCK": "1", "DARWIN_BUDGET": budget}
    p = subprocess.run([sys.executable, "run.py", *args], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    return p.stdout


def latest_run(tag):
    return sorted(glob.glob(os.path.join(ROOT, "runs", f"*_{tag}")))[-1]


def test_once_and_errors():
    out = run_cli("once", "--org", "lab", "--task", "semver")
    assert "hidden tests:" in out
    p = subprocess.run([sys.executable, "run.py", "once", "--task", "nope"], cwd=ROOT,
                       env={**os.environ, "DARWIN_MOCK": "1"}, capture_output=True, text=True)
    assert p.returncode != 0 and "Options:" in p.stderr


def test_evolve_then_resume():
    run_cli("evolve", "--generations", "1", "--children", "1", "--final-seeds", "1")
    d = latest_run("evolve")
    meta = json.load(open(os.path.join(d, "meta.json")))
    assert meta["mode"] == "mock"
    final = json.load(open(os.path.join(d, "final.json")))
    assert final["heldout"]
    lineage = json.load(open(os.path.join(d, "lineage.json")))
    names = [n["name"] for n in lineage]
    assert len(names) == len(set(names))
    out = run_cli("evolve", "--resume", d, "--generations", "1", "--children", "1", "--final-seeds", "1")
    assert "resumed" in out
    d2 = latest_run("evolve")
    lin2 = json.load(open(os.path.join(d2, "lineage.json")))
    assert max(n["gen"] for n in lin2) == 2
    assert len({n["name"] for n in lin2}) == len(lin2)


def test_tiny_budget_exits_cleanly():
    p = subprocess.run([sys.executable, "run.py", "compare"], cwd=ROOT,
                       env={**os.environ, "DARWIN_MOCK": "1", "DARWIN_BUDGET": "0.0005"},
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0 and "saved" in p.stdout


def test_compare_with_catalog_orgs():
    out = run_cli("compare", "--orgs", "orgs/catalog/*.yaml")
    for name in ("flat", "functional", "divisional", "matrix"):
        assert name in out


def test_once_finds_catalog_org():
    assert "hidden tests:" in run_cli("once", "--org", "matrix", "--task", "median")


def test_bad_orgs_glob_errors():
    p = subprocess.run([sys.executable, "run.py", "compare", "--orgs", "orgs/nope/*.yaml"], cwd=ROOT,
                       env={**os.environ, "DARWIN_MOCK": "1"}, capture_output=True, text=True)
    assert p.returncode != 0 and "no org files" in p.stderr


def test_orgs_by_name_list():
    out = run_cli("compare", "--orgs", "startup,hospital,matrix")
    for name in ("flat_startup", "crusoe_general", "matrix"):
        assert name in out
    assert "research_lab" not in out
