import glob
import os

import pytest

from darwin import engine, org


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(engine.ROOT, "orgs", "*.yaml"))))
def test_seed_orgs_valid(path):
    o = org.load(path)
    assert o["name"] and org.summary(o)


def test_back_edge_must_point_backwards():
    bad = {"name": "x", "stages": [
        {"id": "a", "kind": "review", "on_reject": "b"},
        {"id": "b", "kind": "implement"}]}
    with pytest.raises(AssertionError):
        org.normalize(bad)


def test_needs_implement():
    with pytest.raises(AssertionError):
        org.normalize({"name": "x", "stages": [{"id": "a", "kind": "spec"}]})


def test_unknown_kind():
    with pytest.raises(AssertionError):
        org.normalize({"name": "x", "stages": [{"id": "a", "kind": "implement"}, {"id": "b", "kind": "dance"}]})
