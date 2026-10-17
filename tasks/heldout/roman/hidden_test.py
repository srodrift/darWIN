import pytest
from solution import to_roman
def test_small(): assert to_roman(3) == "III"
def test_four(): assert to_roman(4) == "IV"
def test_nine(): assert to_roman(9) == "IX"
def test_1994(): assert to_roman(1994) == "MCMXCIV"
def test_max(): assert to_roman(3999) == "MMMCMXCIX"
def test_zero():
    with pytest.raises(ValueError): to_roman(0)
def test_too_big():
    with pytest.raises(ValueError): to_roman(4000)
def test_float():
    with pytest.raises(ValueError): to_roman(2.5)
