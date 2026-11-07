"""Historical audit specimen. Known false acceptances are intentional.

Selected definitions are unchanged; imports are restricted to their dependencies.
See ../provenance.json for original file hashes and exact source line ranges.
"""
from __future__ import annotations

import json
from pathlib import Path


REQUIRED = ("hypothesis", "mechanism", "kill_criterion", "horizon", "cost_model", "verdict_scale")


def check(path: Path) -> list[str]:
    if not path.is_file():
        return [f"missing hypothesis record: {path}"]
    rec = json.loads(path.read_text())
    problems: list[str] = []
    for field in REQUIRED:
        if not str(rec.get(field) or "").strip():
            problems.append(f"missing {field}")

    sentence = str(rec.get("hypothesis", "")).strip()
    import re
    terminators = len(re.findall(r"[.!?](?:\s|$)", sentence))
    if sentence and (terminators > 1 or ";" in sentence):
        problems.append("hypothesis must be one sentence, not a paragraph")

    kill_raw = rec.get("kill_criterion") or {}
    kill: dict = {"text": kill_raw} if isinstance(kill_raw, str) else dict(kill_raw)
    if not kill.get("text"):
        problems.append("kill_criterion needs a text field")
    metrics = kill.get("metrics") or []
    if not metrics:
        problems.append("kill_criterion needs at least one numeric metric with a threshold")
    for metric in metrics:
        # A key that exists but is null is not a threshold: it makes the kill
        # criterion unfalsifiable while satisfying a presence check.
        candidates = [metric.get(k) for k in ("threshold", "minimum", "maximum")]
        if not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in candidates):
            problems.append(f"kill metric {metric.get('name')!r} has no numeric threshold")

    costs = rec.get("cost_model") or {}
    if not costs.get("id"):
        problems.append("cost_model.id is required so reports can cite it")
    if costs.get("evidence_kind") not in {"venue_evidence", "assumption"}:
        problems.append("cost_model.evidence_kind must be venue_evidence or assumption")
    for field in ("fee_bps", "spread_bps", "slippage_bps"):
        if not isinstance(costs.get(field), (int, float)):
            problems.append(f"cost_model.{field} must be numeric")

    if rec.get("holdout_access_declared") is not False:
        problems.append("holdout_access_declared must be false at preregistration")

    prereg = rec.get("preregistered_at")
    first_read = rec.get("first_data_read_at")
    basis = rec.get("preregistration_basis")
    if not prereg:
        problems.append("preregistered_at timestamp required")
    elif first_read and str(prereg) > str(first_read):
        # Peeking is allowed only if declared, and it brands the result for good.
        if basis == "after_data_scoring":
            problems.append("preregistration after scoring is not a preregistration; start a new investigation")
        elif basis != "after_data_inventory":
            problems.append("hypothesis written after the data was read: declare preregistration_basis")
    if basis not in {"before_data", "after_data_inventory", "after_data_scoring"}:
        problems.append("preregistration_basis must be declared")
    if basis == "after_data_inventory" and rec.get("exploratory") is not True:
        problems.append("a hypothesis formed after seeing the data must be marked exploratory=true")
    return problems
