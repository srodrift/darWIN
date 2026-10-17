def parse_qs(qs):
    return dict(p.split("=") for p in qs.split("&"))
