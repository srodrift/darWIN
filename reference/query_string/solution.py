from urllib.parse import unquote_plus
def parse_qs(qs):
    out = {}
    if not qs:
        return out
    qs = qs.lstrip("?")
    for part in qs.split("&"):
        if not part:
            continue
        k, _, v = part.partition("=")
        k, v = unquote_plus(k), unquote_plus(v)
        if k in out:
            if isinstance(out[k], list):
                out[k].append(v)
            else:
                out[k] = [out[k], v]
        else:
            out[k] = v
    return out
