"""Nemotron on Crusoe Managed Inference (OpenAI-compatible), with a cost
ledger, a hard budget cap, retries, and an offline mock mode.

Env (or put them in the repo's gitignored .env file):
  CRUSOE_API_KEY        your Crusoe key (never commit it)
  DARWIN_MOCK=1         run offline with a fake model (for plumbing tests)
  DARWIN_BUDGET         max USD this run may spend (default 5.00)
  DARWIN_TOTAL_BUDGET   max USD all runs together may spend (default 20.00),
                        tracked in runs/.spend.json

Costs are estimated locally from token counts and the price table below;
the Crusoe console is the source of truth for what you were billed.
"""
import json
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


class FatalAPIError(RuntimeError):
    """Bad key, unknown model, rejected request: retrying cannot help, so the
    whole run stops with a clear message instead of scoring every org 0."""


_NO_TEMPLATE_KWARGS = set()
# Multi-team orgs fan out (teams x clones x council voters x parallel tasks);
# cap simultaneous requests so we stay under Crusoe's per-minute limits.
_SLOTS = threading.BoundedSemaphore(int(os.environ.get("DARWIN_MAX_CONCURRENCY", "12")))


_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEND_FILE = os.environ.get("DARWIN_SPEND_FILE", os.path.join(_REPO, "runs", ".spend.json"))


def read_lifetime(path=None):
    path = path or SPEND_FILE
    try:
        with open(path) as f:
            return float(json.load(f).get("total_usd", 0.0))
    except (OSError, ValueError):
        return 0.0


class Ledger:
    """Thread-safe running total of tokens and dollars, with two caps:
    `budget` for this process and `total_budget` for all runs ever, kept in
    runs/.spend.json so separate runs can't add up past your credits."""

    def __init__(self, budget_usd, total_budget_usd=None, persist=False, path=None):
        self.budget = budget_usd
        self.total_budget = total_budget_usd
        self.persist = persist
        self.path = path or SPEND_FILE
        self.spent = 0.0
        self.tokens_in = 0
        self.tokens_out = 0
        self.calls = 0
        self._flushed = 0.0
        self._lifetime_seen = read_lifetime(self.path) if persist else 0.0
        self._lock = threading.Lock()

    def add(self, model, tin, tout):
        pin, pout = PRICES.get(model, DEFAULT_PRICE)
        cost = (tin * pin + tout * pout) / 1e6
        with self._lock:
            self.spent += cost
            self.tokens_in += tin
            self.tokens_out += tout
            self.calls += 1
            due = self.persist and (self.calls % 10 == 0 or self.spent - self._flushed > 0.05)
        if due:
            self.flush()
        return cost

    def lifetime(self):
        return self._lifetime_seen + (self.spent - self._flushed)

    def flush(self):
        """Add this process's unsaved spend to the lifetime file (locked, atomic)."""
        if not self.persist:
            return
        with self._lock:
            delta = self.spent - self._flushed
            if delta <= 0:
                return
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            lock_path = self.path + ".lock"
            with open(lock_path, "a") as lf:
                try:
                    import fcntl
                    fcntl.flock(lf, fcntl.LOCK_EX)
                except (ImportError, OSError):
                    pass  # no file locking on this platform; single-run use is still safe
                total = read_lifetime(self.path) + delta
                tmp = self.path + ".tmp"
                with open(tmp, "w") as f:
                    json.dump({"total_usd": round(total, 6),
                               "updated": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
                os.replace(tmp, self.path)
            self._flushed = self.spent
            self._lifetime_seen = total

    def check(self):
        if self.spent >= self.budget:
            raise BudgetExceeded(f"run budget ${self.budget:.2f} reached (spent ${self.spent:.4f})")
        if self.total_budget is not None and self.lifetime() >= self.total_budget:
            self.flush()
            raise BudgetExceeded(f"lifetime budget ${self.total_budget:.2f} reached "
                                 f"(all runs: ${self.lifetime():.4f}); raise DARWIN_TOTAL_BUDGET "
                                 f"or check your Crusoe console")


MOCK = os.environ.get("DARWIN_MOCK") == "1"
LEDGER = Ledger(float(os.environ.get("DARWIN_BUDGET", "5.00")),
                total_budget_usd=float(os.environ.get("DARWIN_TOTAL_BUDGET", "20.00")),
                persist=not MOCK)  # mock spend is fake and never counts

import atexit  # noqa: E402

atexit.register(LEDGER.flush)

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        key = os.environ.get("CRUSOE_API_KEY")
        if not key:
            raise FatalAPIError("No CRUSOE_API_KEY. Put `CRUSOE_API_KEY=...` in the repo's .env "
                                "file (it is gitignored), or set DARWIN_MOCK=1 to run offline.")
        _client = OpenAI(base_url=BASE_URL, api_key=key, timeout=120)
    return _client


def chat(messages, model=None, max_tokens=2048, temperature=0.6):
    """Return (text, cost_usd). Raises BudgetExceeded when over budget."""
    model = model or WORKER_MODEL
    LEDGER.check()
    if MOCK:
        return _mock_reply(messages), LEDGER.add(model, 400, 200)

    import openai
    client = _get_client()
    last_err = None
    use_kwargs = model not in _NO_TEMPLATE_KWARGS
    for attempt in range(6):
        try:
            extra = {"chat_template_kwargs": {"enable_thinking": False,
                                              "force_nonempty_content": True}} if use_kwargs else None
            with _SLOTS:
                resp = client.chat.completions.create(
                    model=model, messages=messages, max_tokens=max_tokens,
                    temperature=temperature, top_p=0.95, extra_body=extra,
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
        except (openai.AuthenticationError, openai.PermissionDeniedError) as e:
            raise FatalAPIError(f"Crusoe rejected the API key: {e}") from e
        except openai.NotFoundError as e:
            raise FatalAPIError(f"Model '{model}' not found on Crusoe. Run `python run.py check` "
                                f"and set DARWIN_WORKER_MODEL / DARWIN_META_MODEL. ({e})") from e
        except openai.BadRequestError as e:
            # Some deployments reject chat_template_kwargs: drop it once, remember, retry.
            if use_kwargs:
                use_kwargs = False
                _NO_TEMPLATE_KWARGS.add(model)
                continue
            raise FatalAPIError(f"Crusoe rejected the request for {model}: {e}") from e
        except Exception as e:  # 429 / 5xx / timeouts: jittered backoff
            last_err = e
            time.sleep(min(30, 2 ** attempt) + random.random())
    raise RuntimeError(f"Crusoe call failed after retries: {last_err}")


# ---------------------------------------------------------------- mock
# The mock exists to exercise every code path offline. Its "quality" loosely
# depends on structure (tests and feedback help) so the gate and lineage have
# something to do, but mock scores are NOT results and are labeled as such.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mock_reference(func):
    import glob
    for path in glob.glob(os.path.join(_ROOT, "reference", "*", "solution.py")):
        src = open(path).read()
        if f"def {func}(" in src:
            return src
    return None


def _mock_reply(messages):
    sys_prompt = messages[0]["content"].lower() if messages else ""
    user = messages[-1]["content"] if messages else ""
    fn = re.search(r"def (\w+)\(", user)
    func = fn.group(1) if fn else "f"
    if "verdict" in sys_prompt:
        blocks = re.findall(r"```python\n(.*?)```", user, re.S)
        unchanged = len(blocks) >= 2 and blocks[0].strip() == blocks[-1].strip()
        if unchanged or random.random() < 0.25:
            return "VERDICT: REJECT\n- Edge cases (empty input, invalid input) are not handled."
        return "VERDICT: APPROVE\nLooks complete."
    if "select" in sys_prompt and "candidate" in sys_prompt:
        n = len(re.findall(r"CANDIDATE \d+", user)) or 1
        return f"CHOICE: {random.randint(1, n)}\nMost robust."
    if "as pytest tests" in sys_prompt:
        return (f"```python\nfrom solution import {func}\n\n"
                f"def test_exists():\n    assert callable({func})\n```")
    if "redesign" in sys_prompt:
        op = random.choice(["add_blind_review", "set_parallel", "toggle_shared_memory", "add_review"])
        return json.dumps({"op": op, "n": 3, "reason": "mock meta-agent"})
    if "route an incoming issue" in sys_prompt:
        names = re.findall(r"^- ([\w-]+):", user, re.M) or ["team"]
        return f"TEAM: {random.choice(names)}\nBest fit."
    if "set direction" in sys_prompt:
        return "- Handle empty and invalid input.\n- Do not mutate arguments."
    # implement: better odds with a definition of done and with reviewer feedback
    p = 0.3 + (0.25 if "DEFINITION OF DONE" in user else 0) + (0.25 if "SENT BACK" in user else 0)
    ref = _mock_reference(func)
    if ref and random.random() < p:
        return f"Here is the fix.\n```python\n{ref}```"
    starter = re.search(r"CURRENT MODULE:\n```python\n(.*?)```", user, re.S)
    body = starter.group(1) if starter else f"def {func}(*a, **k):\n    return None\n"
    return f"```python\n{body}```"
