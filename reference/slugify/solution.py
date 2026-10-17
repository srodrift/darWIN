import re, unicodedata
def slugify(title):
    if title is None:
        return ""
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower())
    return s.strip("-")
