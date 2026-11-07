"""Historical audit specimen. Known false acceptances are intentional.

Selected definitions are unchanged; imports are restricted to their dependencies.
See ../provenance.json for original file hashes and exact source line ranges.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str | None:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def verify(record: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute every hash that still has a file on disk and report drift."""
    drift: Dict[str, Any] = {}
    prompt = record.get("task", {}).get("prompt")
    if prompt and Path(prompt).exists():
        now = sha256_file(Path(prompt))
        if now != record["task"].get("prompt_sha256"):
            drift["task.prompt_sha256"] = {"recorded": record["task"].get("prompt_sha256"), "now": now}
    for path, recorded in (record.get("task", {}).get("data_sha256") or {}).items():
        if Path(path).exists():
            now = sha256_file(Path(path))
            if now != recorded:
                drift[f"task.data_sha256[{path}]"] = {"recorded": recorded, "now": now}
    for path, recorded in (record.get("evaluator", {}).get("rubric_sha256") or {}).items():
        if Path(path).exists():
            now = sha256_file(Path(path))
            if now != recorded:
                drift[f"evaluator.rubric_sha256[{path}]"] = {"recorded": recorded, "now": now}
    return {"verified": not drift, "drift": drift}
