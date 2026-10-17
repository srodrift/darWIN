from darwin import sandbox


def test_counts_pass_and_fail():
    code = "def f(x):\n    return x + 1\n"
    tests = "from solution import f\ndef test_a(): assert f(1) == 2\ndef test_b(): assert f(1) == 3\n"
    r = sandbox.run_tests(code, tests)
    assert (r["passed"], r["total"]) == (1, 2)


def test_syntax_error_scores_zero():
    r = sandbox.run_tests("def f(:\n", "from solution import f\ndef test_a(): assert f\n")
    assert r["passed"] == 0


def test_infinite_loop_times_out():
    r = sandbox.run_tests("def f():\n    while True: pass\n",
                          "from solution import f\ndef test_a(): f()\n", timeout=3)
    assert r["passed"] == 0 and r["output"] == "TIMEOUT"
