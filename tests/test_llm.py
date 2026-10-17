"""The live client's failure handling, using a fake Crusoe client."""
try:
    import httpx2 as httpx  # newer openai SDKs
except ImportError:
    import httpx
import openai
import pytest

from darwin import evaluate, engine, evolve, llm, org


def _err(cls, status):
    req = httpx.Request("POST", "https://api.inference.crusoecloud.com/v1/chat/completions")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


class FakeResp:
    class _U:
        prompt_tokens, completion_tokens = 1000, 500

    def __init__(self, text):
        msg = type("M", (), {"content": text, "model_dump": lambda self: {}})()
        self.choices = [type("C", (), {"message": msg})()]
        self.usage = self._U()


class FakeClient:
    def __init__(self, behaviors, model_ids=()):
        self.behaviors, self.calls = list(behaviors), []
        outer = self
        ids = [type("Mdl", (), {"id": i})() for i in model_ids]
        self.models = type("Models", (), {"list": lambda self: type("L", (), {"data": ids})()})()

        class _Comp:
            def create(self, **kw):
                outer.calls.append(kw)
                b = outer.behaviors.pop(0)
                if isinstance(b, Exception):
                    raise b
                return FakeResp(b)
        self.chat = type("Chat", (), {"completions": _Comp()})()


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(llm, "MOCK", False)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    llm._NO_TEMPLATE_KWARGS.clear()

    llm._RESOLVE_TRIED.clear()

    def install(behaviors, model_ids=()):
        fake = FakeClient(behaviors, model_ids)
        monkeypatch.setattr(llm, "_client", fake)
        return fake
    return install


def test_success_and_cost(live):
    live(["hello"])
    text, cost = llm.chat([{"role": "user", "content": "hi"}], model="nvidia/nemotron-3.5-lightning-30b-a3b")
    assert text == "hello" and cost == pytest.approx((1000 * 0.05 + 500 * 0.20) / 1e6)


def test_retries_transient_errors(live):
    fake = live([_err(openai.RateLimitError, 429), _err(openai.InternalServerError, 503), "ok"])
    assert llm.chat([{"role": "user", "content": "hi"}])[0] == "ok"
    assert len(fake.calls) == 3


def test_bad_key_is_fatal_immediately(live):
    fake = live([_err(openai.AuthenticationError, 401)])
    with pytest.raises(llm.FatalAPIError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert len(fake.calls) == 1


def test_unknown_model_is_fatal(live):
    live([_err(openai.NotFoundError, 404)])
    with pytest.raises(llm.FatalAPIError, match="not found"):
        llm.chat([{"role": "user", "content": "hi"}], model="nvidia/typo")


def test_rejected_template_kwargs_falls_back_once(live):
    fake = live([_err(openai.BadRequestError, 400), "ok", "again"])
    assert llm.chat([{"role": "user", "content": "hi"}], model="m1")[0] == "ok"
    assert fake.calls[0]["extra_body"] is not None and fake.calls[1]["extra_body"] is None
    llm.chat([{"role": "user", "content": "hi"}], model="m1")
    assert fake.calls[2]["extra_body"] is None  # remembered


def test_fatal_error_is_not_swallowed_by_evaluate(monkeypatch):
    def boom(*a, **k):
        raise llm.FatalAPIError("bad key")
    monkeypatch.setattr(engine, "run", boom)
    o = org.load(engine.ROOT + "/orgs/startup.yaml")
    with pytest.raises(llm.FatalAPIError):
        evaluate.evaluate(o, "train")


def test_meta_model_missing_falls_back_to_worker(monkeypatch):
    calls = []

    def chat(messages, model=None, **kw):
        calls.append(model)
        if model == "meta-x":
            raise llm.FatalAPIError("Model 'meta-x' not found")
        return '{"op": "toggle_shared_memory", "reason": "share"}', 0.0
    monkeypatch.setattr(llm, "chat", chat)
    monkeypatch.setattr(llm, "META_MODEL", "meta-x")
    monkeypatch.setattr(llm, "WORKER_MODEL", "worker-y")
    o = org.load(engine.ROOT + "/orgs/startup.yaml")
    card = {"score": 0.5, "solved": 1, "runs": 2, "cost_usd": 0.0, "escalations": 0, "failures": []}
    child, mut = evolve.meta_mutation(o, card, [])
    assert calls == ["meta-x", "worker-y"] and mut["source"] == "meta-agent" and child["shared_memory"]


def test_resolve_model_variants():
    avail = ["nvidia/Nemotron-3.5-Lightning-30B-A3B", "nvidia/NVIDIA-Nemotron-3-Super-120B-A12B"]
    assert llm.resolve_model("nvidia/nemotron-3.5-lightning-30b-a3b", avail) == avail[0]
    assert llm.resolve_model("nvidia/Nemotron-3-Super-120B-A12B", avail) == avail[1]
    assert llm.resolve_model("nvidia/NVIDIA-Nemotron-3-Super-120B-A12B", avail) == avail[1]
    assert llm.resolve_model("nvidia/other", avail) is None


def test_price_lookup_ignores_spelling():
    led = llm.Ledger(100)
    a = led.add("nvidia/NVIDIA-Nemotron-3-Super-120B-A12B", 1_000_000, 0)
    b = led.add("nvidia/Nemotron-3.5-Lightning-30B-A3B", 1_000_000, 0)
    assert a == pytest.approx(0.30) and b == pytest.approx(0.05)


def test_not_found_auto_resolves_once(live):
    fake = live([_err(openai.NotFoundError, 404), "ok"],
                model_ids=["nvidia/Nemotron-3.5-Lightning-30B-A3B"])
    text, _ = llm.chat([{"role": "user", "content": "hi"}], model="nvidia/nemotron-3.5-lightning-30b-a3b")
    assert text == "ok" and fake.calls[1]["model"] == "nvidia/Nemotron-3.5-Lightning-30B-A3B"
