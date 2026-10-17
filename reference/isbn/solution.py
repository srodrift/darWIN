def is_valid_isbn(s):
    if not isinstance(s, str):
        return False
    s = s.replace("-", "").replace(" ", "")
    if len(s) == 10:
        if not s[:9].isdigit() or not (s[9].isdigit() or s[9] in "Xx"):
            return False
        total = sum((10 - i) * int(ch) for i, ch in enumerate(s[:9]))
        total += 10 if s[9] in "Xx" else int(s[9])
        return total % 11 == 0
    if len(s) == 13:
        if not s.isdigit():
            return False
        total = sum(int(ch) * (1 if i % 2 == 0 else 3) for i, ch in enumerate(s))
        return total % 10 == 0
    return False
