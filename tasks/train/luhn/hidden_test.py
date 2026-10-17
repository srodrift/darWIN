from solution import luhn_valid
def test_valid(): assert luhn_valid("4539578763621486")
def test_invalid(): assert not luhn_valid("4539578763621487")
def test_spaces(): assert luhn_valid("4539 5787 6362 1486")
def test_dashes(): assert luhn_valid("4539-5787-6362-1486")
def test_amex_length(): assert luhn_valid("378282246310005")
def test_letters(): assert not luhn_valid("4539a78763621486")
def test_short(): assert not luhn_valid("0")
def test_none(): assert not luhn_valid(None)
