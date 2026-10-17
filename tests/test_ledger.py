"""Credit protection: per-run cap, lifetime cap across runs, .env loading."""
import json
import os
import subprocess
import sys

import pytest

from darwin import llm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE = "nvidia/nemotron-3.5-lightning-30b-a3b"  # $0.05 in / $0.20 out per 1M


def test_run_cap():
    led = llm.Ledger(0.001)
    led.add(PRICE, 10_000, 10_000)  # $0.0025
    with pytest.raises(llm.BudgetExceeded, match="run budget"):
        led.check()


def test_lifetime_cap_accumulates_across_runs(tmp_path):
    path = str(tmp_path / "spend.json")
    run1 = llm.Ledger(100, total_budget_usd=0.004, persist=True, path=path)
    run1.add(PRICE, 10_000, 10_000)  # $0.0025
    run1.check()
    run1.flush()
    assert json.load(open(path))["total_usd"] == pytest.approx(0.0025)
    run2 = llm.Ledger(100, total_budget_usd=0.004, persist=True, path=path)  # a later run
    assert run2.lifetime() == pytest.approx(0.0025)
    run2.add(PRICE, 10_000, 10_000)
    with pytest.raises(llm.BudgetExceeded, match="lifetime budget"):
        run2.check()
    assert json.load(open(path))["total_usd"] == pytest.approx(0.005)


def test_flush_is_incremental(tmp_path):
    path = str(tmp_path / "spend.json")
    led = llm.Ledger(100, total_budget_usd=100, persist=True, path=path)
    for _ in range(3):
        led.add(PRICE, 10_000, 10_000)
        led.flush()
        led.flush()  # double flush must not double count
    assert json.load(open(path))["total_usd"] == pytest.approx(0.0075)


def test_mock_never_writes_spend_file(tmp_path):
    led = llm.Ledger(100, total_budget_usd=1, persist=False, path=str(tmp_path / "s.json"))
    led.add(PRICE, 1_000_000, 1_000_000)
    led.flush()
    assert not os.path.exists(tmp_path / "s.json")


def test_dotenv_loads_key_without_overriding(tmp_path):
    repo = tmp_path / "repo"
    (repo / "darwin").mkdir(parents=True)
    src = open(os.path.join(ROOT, "darwin", "__init__.py")).read()
    (repo / "darwin" / "__init__.py").write_text(src)
    (repo / ".env").write_text('# comment\nexport CRUSOE_API_KEY="abc123"\nDARWIN_BUDGET=1\nEMPTY=\n')
    code = "import os, darwin; print(os.environ.get('CRUSOE_API_KEY'), os.environ.get('DARWIN_BUDGET'))"
    env = {k: v for k, v in os.environ.items() if k not in ("CRUSOE_API_KEY", "DARWIN_BUDGET")}
    out = subprocess.run([sys.executable, "-c", code], cwd=repo, env=env, capture_output=True, text=True)
    assert out.stdout.split() == ["abc123", "1"]
    env["DARWIN_BUDGET"] = "7"  # real environment wins over .env
    out = subprocess.run([sys.executable, "-c", code], cwd=repo, env=env, capture_output=True, text=True)
    assert out.stdout.split() == ["abc123", "7"]


def test_env_file_is_gitignored():
    assert ".env" in open(os.path.join(ROOT, ".gitignore")).read().split()
