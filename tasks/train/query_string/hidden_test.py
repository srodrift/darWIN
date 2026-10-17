from solution import parse_qs
def test_basic(): assert parse_qs("a=1&b=2") == {"a": "1", "b": "2"}
def test_leading_q(): assert parse_qs("?a=1") == {"a": "1"}
def test_plus_space(): assert parse_qs("q=hello+world") == {"q": "hello world"}
def test_percent(): assert parse_qs("name=J%C3%BCrgen") == {"name": "Jürgen"}
def test_repeated(): assert parse_qs("t=a&t=b") == {"t": ["a", "b"]}
def test_no_value(): assert parse_qs("flag") == {"flag": ""}
def test_empty(): assert parse_qs("") == {}
def test_equals_in_value(): assert parse_qs("x=a=b") == {"x": "a=b"}
