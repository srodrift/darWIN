import re
def parse_duration(s):
    if not isinstance(s, str) or not s.strip():
        raise ValueError("empty duration")
    s = s.strip().lower().replace(" ", "")
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", s)
    if not m or not any(m.groups()):
        raise ValueError(f"bad duration: {s}")
    h, mi, se = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + se
