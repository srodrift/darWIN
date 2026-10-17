"""Run candidate code against a test file in an isolated subprocess.

Every org's code runs here, never in the engine's own process. Swap
`run_tests` for an NVIDIA OpenShell/NemoClaw sandbox call to harden it.
"""
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

TIMEOUT_S = 20


def run_tests(code: str, test_code: str, timeout: int = TIMEOUT_S) -> dict:
    """Write code as solution.py next to the test file and run pytest.

    Returns {"passed": int, "total": int, "output": str}.
    """
    with tempfile.TemporaryDirectory(prefix="darwin_") as d:
        with open(os.path.join(d, "solution.py"), "w") as f:
            f.write(code or "")
        with open(os.path.join(d, "test_task.py"), "w") as f:
            f.write(test_code or "")
        report = os.path.join(d, "report.xml")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                 "--tb=line", f"--junitxml={report}",
                 "test_task.py"],
                cwd=d, capture_output=True, text=True, timeout=timeout,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            output = (proc.stdout + proc.stderr)[-3000:]
        except subprocess.TimeoutExpired:
            return {"passed": 0, "total": 0, "output": "TIMEOUT"}

        passed, total = 0, 0
        if os.path.exists(report):
            try:
                root = ET.parse(report).getroot()
                suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
                for s in suites:
                    t = int(s.get("tests", 0))
                    bad = int(s.get("failures", 0)) + int(s.get("errors", 0)) + int(s.get("skipped", 0))
                    total += t
                    passed += t - bad
            except ET.ParseError:
                pass
        return {"passed": passed, "total": total, "output": output}
