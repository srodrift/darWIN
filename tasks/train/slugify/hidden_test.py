from solution import slugify
def test_basic(): assert slugify("Hello World") == "hello-world"
def test_accents(): assert slugify("Café Déjà Vu") == "cafe-deja-vu"
def test_punct(): assert slugify("What's new? (2026)") == "what-s-new-2026"
def test_collapse(): assert slugify("a  --  b") == "a-b"
def test_strip(): assert slugify("  -Hi- ") == "hi"
def test_empty(): assert slugify("") == ""
def test_none(): assert slugify(None) == ""
