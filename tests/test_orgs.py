import glob
import os

import pytest

from darwin import engine, org


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(engine.ROOT, "orgs", "**", "*.yaml"), recursive=True)))
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


def test_single_team_shorthand_becomes_teams():
    o = org.normalize({"name": "x", "stages": [{"id": "a", "kind": "implement"}]})
    assert [t["name"] for t in o["teams"]] == ["team"] and o["decide"]["by"] == "tests"


def test_duplicate_team_names_rejected():
    with pytest.raises(AssertionError):
        org.normalize({"name": "x", "teams": [
            {"name": "a", "stages": [{"id": "i", "kind": "implement"}]},
            {"name": "a", "stages": [{"id": "i", "kind": "implement"}]}]})


def test_bad_governance_rejected():
    with pytest.raises(AssertionError):
        org.normalize({"name": "x", "decide": {"by": "dictator"},
                       "stages": [{"id": "i", "kind": "implement"}]})


def test_same_stage_id_allowed_in_different_teams():
    o = org.normalize({"name": "x", "teams": [
        {"name": "a", "stages": [{"id": "builder", "kind": "implement"}]},
        {"name": "b", "stages": [{"id": "builder", "kind": "implement"}]}]})
    assert "a: builder | b: builder" in org.summary(o)
