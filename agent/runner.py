"""Test environment and pytest runs. Deterministic, no LLM. A JS adapter would replace only this file."""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


class EnvError(Exception):
    """The environment or the test run itself is broken (not a test failure)."""


def _run(cmd, cwd, timeout):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise EnvError(f"timed out after {timeout}s: {' '.join(map(str, cmd[:4]))}")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def setup_env(repo, run_dir):
    """Create run_dir/venv with pytest and the repo's dependencies. Returns (python path, warning)."""
    repo, venv = Path(repo), Path(run_dir) / "venv"
    code, out = _run([sys.executable, "-m", "venv", str(venv)], run_dir, 300)
    if code:
        raise EnvError(f"could not create venv:\n{out[-2000:]}")
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    cmd = [str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check", "pytest"]
    if (repo / "requirements.txt").exists():
        cmd += ["-r", "requirements.txt"]
    code, out = _run(cmd, repo, 900)
    if code:
        raise EnvError(f"dependency install failed:\n{out[-2000:]}")
    warning = ""
    if (repo / "pyproject.toml").exists() or (repo / "setup.py").exists():
        # Not fatal: many repos carry a pyproject.toml only for tool config.
        code, out = _run([str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check", "-e", "."], repo, 900)
        if code:
            warning = "pip install -e . failed; running tests without it"
    return python, warning


def run_tests(python, repo, run_dir, label):
    """Run the full suite. Returns ({test_id: passed|failed|error|skipped}, output)."""
    xml = Path(run_dir) / f"junit_{label}.xml"
    xml.unlink(missing_ok=True)
    code, out = _run([str(python), "-m", "pytest", "-q", "--rootdir=.", "-p", "no:cacheprovider",
                      "--continue-on-collection-errors", f"--junitxml={xml}"],
                     repo, int(os.getenv("TEST_TIMEOUT", "300")))
    if code == 5:  # no tests collected
        return {}, out
    if code not in (0, 1, 2) or not xml.exists():
        raise EnvError(f"pytest could not run (exit {code}):\n{out[-2000:]}")
    results = {}
    for case in ET.parse(xml).getroot().iter("testcase"):
        test_id = f"{case.get('classname')}::{case.get('name')}"
        kinds = {child.tag for child in case}
        results[test_id] = next((k if k != "failure" else "failed" for k in ("error", "failure", "skipped") if k in kinds), "passed")
    return results, out


def compare(before, after):
    """Tests that passed before and do not pass now (a deleted test counts)."""
    # ponytail: single run, no flaky-test rerun; rerun failures once here if flakiness shows up
    return sorted(t for t, s in before.items() if s == "passed" and after.get(t) != "passed")


def counts(results):
    passed = sum(s == "passed" for s in results.values())
    failed = sum(s in ("failed", "error") for s in results.values())
    return {"passed": passed, "failed": failed, "total": len(results)}
