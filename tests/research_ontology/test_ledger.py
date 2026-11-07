from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from research_ontology import ClaimKind, ClaimVersion
from research_ontology.ledger import (
    AppendOnlyLedger,
    LedgerValidationError,
    build_event,
    encode_events,
    event_hash,
    replay_ledger_bytes,
)

from .conftest import opaque, predictive_spec


NOW = "2026-09-01T00:00:00Z"


def payload(record_type: str = "TestRecord") -> dict:
    return {
        "record_type": record_type,
        "research_only": True,
        "execution_allowed": False,
    }


def event(number: int, *, previous: str | None = None, body: dict | None = None) -> dict:
    return build_event(
        object_id=opaque(number * 10 + 1),
        version_id=opaque(number * 10 + 2),
        event_type="record_appended",
        ontology_version="0.1.0-rc.1",
        actor_id="test-system",
        actor_kind="system",
        recorded_at=NOW,
        payload=body or payload(),
        previous_event_hash=previous,
        event_id=opaque(number * 10 + 3),
    )


def release_event(
    number: int,
    version: str,
    release_payload: dict,
    *,
    previous: str | None = None,
) -> dict:
    object_id = opaque(500 + number * 3)
    version_id = opaque(501 + number * 3)
    body = deepcopy(release_payload)
    body.update(
        {
            "record_type": "OntologyRelease",
            "release_id": object_id,
            "object_id": object_id,
            "version_id": version_id,
            "version": version,
            "released_at": f"2026-09-01T00:00:0{number}Z",
            "research_only": True,
            "execution_allowed": False,
        }
    )
    return build_event(
        object_id=object_id,
        version_id=version_id,
        event_type="ontology_release_appended",
        ontology_version=version,
        actor_id="ontology-release-test",
        actor_kind="system",
        recorded_at=f"2026-09-01T00:00:0{number}Z",
        payload=body,
        previous_event_hash=previous,
        event_id=opaque(502 + number * 3),
    )


def test_constructor_has_no_write_side_effect(tmp_path: Path):
    path = tmp_path / "missing" / "ledger.jsonl"
    AppendOnlyLedger(path)
    assert not path.exists()
    assert not path.parent.exists()


def test_append_and_replay_hash_chain(tmp_path: Path):
    ledger = AppendOnlyLedger(tmp_path / "ledger.jsonl")
    first = ledger.append(
        object_id=opaque(1),
        version_id=opaque(2),
        event_type="record_appended",
        ontology_version="0.1.0-rc.1",
        actor_id="test-system",
        actor_kind="system",
        recorded_at=NOW,
        payload=payload(),
        event_id=opaque(3),
    )
    second = ledger.append(
        object_id=opaque(4),
        version_id=opaque(5),
        event_type="record_appended",
        ontology_version="0.1.0-rc.1",
        actor_id="test-system",
        actor_kind="system",
        recorded_at=NOW,
        payload=payload(),
        event_id=opaque(6),
    )
    replay = ledger.replay()
    assert second["previous_event_hash"] == first["event_hash"]
    assert replay.head_hash == second["event_hash"]
    assert len(replay.events) == 2


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda data: data["payload"].update(status="supported"), "universal_status_forbidden"),
        (lambda data: data.update(execution_allowed=True), "event_execution_allowed_must_be_false"),
        (lambda data: data["payload"].update(execution_allowed=True), "payload_execution_allowed_must_be_false"),
    ],
)
def test_tampering_and_unsafe_axes_fail_closed(mutation, code):
    original = event(1)
    mutation(original)
    basis = dict(original)
    basis.pop("event_hash")
    original["event_hash"] = event_hash(basis)
    with pytest.raises(LedgerValidationError) as raised:
        encode_events([original])
    assert raised.value.code == code


def test_broken_hash_chain_detected():
    first = event(1)
    second = event(2, previous="f" * 64)
    with pytest.raises(LedgerValidationError, match="previous_event_hash_mismatch"):
        encode_events([first, second])


def test_invalid_append_leaves_ledger_byte_identical(tmp_path: Path):
    ledger = AppendOnlyLedger(tmp_path / "ledger.jsonl")
    ledger.append(
        object_id=opaque(1),
        version_id=opaque(2),
        event_type="record_appended",
        ontology_version="0.1.0-rc.1",
        actor_id="system",
        actor_kind="system",
        recorded_at=NOW,
        payload=payload(),
        event_id=opaque(3),
    )
    before = ledger.read_bytes()
    with pytest.raises(LedgerValidationError, match="version_id_reuse_forbidden"):
        ledger.append(
            object_id=opaque(4),
            version_id=opaque(2),
            event_type="record_appended",
            ontology_version="0.1.0-rc.1",
            actor_id="system",
            actor_kind="system",
            recorded_at=NOW,
            payload=payload(),
            event_id=opaque(5),
        )
    assert ledger.read_bytes() == before


def test_material_claim_change_requires_child_object(tmp_path: Path):
    ledger = AppendOnlyLedger(tmp_path / "ledger.jsonl")
    old = ClaimVersion(
        object_id=opaque(10),
        version_id=opaque(11),
        ontology_version="0.1.0-rc.1",
        claim_kind=ClaimKind.PREDICTIVE,
        proposition="Compound signal predicts relative returns.",
        scope={"geography": "US"},
        spec=predictive_spec(),
        created_at=NOW,
        created_by="analyst",
    )
    ledger.append_record(
        old,
        event_type="claim_version_appended",
        ontology_version="0.1.0-rc.1",
        actor_id="analyst",
        actor_kind="human",
        recorded_at=NOW,
        event_id=opaque(12),
    )
    changed = ClaimVersion(
        **{
            **old.to_dict(),
            "version_id": opaque(13),
            "claim_kind": ClaimKind.PREDICTIVE,
            "proposition": "A changed outcome predicts relative returns.",
        }
    )
    before = ledger.read_bytes()
    with pytest.raises(LedgerValidationError, match="material_change_requires_child_object"):
        ledger.append_record(
            changed,
            event_type="claim_version_appended",
            ontology_version="0.1.0-rc.1",
            actor_id="analyst",
            actor_kind="human",
            recorded_at=NOW,
            event_id=opaque(14),
        )
    assert ledger.read_bytes() == before


def test_replay_is_deterministic_and_bytes_are_canonical():
    first = event(1)
    second = event(2, previous=first["event_hash"])
    raw = encode_events([first, second])
    assert encode_events(replay_ledger_bytes(raw).events) == raw
    assert replay_ledger_bytes(raw) == replay_ledger_bytes(raw)


def test_agent_cannot_append_human_authority_receipt(tmp_path: Path):
    ledger = AppendOnlyLedger(tmp_path / "ledger.jsonl")
    body = {
        **payload("AxisReceipt"),
        "target_object_id": opaque(1),
        "target_version_id": opaque(2),
        "axis_name": "authority",
        "axis_value": "human_reviewed",
    }
    with pytest.raises(LedgerValidationError, match="agent_generated_human_authority_forbidden"):
        ledger.append(
            object_id=opaque(80),
            version_id=opaque(81),
            event_type="axis_receipt_appended",
            ontology_version="0.1.0-rc.1",
            actor_id="model",
            actor_kind="agent",
            recorded_at=NOW,
            payload=body,
            event_id=opaque(82),
        )
    assert not ledger.path.exists()


def test_forged_claim_fingerprint_cannot_mask_material_change(tmp_path: Path):
    ledger = AppendOnlyLedger(tmp_path / "ledger.jsonl")
    original = ClaimVersion(
        object_id=opaque(100),
        version_id=opaque(101),
        ontology_version="0.1.0-rc.1",
        claim_kind=ClaimKind.PREDICTIVE,
        proposition="The frozen target is relative return.",
        scope={"geography": "US"},
        spec=predictive_spec(),
        created_at=NOW,
        created_by="analyst",
    )
    ledger.append_record(
        original,
        event_type="claim_version_appended",
        ontology_version="0.1.0-rc.1",
        actor_id="analyst",
        actor_kind="human",
        recorded_at=NOW,
        event_id=opaque(102),
    )
    before = ledger.read_bytes()
    forged = {
        **original.to_dict(),
        "record_type": "ClaimVersion",
        "version_id": opaque(103),
        "proposition": "A materially different target is absolute return.",
        "semantic_fingerprint": original.semantic_fingerprint,
    }

    with pytest.raises(LedgerValidationError, match="claim_semantic_fingerprint_mismatch"):
        ledger.append(
            object_id=original.object_id,
            version_id=opaque(103),
            event_type="claim_version_appended",
            ontology_version="0.1.0-rc.1",
            actor_id="analyst",
            actor_kind="human",
            recorded_at=NOW,
            payload=forged,
            event_id=opaque(104),
        )

    assert ledger.read_bytes() == before


def test_retracted_lifecycle_cannot_be_resurrected_and_failed_append_is_atomic(
    tmp_path: Path,
) -> None:
    ledger = AppendOnlyLedger(tmp_path / "ledger.jsonl")
    target_object = opaque(110)
    target_version = opaque(111)
    ledger.append(
        object_id=target_object,
        version_id=target_version,
        event_type="record_appended",
        ontology_version="0.1.0-rc.1",
        actor_id="system",
        actor_kind="system",
        recorded_at=NOW,
        payload=payload(),
        event_id=opaque(112),
    )

    def receipt(value: str) -> dict:
        return {
            **payload("AxisReceipt"),
            "target_object_id": target_object,
            "target_version_id": target_version,
            "axis_name": "lifecycle",
            "axis_value": value,
            "scope": {"applies_to": "exact_version"},
        }

    ledger.append(
        object_id=opaque(113),
        version_id=opaque(114),
        event_type="axis_receipt_appended",
        ontology_version="0.1.0-rc.1",
        actor_id="system",
        actor_kind="system",
        recorded_at=NOW,
        payload=receipt("retracted"),
        event_id=opaque(115),
    )
    before = ledger.read_bytes()
    with pytest.raises(LedgerValidationError, match="lifecycle_transition_forbidden"):
        ledger.append(
            object_id=opaque(116),
            version_id=opaque(117),
            event_type="axis_receipt_appended",
            ontology_version="0.1.0-rc.1",
            actor_id="system",
            actor_kind="system",
            recorded_at=NOW,
            payload=receipt("active"),
            event_id=opaque(118),
        )
    assert ledger.read_bytes() == before


def test_lowercase_disposition_and_legacy_execution_escalation_do_not_bypass_policy():
    target = event(20)
    with pytest.raises(LedgerValidationError, match="agent_generated_human_authority_forbidden"):
        build_event(
            object_id=opaque(210),
            version_id=opaque(211),
            event_type="record_appended",
            ontology_version="0.1.0-rc.1",
            actor_id="model",
            actor_kind="agent",
            recorded_at=NOW,
            payload={
                **payload("disposition_record"),
                "target_object_id": target["object_id"],
                "target_version_id": target["version_id"],
                "reviewer_id": "model",
                "rationale": "An agent cannot fabricate this receipt.",
                "decision_at": NOW,
                "authority": "human_reviewed",
                "decision": "kept",
                "scope": {"applies_to": "exact_version"},
            },
            previous_event_hash=target["event_hash"],
            event_id=opaque(212),
        )

    with pytest.raises(LedgerValidationError, match="execution_enablement_forbidden"):
        event(
            22,
            body={
                **payload(),
                "legacy_annotations": {"execution_allowed": True},
            },
        )


def test_backdated_and_wrong_owner_receipts_fail_closed(tmp_path: Path) -> None:
    ledger = AppendOnlyLedger(tmp_path / "ledger.jsonl")
    target_object = opaque(230)
    target_version = opaque(231)
    ledger.append(
        object_id=target_object,
        version_id=target_version,
        event_type="record_appended",
        ontology_version="0.1.0-rc.1",
        actor_id="system",
        actor_kind="system",
        recorded_at=NOW,
        payload=payload(),
        event_id=opaque(232),
    )
    before = ledger.read_bytes()
    with pytest.raises(LedgerValidationError, match="recorded_at_order_invalid"):
        ledger.append(
            object_id=opaque(233),
            version_id=opaque(234),
            event_type="record_appended",
            ontology_version="0.1.0-rc.1",
            actor_id="system",
            actor_kind="system",
            recorded_at="2026-08-31T23:59:59Z",
            payload=payload(),
            event_id=opaque(235),
        )
    assert ledger.read_bytes() == before

    with pytest.raises(LedgerValidationError, match="exact_target_object_version_mismatch"):
        ledger.append(
            object_id=opaque(236),
            version_id=opaque(237),
            event_type="axis_receipt_appended",
            ontology_version="0.1.0-rc.1",
            actor_id="system",
            actor_kind="system",
            recorded_at=NOW,
            payload={
                **payload("AxisReceipt"),
                "target_object_id": opaque(999),
                "target_version_id": target_version,
                "axis_name": "evidence",
                "axis_value": "insufficient",
            },
            event_id=opaque(238),
        )
    assert ledger.read_bytes() == before


def test_axis_receipt_cannot_assert_exact_support_without_evidence_assessment():
    body = {
        **payload("AxisReceipt"),
        "target_object_id": opaque(1),
        "target_version_id": opaque(2),
        "axis_name": "evidence",
        "axis_value": "supported_in_scope",
    }
    with pytest.raises(
        LedgerValidationError,
        match="support_or_contradiction_requires_evidence_assessment",
    ):
        build_event(
            object_id=opaque(240),
            version_id=opaque(241),
            event_type="axis_receipt_appended",
            ontology_version="0.1.0-rc.1",
            actor_id="system",
            actor_kind="system",
            recorded_at=NOW,
            payload=body,
            previous_event_hash=None,
            event_id=opaque(242),
        )


def test_production_replay_enforces_release_freeze_patch_and_minor_policy() -> None:
    release_path = (
        Path(__file__).resolve().parents[2]
        / "config"
        / "research_ontology"
        / "ontology-0.1.0.json"
    )
    payload_010 = json.loads(release_path.read_text(encoding="utf-8"))

    rc = release_event(1, "0.1.0-rc.1", payload_010)
    final = release_event(2, "0.1.0", payload_010, previous=rc["event_hash"])
    assert len(replay_ledger_bytes(encode_events([rc, final])).events) == 2

    base = release_event(1, "0.1.0", payload_010)
    patch = release_event(2, "0.1.1", payload_010, previous=base["event_hash"])
    assert len(replay_ledger_bytes(encode_events([base, patch])).events) == 2

    changed_patch_payload = deepcopy(payload_010)
    changed_patch_payload["terms"][0]["definition"] += " Changed machine meaning."
    changed_patch = release_event(
        2,
        "0.1.1",
        changed_patch_payload,
        previous=base["event_hash"],
    )
    with pytest.raises(
        LedgerValidationError, match="ontology_patch_meaning_change_forbidden"
    ):
        encode_events([base, changed_patch])

    additive_minor_payload = deepcopy(payload_010)
    additive_minor_payload["terms"].append(
        {
            "term_id": opaque(590),
            "term_key": "compatible_addition",
            "term_type": "governance_marker",
            "definition": "A new compatible term with a permanent identity.",
        }
    )
    additive_minor = release_event(
        2,
        "0.2.0",
        additive_minor_payload,
        previous=base["event_hash"],
    )
    assert len(replay_ledger_bytes(encode_events([base, additive_minor])).events) == 2

    nonadditive_minor_payload = deepcopy(payload_010)
    nonadditive_minor_payload["terms"] = nonadditive_minor_payload["terms"][1:]
    nonadditive_minor = release_event(
        2,
        "0.2.0",
        nonadditive_minor_payload,
        previous=base["event_hash"],
    )
    with pytest.raises(LedgerValidationError, match="ontology_minor_must_be_additive"):
        encode_events([base, nonadditive_minor])
