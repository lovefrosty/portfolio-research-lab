from __future__ import annotations

from uuid import UUID

import pytest

from research_ontology.contracts import PREDICTIVE_FIELDS


def opaque(number: int) -> str:
    return f"urn:portfolio-research:{UUID(f'00000000-0000-4000-8000-{number:012d}')}"


def planned(name: str, value: object = None, *, state: str = "specified") -> dict:
    return {
        "field_name": name,
        "state": state,
        "value": value if state == "specified" else None,
        "assumptions": [],
        "test_refs": [],
        "refinement_notes": [],
    }


def predictive_spec(**overrides: object) -> dict:
    values = {
        "target": "relative return",
        "forecast_origin": "Friday close",
        "information_cutoff": "Friday 16:00 ET",
        "horizon": "4 weeks",
        "universe": ["refiners", "upstream"],
        "benchmark": "upstream basket",
        "baseline": "oil-only model",
        "feature_proxy_refs": ["crack", "inventory"],
        "metric": "incremental return",
        "success_thresholds": {"minimum": 0.01},
        "disproof_thresholds": {"maximum": 0.0},
        "controls": ["walk_forward", "embargo"],
        "regimes": ["all", "recession"],
        "costs": {"bps": 10},
        "multiple_testing_family": "refining-v0",
        "expiry": "2027-01-01T00:00:00Z",
    }
    values.update(overrides)
    return {name: planned(name, values[name]) for name in PREDICTIVE_FIELDS}


@pytest.fixture
def ids():
    return opaque
