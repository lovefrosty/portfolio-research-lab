"""Historical audit specimen. Known false acceptances are intentional.

Selected definitions are unchanged; imports are restricted to their dependencies.
See ../provenance.json for original file hashes and exact source line ranges.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, List, Sequence, Tuple


GroupKey = Callable[[Dict[str, Any]], Tuple[Any, ...]]


def _default_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    return (row.get("harness"), row.get("model_requested"), row.get("provider_requested"))


def pass_hat_k(rows: Sequence[Dict[str, Any]], k: int, *, key: GroupKey = _default_key,
               outcome: str = "combined_verdict") -> Dict[Tuple[Any, ...], Dict[str, Any]]:
    """Fraction of task groups where all k repetitions pass.

    Groups with fewer than k repetitions report `pass_hat_k=None` rather than
    scoring them from partial evidence.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    groups: Dict[Tuple[Any, ...], List[bool]] = defaultdict(list)
    for row in rows:
        result = row.get("result") or row.get("grade") or {}
        verdict = result.get(outcome) or result.get("verdict")
        groups[key(row)].append(str(verdict) == "pass")

    out: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for group, outcomes in groups.items():
        window = outcomes[:k]
        complete = len(outcomes) >= k
        out[group] = {
            "trials": len(outcomes),
            "k": k,
            "pass_hat_k": (1.0 if all(window) else 0.0) if complete else None,
            "pass_at_1": sum(outcomes) / len(outcomes),
            "inconsistent": bool(any(outcomes) and not all(outcomes)),
        }
    return out
