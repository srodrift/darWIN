"""The benchmark itself must be sound: references pass, starters fail."""
import glob
import os

import pytest

from darwin import engine, sandbox

ROOT = engine.ROOT
TASK_DIRS = sorted(glob.glob(os.path.join(ROOT, "tasks", "*", "*")))


def test_splits_exist():
    assert len(glob.glob(os.path.join(ROOT, "tasks", "train", "*"))) >= 4
    assert len(glob.glob(os.path.join(ROOT, "tasks", "heldout", "*"))) >= 3


@pytest.mark.parametrize("d", TASK_DIRS, ids=os.path.basename)
def test_reference_passes_and_starter_fails(d):
    t = engine.load_task(d)
    ref = open(os.path.join(ROOT, "reference", t["name"], "solution.py")).read()
    r = sandbox.run_tests(ref, t["hidden"])
    assert r["total"] > 0 and r["passed"] == r["total"], r["output"]
    s = sandbox.run_tests(t["starter"], t["hidden"])
    assert s["passed"] < s["total"]
    assert f"def {t['func']}(" in ref
