from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from research_ontology.verifier import (
    EVENT_SCHEMA,
    HASH_DOMAIN,
    VERIFICATION_SCHEMA,
    canonical_json_bytes,
    compute_event_hash,
    verify_ledger_bytes,
    verify_ledger_path,
)


ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "research_ontology" / "verifier.py"


def _id(number: int) -> str:
    return f"urn:portfolio-research:00000000-0000-4000-8000-{number:012d}"


def _record_type(event_type: str) -> str:
    return {
        "ontology_release": "OntologyRelease",
        "claim_version": "ClaimVersion",
        "inference": "InferenceReceipt",
        "evidence_assessment": "EvidenceAssessment",
        "artifact_reference": "ArtifactReference",
        "disposition_record": "DispositionRecord",
        "proxy_gate_decision": "ProxyGateDecision",
    }.get(event_type, "TestRecord")


def _claim_fingerprint(payload: dict) -> str:
    core = {
        field: payload[field]
        for field in (
            "claim_kind",
            "proposition",
            "scope",
            "spec",
            "parent_claim_ids",
            "mechanism_ids",
        )
    }
    return hashlib.sha256(
        b"claim_semantic_fingerprint_v0\0" + canonical_json_bytes(core)
    ).hexdigest()


def _event(
    number: int,
    *,
    event_type: str = "claim_version",
    object_id: str | None = None,
    version_id: str | None = None,
    actor_kind: str = "system",
    actor_id: str = "test-system",
    payload: dict | None = None,
) -> dict:
    object_id = object_id or _id(number * 10 + 2)
    version_id = version_id or _id(number * 10 + 3)
    body = payload or {
        "claim_kind": "structural",
        "proposition": "A fixture mechanism has a bounded relation.",
        "scope": {"universe": "fixture"},
        "spec": {"subjects": [], "relation": {}, "objects": [], "conditions": {}},
        "parent_claim_ids": [],
        "mechanism_ids": [],
    }
    body = deepcopy(body)
    body.setdefault("record_type", _record_type(event_type))
    body.setdefault("object_id", object_id)
    body.setdefault("version_id", version_id)
    body.setdefault("research_only", True)
    body.setdefault("execution_allowed", False)
    if body["record_type"] == "ClaimVersion":
        body.setdefault("semantic_fingerprint", _claim_fingerprint(body))
    return {
        "schema": EVENT_SCHEMA,
        "event_id": _id(number * 10 + 1),
        "object_id": object_id,
        "version_id": version_id,
        "event_type": event_type,
        "ontology_version": "0.1.0",
        "actor": {"actor_id": actor_id, "actor_kind": actor_kind},
        "recorded_at": f"2026-01-01T00:00:{number:02d}Z",
        "payload": body,
        "previous_event_hash": None,
        "event_hash": "0" * 64,
        "research_only": True,
        "execution_allowed": False,
    }


def _chain(*events: dict) -> list[dict]:
    out = []
    previous = None
    for source in events:
        event = deepcopy(source)
        event["previous_event_hash"] = previous
        event["event_hash"] = compute_event_hash(event)
        previous = event["event_hash"]
        out.append(event)
    return out


def _raw(events: list[dict]) -> bytes:
    return b"\n".join(canonical_json_bytes(event) for event in events) + b"\n"


def _codes(result: dict) -> set[str]:
    return {row["code"] for row in result["errors"]}


def test_verifier_has_no_ontology_or_application_imports() -> None:
    tree = ast.parse(VERIFIER.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])

    assert imported <= {
        "__future__",
        "datetime",
        "hashlib",
        "json",
        "math",
        "pathlib",
        "re",
        "typing",
        "uuid",
    }
    assert not ({"research_ontology", "research_lab", "research_compiler"} & imported)


def test_valid_raw_jsonl_recomputes_chain_and_complete_report(tmp_path: Path) -> None:
    events = _chain(_event(1), _event(2))
    raw = _raw(events)
    result = verify_ledger_bytes(raw)

    assert result == {
        "schema": VERIFICATION_SCHEMA,
        "valid": True,
        "event_count": 2,
        "head_hash": events[-1]["event_hash"],
        "ledger_sha256": hashlib.sha256(raw).hexdigest(),
        "errors": [],
    }

    path = tmp_path / "ledger.jsonl"
    path.write_bytes(raw)
    assert verify_ledger_path(path) == result


def test_generic_writer_event_type_is_dispatched_by_payload_record_type() -> None:
    event = _event(1, event_type="record_appended")
    event["ontology_version"] = "0.1.0-rc.1"
    event["payload"]["record_type"] = "ClaimVersion"
    event["payload"]["semantic_fingerprint"] = _claim_fingerprint(event["payload"])

    result = verify_ledger_bytes(_raw(_chain(event)))

    assert result["valid"] is True
    assert result["errors"] == []


def test_hash_basis_excludes_only_event_hash() -> None:
    event = _event(1)
    expected = hashlib.sha256(
        HASH_DOMAIN
        + canonical_json_bytes({key: value for key, value in event.items() if key != "event_hash"})
    ).hexdigest()

    assert compute_event_hash(event) == expected
    event["payload"]["proposition"] = "Changed"
    assert compute_event_hash(event) != expected


def test_thousand_record_replay_is_deterministic_without_a_latency_claim() -> None:
    events = []
    for number in range(1, 1_001):
        event = _event(number, event_type="record_appended", payload={"note": number})
        event["recorded_at"] = "2026-01-01T00:00:00Z"
        events.append(event)
    raw = _raw(_chain(*events))

    first = verify_ledger_bytes(raw)
    second = verify_ledger_bytes(raw)

    assert first == second
    assert first["valid"] is True
    assert first["event_count"] == 1_000


def test_tamper_chain_and_duplicate_versions_are_independent_failures() -> None:
    first, second = _chain(_event(1), _event(2))

    tampered = deepcopy(second)
    tampered["payload"]["artifact_refs"] = [_id(999)]
    assert _codes(verify_ledger_bytes(_raw([first, tampered]))) == {"event_hash_mismatch"}

    broken = deepcopy(second)
    broken["previous_event_hash"] = "f" * 64
    broken["event_hash"] = compute_event_hash(broken)
    assert _codes(verify_ledger_bytes(_raw([first, broken]))) == {
        "previous_event_hash_mismatch"
    }

    duplicate = _event(2, version_id=first["version_id"])
    duplicate["payload"]["version_id"] = first["version_id"]
    assert _codes(verify_ledger_bytes(_raw(_chain(first, duplicate)))) == {
        "duplicate_version_id"
    }


def test_parser_rejects_duplicate_keys_non_utf8_and_blank_records() -> None:
    event = _chain(_event(1))[0]
    valid = canonical_json_bytes(event)
    duplicate = valid.replace(b'{"actor":', b'{"schema":"duplicate","actor":', 1)

    assert _codes(verify_ledger_bytes(duplicate + b"\n")) == {"duplicate_json_key"}
    assert _codes(verify_ledger_bytes(b"\xff")) == {"invalid_utf8"}
    assert _codes(verify_ledger_bytes(valid + b"\n\n")) == {"blank_jsonl_line"}
    assert _codes(verify_ledger_bytes(valid)) == {"ledger_missing_final_newline"}


def test_boundaries_status_and_unqualified_semantic_edges_fail_closed() -> None:
    event = _event(1)
    event["research_only"] = False
    event["execution_allowed"] = True
    event["payload"]["status"] = "supported"
    event["payload"]["can_affect_trading"] = True
    event["payload"]["edges"] = [
        {"from": "feature", "relation": "predicts", "to": "outcome"}
    ]
    result = verify_ledger_bytes(_raw(_chain(event)))

    assert _codes(result) == {
        "execution_allowed_must_be_false",
        "research_only_must_be_true",
        "trading_authority_forbidden",
        "universal_status_forbidden",
        "unqualified_forbidden_semantic_edge",
    }


def test_claim_semantic_change_requires_new_object_but_metadata_version_does_not() -> None:
    first = _event(1)
    metadata = _event(
        2,
        object_id=first["object_id"],
        payload={**first["payload"], "artifact_refs": [_id(900)]},
    )
    metadata["payload"]["version_id"] = metadata["version_id"]
    assert verify_ledger_bytes(_raw(_chain(first, metadata)))["valid"] is True

    changed = _event(
        2,
        object_id=first["object_id"],
        payload=deepcopy(first["payload"]),
    )
    changed["payload"]["version_id"] = changed["version_id"]
    changed["payload"]["spec"]["conditions"] = {"support_rule": "changed"}
    changed["payload"]["semantic_fingerprint"] = _claim_fingerprint(
        changed["payload"]
    )
    assert _codes(verify_ledger_bytes(_raw(_chain(first, changed)))) == {
        "claim_semantic_change_requires_new_object"
    }


def test_release_term_rewrite_is_detected_across_valid_hash_chain() -> None:
    term_id = _id(501)
    first = _event(
        1,
        event_type="ontology_release",
        payload={
            "version": "0.1.0",
            "terms": [{"term_id": term_id, "term_key": "claim", "definition": "First"}],
        },
    )
    second = _event(
        2,
        event_type="ontology_release",
        payload={
            "version": "0.1.0",
            "terms": [{"term_id": _id(502), "term_key": "other", "definition": "Other"}],
        },
    )
    assert "ontology_release_version_rewrite" in _codes(
        verify_ledger_bytes(_raw(_chain(first, second)))
    )

    second["ontology_version"] = "0.2.0"
    second["payload"]["version"] = "0.2.0"
    second["payload"]["terms"] = [
        {"term_id": term_id, "term_key": "claim", "definition": "Rewritten"}
    ]
    assert "ontology_term_rewrite_forbidden" in _codes(
        verify_ledger_bytes(_raw(_chain(first, second)))
    )


def test_disposition_blocked_evidence_and_proxy_materiality_are_independently_checked() -> None:
    target = _event(1)
    disposition = _event(
        2,
        event_type="disposition_record",
        actor_kind="agent",
        actor_id="agent-1",
        payload={
            "target_object_id": target["object_id"],
            "target_version_id": target["version_id"],
            "reviewer_id": "agent-1",
            "authority": "human_reviewed",
            "decision": "kept",
            "rationale": "The exact target was reviewed.",
            "decision_at": "2026-01-01T00:00:02Z",
            "scope": {"claim_version_id": target["version_id"]},
        },
    )
    assert _codes(verify_ledger_bytes(_raw(_chain(target, disposition)))) == {
        "disposition_requires_human_actor"
    }

    blocked = _event(
        2,
        event_type="evidence_assessment",
        payload={
            "claim_version_id": target["version_id"],
            "evidence": "blocked_by_data",
            "admissibility": "blocked",
            "evidence_effect": "contradicts",
        },
    )
    assert _codes(verify_ledger_bytes(_raw(_chain(target, blocked)))) == {
        "blocked_data_is_not_support_or_contradiction"
    }

    proxy = _event(
        1,
        event_type="proxy_gate_decision",
        payload={"requested_use": "target", "outcome": "preapproved"},
    )
    assert _codes(verify_ledger_bytes(_raw(_chain(proxy)))) == {
        "material_proxy_substitution_requires_review"
    }


def test_error_rows_are_structured_stable_and_deterministic() -> None:
    event = _event(1)
    event["payload"]["status"] = "mixed"
    raw = _raw(_chain(event))

    first = verify_ledger_bytes(raw)
    second = verify_ledger_bytes(raw)

    assert first == second
    assert first["valid"] is False
    assert first["event_count"] == 1
    assert first["head_hash"]
    assert first["ledger_sha256"] == hashlib.sha256(raw).hexdigest()
    assert first["errors"] == [
        {
            "code": "universal_status_forbidden",
            "line": 1,
            "event_id": event["event_id"],
            "path": "payload.status",
        }
    ]


def test_generic_nested_axes_and_human_declarations_fail_outside_legacy_annotations() -> None:
    invalid = _event(
        1,
        event_type="record_appended",
        actor_kind="agent",
        payload={
            "freshness": "recentish",
            "axes": {"evidence": "decisive", "invented": "value"},
            "nested": {"authority": "human_reviewed", "decision": "kept"},
        },
    )
    assert _codes(verify_ledger_bytes(_raw(_chain(invalid)))) == {
        "agent_generated_human_authority_forbidden",
        "agent_generated_human_decision_forbidden",
        "evidence_axis_invalid",
        "freshness_axis_invalid",
        "unknown_axis_forbidden",
    }

    legacy = _event(
        1,
        event_type="record_appended",
        actor_kind="migration",
        payload={
            "legacy_annotations": {
                "status": "supported",
                "authority": "human_reviewed",
                "decision": "kept",
                "axes": {"evidence": "legacy-score"},
            }
        },
    )
    assert verify_ledger_bytes(_raw(_chain(legacy)))["valid"] is True


def _axis_receipt(
    number: int,
    target: dict,
    *,
    axis_name: str = "decision",
    axis_value: str = "pending",
) -> dict:
    return _event(
        number,
        event_type="record_appended",
        payload={
            "record_type": "axisreceipt",
            "target_object_id": target["object_id"],
            "target_version_id": target["version_id"],
            "axis_name": axis_name,
            "axis_value": axis_value,
            "scope": {"applies_to": "exact_version"},
        },
    )


def test_exact_targets_and_assessments_resolve_across_complete_ledger() -> None:
    target = _event(2)
    forward_receipt = _axis_receipt(1, target)
    assert verify_ledger_bytes(_raw(_chain(forward_receipt, target)))["valid"] is True

    wrong_owner = deepcopy(forward_receipt)
    wrong_owner["payload"]["target_object_id"] = _id(999)
    assert _codes(verify_ledger_bytes(_raw(_chain(wrong_owner, target)))) == {
        "exact_target_object_version_mismatch"
    }

    missing = _axis_receipt(1, target)
    assert "exact_target_version_not_found" in _codes(
        verify_ledger_bytes(_raw(_chain(missing)))
    )

    assessment = _event(
        1,
        event_type="record_appended",
        payload={
            "record_type": "evidenceassessment",
            "claim_version_id": target["version_id"],
            "evidence": "untested",
            "admissibility": "inadmissible",
        },
    )
    assert verify_ledger_bytes(_raw(_chain(assessment, target)))["valid"] is True
    assert "assessment_target_version_not_found" in _codes(
        verify_ledger_bytes(_raw(_chain(assessment)))
    )


def test_lifecycle_receipts_are_one_way_and_evidence_findings_are_not_axis_receipts() -> None:
    target = _event(1)
    retract = _axis_receipt(
        2, target, axis_name="lifecycle", axis_value="retracted"
    )
    reactivate = _axis_receipt(
        3, target, axis_name="lifecycle", axis_value="active"
    )
    assert _codes(
        verify_ledger_bytes(_raw(_chain(target, retract, reactivate)))
    ) == {"lifecycle_transition_forbidden"}

    unchanged = _axis_receipt(2, target, axis_name="lifecycle", axis_value="active")
    assert _codes(verify_ledger_bytes(_raw(_chain(target, unchanged)))) == {
        "lifecycle_receipt_must_change_value"
    }

    unsupported = _axis_receipt(
        2, target, axis_name="evidence", axis_value="supported_in_scope"
    )
    assert _codes(verify_ledger_bytes(_raw(_chain(target, unsupported)))) == {
        "support_or_contradiction_requires_evidence_assessment"
    }


def _release_payload(version: str, terms: list[dict] | None = None) -> dict:
    return {
        "version": version,
        "terms": terms
        or [
            {
                "term_id": _id(700),
                "term_key": "claim_version",
                "definition": "An immutable claim version.",
            }
        ],
        "derivation_rules": [
            {
                "rule_id": "version_identity_v0",
                "relation": "version_of",
                "version": "0.1.0",
                "source_record": "versioned_record",
                "source_field": "object_id",
                "deterministic": True,
                "provenance_required": True,
                "semantic_authority_added": False,
                "transitive": False,
            }
        ],
        "lifecycle_values": ["active", "superseded", "retracted"],
        "evidence_values": sorted(
            {
                "untested",
                "supported_in_scope",
                "contradicted_in_scope",
                "mixed",
                "insufficient",
                "unstable",
                "proxy_only",
                "blocked_by_data",
            }
        ),
        "authority_values": [
            "agent_proposed",
            "legacy_import_unreviewed",
            "human_reviewed",
        ],
        "decision_values": [
            "pending",
            "kept",
            "rejected_exact",
            "retyped",
            "revision_requested",
            "deferred",
        ],
        "freshness_values": ["not_applicable", "current", "expired", "unknown"],
        "admissibility_values": ["admissible", "inadmissible", "blocked"],
    }


def _release_event(number: int, version: str, payload: dict | None = None) -> dict:
    event = _event(
        number,
        event_type="ontology_release",
        payload=payload or _release_payload(version),
    )
    event["ontology_version"] = version
    return event


def test_release_semver_freeze_additivity_and_full_term_identity() -> None:
    release = _release_event(1, "0.1.0")
    reused = _release_event(2, "0.1.0")
    assert _codes(verify_ledger_bytes(_raw(_chain(release, reused)))) == {
        "ontology_release_version_reused"
    }

    rc = _release_event(1, "0.1.0-rc.1")
    final = _release_event(2, "0.1.0")
    assert verify_ledger_bytes(_raw(_chain(rc, final)))["valid"] is True

    patch_payload = _release_payload("0.1.1")
    patch_payload["freshness_values"] = [
        "not_applicable",
        "current",
        "expired",
        "unknown",
        "future",
    ]
    changed_patch = _release_event(2, "0.1.1", patch_payload)
    assert "ontology_patch_meaning_change_forbidden" in _codes(
        verify_ledger_bytes(_raw(_chain(release, changed_patch)))
    )

    replacement_term = {
        "term_id": _id(701),
        "term_key": "additional_term",
        "definition": "A compatible addition that omits the old term.",
    }
    nonadditive_minor = _release_event(
        2,
        "0.2.0",
        _release_payload("0.2.0", [replacement_term]),
    )
    assert "ontology_minor_must_be_additive" in _codes(
        verify_ledger_bytes(_raw(_chain(release, nonadditive_minor)))
    )

    rewritten = deepcopy(_release_payload("1.0.0")["terms"][0])
    rewritten["deprecated"] = True
    rewritten_major = _release_event(
        2, "1.0.0", _release_payload("1.0.0", [rewritten])
    )
    assert "ontology_term_rewrite_forbidden" in _codes(
        verify_ledger_bytes(_raw(_chain(release, rewritten_major)))
    )
