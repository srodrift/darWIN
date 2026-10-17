import pytest
from solution import parse_duration
def test_seconds(): assert parse_duration("90s") == 90
def test_hours(): assert parse_duration("2h") == 7200
def test_combo(): assert parse_duration("1h30m") == 5400
def test_spaces(): assert parse_duration("1h 5m 10s") == 3910
def test_upper(): assert parse_duration("10M") == 600
def test_invalid():
    with pytest.raises(ValueError): parse_duration("abc")
def test_empty():
    with pytest.raises(ValueError): parse_duration("")
