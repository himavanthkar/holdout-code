"""Run a pytest file against a solution in an isolated sandbox.

run_tests(solution_code, test_code, timeout=10) -> {passed, failed, errors, total, failing_tests, timed_out, output}
"""
from __future__ import annotations

import base64
import hashlib
import os
import signal
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


class LocalSandbox:
    """Temp dir + subprocess pytest, stripped environment (no API keys), killed on timeout."""

    name = "local"

    def run_tests(self, solution_code: str, test_code: str, timeout: float = 10) -> dict:
        with tempfile.TemporaryDirectory(prefix="pod_sbx_") as d:
            p = Path(d)
            (p / "solution.py").write_text(solution_code)
            (p / "test_solution.py").write_text(test_code)
            home = p / "home"
            home.mkdir()
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "PYTHONPATH": str(p),
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}
            cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=",
                   "--junitxml=report.xml", "test_solution.py"]
            proc = subprocess.Popen(cmd, cwd=p, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, start_new_session=True)
            try:
                out, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate()
                return {"passed": 0, "failed": 0, "errors": 1, "total": 0, "timed_out": True,
                        "failing_tests": [{"name": "<timeout>", "message": f"test run exceeded {timeout}s"}],
                        "output": "TIMEOUT"}
            res = _parse_junit(p / "report.xml", out)
            # tamper check: the locked test file must be byte-identical after the run
            res["tests_intact"] = (p / "test_solution.py").exists() and (p / "test_solution.py").read_text() == test_code
            return res


def _parse_junit(report: Path, out: str) -> dict:
    return _parse_junit_text(report.read_text() if report.exists() else "", out)


def _parse_junit_text(xml_text: str, out: str) -> dict:
    res = {"passed": 0, "failed": 0, "errors": 0, "total": 0, "timed_out": False, "failing_tests": [],
           "output": out[-3000:]}
    try:
        root = ET.fromstring(xml_text.strip()) if xml_text.strip() else None
    except ET.ParseError:
        root = None
    if root is None:
        res["errors"] = 1
        res["failing_tests"].append({"name": "<collection>", "message": out[-1500:]})
        return res
    for tc in root.iter("testcase"):
        res["total"] += 1
        bad = tc.find("failure")
        kind = "failed"
        if bad is None:
            bad = tc.find("error")
            kind = "errors"
        if bad is None:
            if tc.find("skipped") is None:
                res["passed"] += 1
            continue
        res[kind] += 1
        msg = (bad.get("message") or "") + "\n" + (bad.text or "")
        res["failing_tests"].append({"name": tc.get("name", "?"), "message": msg.strip()[:800]})
    if res["total"] == 0:  # collection error (e.g. import failure) produces no testcases on some versions
        res["errors"] = 1
        res["failing_tests"].append({"name": "<collection>", "message": out[-1500:]})
    return res


class OpenShellSandbox:
    """NVIDIA OpenShell sandbox. Same interface; selected by SANDBOX=openshell.

    Code runs inside a persistent OpenShell sandbox (a micro-VM on the macOS VM driver) as an unprivileged user, with
    OpenShell's default deny-by-default network policy and no credentials attached. One `openshell sandbox exec` per
    test run: files go in base64-encoded, pytest runs under `timeout -s KILL`, the JUnit XML comes back on stdout.
    Create the sandbox once with `python -m pod.openshell_setup`.
    """

    name = "openshell"
    VENDOR = "/sandbox/vendor/podvendor"  # pytest + deps uploaded by pod.openshell_setup (no network in the sandbox)

    def __init__(self, sandbox: str | None = None):
        self.sandbox = sandbox or os.environ.get("OPENSHELL_SANDBOX", "pod-sbx")

    def run_tests(self, solution_code: str, test_code: str, timeout: float = 10) -> dict:
        d = f"/tmp/pod_{uuid.uuid4().hex[:12]}"
        b64 = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731
        script = (
            f"mkdir -p {d} && cd {d} && printf %s '{b64(solution_code)}' | base64 -d > solution.py && "
            f"printf %s '{b64(test_code)}' | base64 -d > test_solution.py; "
            f"PYTHONPATH={d}:{self.VENDOR} HOME={d} PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 "
            f"timeout -s KILL {int(timeout)} python3 -m pytest -q -p no:cacheprovider -o addopts= "
            f"--junitxml=report.xml test_solution.py > out.txt 2>&1; rc=$?; "
            f"echo @@RC $rc; echo @@SHA $(sha256sum test_solution.py | cut -c1-64); echo @@OUT; tail -c 3000 out.txt; "
            f"echo; echo @@XML; cat report.xml 2>/dev/null; cd / && rm -rf {d}"
        )
        cmd = ["openshell", "sandbox", "exec", self.sandbox, "--no-tty", "--no-login-shell",
               "--timeout", str(int(timeout) + 20), "--", "sh", "-c", script]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 40, cwd=tempfile.gettempdir())
        except subprocess.TimeoutExpired:
            return {"passed": 0, "failed": 0, "errors": 1, "total": 0, "timed_out": True,
                    "failing_tests": [{"name": "<timeout>", "message": "openshell exec timed out"}], "output": "TIMEOUT"}
        out = p.stdout
        if "@@RC" not in out:
            raise RuntimeError(f"openshell exec failed (is sandbox '{self.sandbox}' ready? run python -m pod.openshell_setup): "
                               f"{(p.stderr or out)[-400:]}")
        rc = int(out.split("@@RC", 1)[1].split()[0])
        sha = out.split("@@SHA", 1)[1].split()[0] if "@@SHA" in out else ""
        body = out.split("@@OUT", 1)[1].split("@@XML", 1)[0] if "@@OUT" in out else ""
        xml = out.split("@@XML", 1)[1] if "@@XML" in out else ""
        if rc == 137:  # killed by `timeout -s KILL`
            return {"passed": 0, "failed": 0, "errors": 1, "total": 0, "timed_out": True, "tests_intact": True,
                    "failing_tests": [{"name": "<timeout>", "message": f"test run exceeded {timeout}s"}], "output": "TIMEOUT"}
        res = _parse_junit_text(xml, body)
        res["tests_intact"] = sha == hashlib.sha256(test_code.encode()).hexdigest()
        return res


def get_sandbox(kind: str = "local"):
    return OpenShellSandbox() if kind == "openshell" else LocalSandbox()


def run_tests(solution_code: str, test_code: str, timeout: float = 10, kind: str = "local") -> dict:
    return get_sandbox(kind).run_tests(solution_code, test_code, timeout)


def failure_signature(result: dict) -> frozenset:
    return frozenset(t["name"] for t in result.get("failing_tests", []))


def summarize(result: dict) -> str:
    tot = result["passed"] + result["failed"] + result["errors"]
    s = f"{result['passed']}/{tot} pass"
    if result["timed_out"]:
        s += " (timed out)"
    return s
