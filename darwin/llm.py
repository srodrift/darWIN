"""Nemotron on Crusoe Managed Inference (OpenAI-compatible), with a cost
ledger, a hard budget cap, retries, and an offline mock mode.

Env:
  CRUSOE_API_KEY     your Crusoe key (never commit it)
  DARWIN_MOCK=1    run offline with a fake model (for plumbing tests)
  DARWIN_BUDGET    max USD this process may spend (default 5.00)
"""
import os
import random
import re
import threading
import time

BASE_URL = "https://api.inference.crusoecloud.com/v1"

# Confirm exact IDs with: GET /v1/models
WORKER_MODEL = os.environ.get("DARWIN_WORKER_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
META_MODEL = os.environ.get("DARWIN_META_MODEL", "nvidia/Nemotron-3-Super-120B-A12B")

# USD per 1M tokens (input, output), from Crusoe's hackathon guide. Verify in console.
PRICES = {
    "nvidia/nemotron-3.5-lightning-30b-a3b": (0.05, 0.20),
    "nvidia/Nemotron-3-Nano-30B-A3B": (0.05, 0.20),
    "nvidia/Nemotron-3-Super-120B-A12B": (0.30, 2.40),
}
DEFAULT_PRICE = (0.30, 2.40)


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    """Thread-safe running total of tokens and dollars."""

    def __init__(self, budget_usd: float):
        self.budget = budget_usd
        self.spent = 0.0
        self.tokens_in = 0
        self.tokens_out = 0
        self.calls = 0
        self._lock = threading.Lock()

    def add(self, model, tin, tout):
        pin, pout = PRICES.get(model, DEFAULT_PRICE)
        cost = (tin * pin + tout * pout) / 1e6
        with self._lock:
            self.spent += cost
            self.tokens_in += tin
            self.tokens_out += tout
            self.calls += 1
        return cost

    def check(self):
        if self.spent >= self.budget:
            raise BudgetExceeded(f"budget ${self.budget:.2f} reached (spent ${self.spent:.2f})")


LEDGER = Ledger(float(os.environ.get("DARWIN_BUDGET", "5.00")))
MOCK = os.environ.get("DARWIN_MOCK") == "1"

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        key = os.environ.get("CRUSOE_API_KEY")
        if not key:
            raise RuntimeError("Set CRUSOE_API_KEY, or DARWIN_MOCK=1 to run offline.")
        _client = OpenAI(base_url=BASE_URL, api_key=key, timeout=120)
    return _client


def chat(messages, model=None, max_tokens=2048, temperature=0.6):
    """Return (text, cost_usd). Raises BudgetExceeded when over budget."""
    model = model or WORKER_MODEL
    LEDGER.check()
    if MOCK:
        return _mock_reply(messages), LEDGER.add(model, 400, 200)

    client = _get_client()
    last_err = None
    for attempt in range(5):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.95,
                extra_body={"chat_template_kwargs": {"enable_thinking": False,
                                                     "force_nonempty_content": True}},
            )
            msg = resp.choices[0].message
            text = msg.content or ""
            if not text:
                d = msg.model_dump()
                text = d.get("reasoning_content") or d.get("reasoning") or ""
            u = resp.usage
            cost = LEDGER.add(model, getattr(u, "prompt_tokens", 0) or 0,
                              getattr(u, "completion_tokens", 0) or 0)
            return text, cost
        except Exception as e:  # 429/503/timeouts: jittered backoff
            last_err = e
            time.sleep(min(30, 2 ** attempt) + random.random())
    raise RuntimeError(f"Crusoe call failed after retries: {last_err}")


# ---------------------------------------------------------------- mock
def _mock_reply(messages):
    """Deterministic-ish fake model so the whole pipeline runs offline."""
    sys_prompt = messages[0]["content"].lower() if messages else ""
    user = messages[-1]["content"] if messages else ""
    if "verdict" in sys_prompt:
        return "VERDICT: APPROVE\nLooks fine." if random.random() < 0.7 else \
               "VERDICT: REJECT\n- Missing edge case handling for empty input."
    if "select" in sys_prompt and "candidate" in sys_prompt:
        return "CHOICE: 1"
    if "write pytest" in sys_prompt or "definition of done" in sys_prompt:
        fn = re.search(r"def (\w+)\(", user)
        name = fn.group(1) if fn else "f"
        return f"```python\nfrom solution import {name}\n\ndef test_exists():\n    assert callable({name})\n```"
    if "search query" in sys_prompt:
        return "QUERY: python edge cases"
    if "mutation" in sys_prompt:
        return '{"op": "add_review", "reason": "mock"}'
    code = re.search(r"```python\n(.*?)```", user, re.S)
    body = code.group(1) if code else "def f():\n    pass\n"
    return f"PLAN: keep it simple.\n```python\n{body}```"
