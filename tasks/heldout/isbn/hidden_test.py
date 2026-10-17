from solution import is_valid_isbn as v
def test_isbn10(): assert v("0306406152")
def test_isbn10_x(): assert v("080442957X")
def test_isbn10_bad(): assert not v("0306406153")
def test_isbn13(): assert v("9780306406157")
def test_isbn13_hyphens(): assert v("978-0-306-40615-7")
def test_isbn13_bad(): assert not v("9780306406158")
def test_letters(): assert not v("97803064061AB")
def test_wrong_len(): assert not v("12345")
