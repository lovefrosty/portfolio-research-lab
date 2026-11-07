"""Historical audit specimen. Known false acceptances are intentional.

Selected definitions are unchanged; imports are restricted to their dependencies.
See ../provenance.json for original file hashes and exact source line ranges.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _load_fixture_gate(task_dir: Path):
    """Grade with the gate version the task pinned, so a later repo edit cannot
    retroactively fail (or pass) a run that never saw it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gate_fixture", task_dir / "gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INFRA_PATTERNS = (
    "does not support this model",
    "not supported when using",
    "invalid_request_error",
    "authrequired",
    "command not found",
    "connection refused",
    "unauthorized",
    "session limit",
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota",
    "overloaded",
)


INFRA_REGEXES = (
    r'"api_error_status"\s*:\s*\d{3}',
    r'"terminal_reason"\s*:\s*"api_error"',
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def grade_cell(workspace: Path, task_dir: Path, transcript: Path,
               returncode: int | None = None) -> dict[str, Any]:
    text = transcript.read_text(errors="replace") if transcript.is_file() else ""
    submission = workspace / "hypothesis.json"

    problems = _load_fixture_gate(task_dir).check(submission)
    artifact_pass = not problems

    # Gate invocation is evidenced by the receipt the gate writes itself, not by
    # the transcript: an agent that says "run gate.py" leaves no receipt.
    receipt_path = workspace / "gate_receipt.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
    gate_evidence = bool(
        receipt
        and receipt.get("status") == "pass"
        and receipt.get("artifact_sha256") == _sha(submission)
        and receipt.get("gate_source_sha256") == _sha(workspace / "gate.py")
    )
    trace = {
        "artifact_written": submission.is_file(),
        "gate_receipt": gate_evidence,
        "gate_copy_unmodified": _sha(workspace / "gate.py") == _sha(task_dir / "gate.py"),
        "brief_unmodified": _sha(workspace / "BRIEF.md") == _sha(task_dir / "BRIEF.md"),
    }
    trace_pass = all(trace.values())
    structured = any(re.search(rx, text) for rx in INFRA_REGEXES)
    phrased = returncode not in (None, 0) and any(p in text.lower() for p in INFRA_PATTERNS)
    infra = bool(structured or phrased)

    if infra:
        verdict, score = "invalid", 0.0
    elif artifact_pass and trace_pass:
        verdict, score = "pass", 1.0
    elif artifact_pass and not trace_pass:
        verdict, score = "pass_unverified", 0.5
    else:
        verdict, score = "fail", 0.0

    return {
        "verdict": verdict,
        "score": score,
        "infrastructure_failure": infra,
        "artifact": {"pass": artifact_pass, "problems": problems},
        "trace": trace,
        "trace_pass": trace_pass,
    }
