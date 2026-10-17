def _parse(v):
    v = v.split("+", 1)[0]
    core, _, pre = v.partition("-")
    major, minor, patch = (int(x) for x in core.split("."))
    return (major, minor, patch), (pre.split(".") if pre else [])

def _cmp_pre(a, b):
    if not a and not b: return 0
    if not a: return 1
    if not b: return -1
    for x, y in zip(a, b):
        if x == y: continue
        xd, yd = x.isdigit(), y.isdigit()
        if xd and yd: return (int(x) > int(y)) - (int(x) < int(y))
        if xd: return -1
        if yd: return 1
        return (x > y) - (x < y)
    return (len(a) > len(b)) - (len(a) < len(b))

def compare_versions(a, b):
    (ca, pa), (cb, pb) = _parse(a), _parse(b)
    if ca != cb:
        return (ca > cb) - (ca < cb)
    return _cmp_pre(pa, pb)
