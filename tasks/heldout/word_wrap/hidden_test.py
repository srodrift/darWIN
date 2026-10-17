import pytest
from solution import wrap
def test_basic(): assert wrap("the quick brown fox", 10) == ["the quick", "brown fox"]
def test_no_split_words(): assert wrap("hello world", 7) == ["hello", "world"]
def test_long_word(): assert wrap("abcdefghij", 4) == ["abcd", "efgh", "ij"]
def test_whitespace(): assert wrap("  a   b  ", 5) == ["a b"]
def test_empty(): assert wrap("", 5) == []
def test_width_limit():
    for line in wrap("lorem ipsum dolor sit amet consectetur", 8):
        assert len(line) <= 8
def test_bad_width():
    with pytest.raises(ValueError): wrap("x", 0)
