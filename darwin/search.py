"""You.com web search, used by any role whose org config grants `search: true`.

Env: YDC_API_KEY. Without a key (or in mock mode) search returns "" and the
role simply works without references.
"""
import os

import requests

URL = "https://ydc-index.io/v1/search"


def available() -> bool:
    """True only when a real You.com search can happen."""
    return bool(os.environ.get("YDC_API_KEY")) and os.environ.get("DARWIN_MOCK") != "1"


def web_search(query: str, count: int = 4) -> str:
    key = os.environ.get("YDC_API_KEY")
    if not key or os.environ.get("DARWIN_MOCK") == "1":
        return ""
    try:
        r = requests.post(URL, headers={"X-API-Key": key},
                          json={"query": query, "count": count}, timeout=20)
        r.raise_for_status()
        web = (r.json().get("results") or {}).get("web") or []
    except Exception as e:  # search is best-effort, never fatal
        return f"(search failed: {e})"
    lines = []
    for item in web[:count]:
        snippets = " ".join((item.get("snippets") or [])[:2])
        lines.append(f"- {item.get('title', '')} ({item.get('url', '')}): "
                     f"{item.get('description', '')} {snippets}"[:600])
    return "\n".join(lines)
