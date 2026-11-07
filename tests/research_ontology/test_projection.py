from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research_ontology.contracts import canonical_json, canonical_sha256
from research_ontology.ledger import build_event
from research_ontology.policy import DERIVATION_RELATIONS
from research_ontology.projection import build_graph_projection, build_tier1_context

from .conftest import opaque


FIXTURE = Path(__file__).parent / "fixtures" / "projection_events.json"
PARENT_VERSION_ID = "urn:portfolio-research:00000000-0000-0000-0000-000000000101"
CHILD_VERSION_ID = "urn:portfolio-research:00000000-0000-0000-0000-000000000102"
REGISTERED_DERIVATION_RULES = {
    "version_of": ("version_identity_v0", "0.1.0"),
    "parent_of": ("parent_reference_v0", "0.1.0"),
    "instantiates": ("claim_instantiation_v0", "0.1.0"),
    "assesses": ("assessment_target_v0", "0.1.0"),
    "references_artifact": ("artifact_reference_v0", "0.1.0"),
    "derived_from": ("projection_provenance_v0", "0.1.0"),
    "supersedes": ("version_supersession_v0", "0.1.0"),
}


@pytest.fixture
def replayed_events() -> list[dict[str, object]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _node(projection: dict[str, object], node_id: str) -> dict[str, object]:
    return next(node for node in projection["nodes"] if node["node_id"] == node_id)


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def test_projection_emits_only_versioned_whitelisted_structural_edges(
    replayed_events: list[dict[str, object]],
) -> None:
    projection = build_graph_projection(replayed_events, as_of="2026-01-06T00:00:00Z")

    assert projection["research_only"] is True
    assert projection["execution_allowed"] is False
    assert {edge["relation"] for edge in projection["edges"]} <= DERIVATION_RELATIONS
    assert all(edge["relation_version"] for edge in projection["edges"])
    assert all(edge["rule_id"] for edge in projection["edges"])
    assert all(edge["deterministic"] is True for edge in projection["edges"])
    assert all(edge["provenance_refs"] for edge in projection["edges"])
    assert all(edge["source_event_ids"] for edge in projection["edges"])
    assert all(
        REGISTERED_DERIVATION_RULES[edge["relation"]]
        == (edge["rule_id"], edge["relation_version"])
        for edge in projection["edges"]
    )
    assert not (
        {"predicts", "causes", "supports", "contradicts", "proxy_for", "same_as"}
        & {edge["relation"] for edge in projection["edges"]}
    )
    assert {item.get("relation") for item in projection["excluded_relations"]} == {
        "predicts",
        "same_as",
        "derived_from",
    }
    assert any(
        edge["relation"] == "parent_of"
        and edge["target_id"]
        == "urn:portfolio-research:00000000-0000-0000-0000-000000000002"
        for edge in projection["edges"]
    )

    core = {key: value for key, value in projection.items() if key != "projection_sha256"}
    assert projection["projection_sha256"] == canonical_sha256(
        "research_graph_projection_v0", core
    )


def test_current_axes_are_independent_exact_target_and_freshness_is_as_of(
    replayed_events: list[dict[str, object]],
) -> None:
    projection = build_graph_projection(replayed_events, as_of="2026-01-06T00:00:00Z")
    parent = _node(projection, PARENT_VERSION_ID)
    child = _node(projection, CHILD_VERSION_ID)

    assert parent["axes"] == {
        "lifecycle": "active",
        "evidence": "untested",
        "authority": "agent_proposed",
        "decision": "pending",
        "freshness": "unknown",
        "admissibility": None,
    }
    assert child["axes"] == {
        "lifecycle": "active",
        "evidence": "contradicted_in_scope",
        "authority": "agent_proposed",
        "decision": "pending",
        "freshness": "current",
        "admissibility": "admissible",
    }
    assert child["blockers"][0]["code"] == "unresolved_ambiguity"
    assert child["contradictions"][0]["code"] == "contradicted_in_scope"
    assert parent["blockers"] == []
    assert parent["contradictions"] == []

    before_expiry = build_graph_projection(replayed_events, as_of="2026-01-04T12:00:00Z")
    assert _node(before_expiry, CHILD_VERSION_ID)["axes"]["freshness"] == "current"

    after_future_assessment = build_graph_projection(
        replayed_events, as_of="2026-02-02T00:00:00Z"
    )
    later_child = _node(after_future_assessment, CHILD_VERSION_ID)
    assert later_child["axes"]["evidence"] == "supported_in_scope"
    assert later_child["axes"]["decision"] == "pending"
    assert later_child["axes"]["freshness"] == "current"


def test_tier1_context_is_bounded_allowlisted_and_recursively_sanitized(
    replayed_events: list[dict[str, object]],
) -> None:
    context = build_tier1_context(
        replayed_events,
        as_of="2026-01-06T00:00:00Z",
        max_records=2,
        max_bytes=4096,
    )

    assert context["record_count"] <= 2
    assert context["truncated"] is True
    assert len(canonical_json(context).encode("utf-8")) <= 4096
    assert context["execution_allowed"] is False
    assert CHILD_VERSION_ID in {record["record_id"] for record in context["records"]}

    forbidden = {
        "raw_body",
        "logs",
        "sample_rows",
        "secrets",
        "secret_token",
        "broker_state",
        "positions",
        "hidden_reasoning",
    }
    assert not (forbidden & _all_keys(context))
    for record in context["records"]:
        assert {
            "record_id",
            "object_id",
            "version_id",
            "ids",
            "record_type",
            "kind",
            "axes",
            "scope",
            "freshness",
            "blockers",
            "contradictions",
            "caveats",
            "artifact_refs",
        } <= set(record)

    core = {key: value for key, value in context.items() if key != "context_sha256"}
    assert context["context_sha256"] == canonical_sha256("tier1_context_v0", core)


def test_projection_and_context_are_invariant_to_logically_unordered_input(
    replayed_events: list[dict[str, object]],
) -> None:
    reversed_events = list(reversed(replayed_events))
    reordered_nested = copy.deepcopy(reversed_events)
    child_event = next(event for event in reordered_nested if event["event_id"] == "evt-child-claim")
    child_event["payload"]["relations"].reverse()

    projection_a = build_graph_projection(replayed_events, as_of="2026-01-06T00:00:00Z")
    projection_b = build_graph_projection(reversed_events, as_of="2026-01-06T00:00:00Z")
    projection_c = build_graph_projection(reordered_nested, as_of="2026-01-06T00:00:00Z")
    assert projection_a == projection_b
    assert projection_a == projection_c
    assert projection_a["projection_sha256"] == projection_b["projection_sha256"]

    context_a = build_tier1_context(replayed_events, as_of="2026-01-06T00:00:00Z")
    context_b = build_tier1_context(reversed_events, as_of="2026-01-06T00:00:00Z")
    assert context_a == context_b
    assert context_a["context_sha256"] == context_b["context_sha256"]


def test_conflicting_duplicate_event_or_version_identity_fails_closed(
    replayed_events: list[dict[str, object]],
) -> None:
    event_conflict = copy.deepcopy(replayed_events[0])
    event_conflict["payload"]["claim_kind"] = "association"
    with pytest.raises(ValueError, match="projection_event_id_conflict"):
        build_graph_projection(
            [replayed_events[0], event_conflict], as_of="2026-01-06T00:00:00Z"
        )

    version_conflict = copy.deepcopy(replayed_events[0])
    version_conflict["event_id"] = "evt-conflicting-version"
    version_conflict["recorded_at"] = "2026-01-01T01:00:00Z"
    version_conflict["payload"]["claim_kind"] = "association"
    with pytest.raises(ValueError, match="projection_version_id_conflict"):
        build_graph_projection(
            [replayed_events[0], version_conflict], as_of="2026-01-06T00:00:00Z"
        )


def test_axis_receipt_uses_exact_target_and_envelope_identity() -> None:
    claim_object = "urn:portfolio-research:00000000-0000-0000-0000-000000000501"
    claim_version = "urn:portfolio-research:00000000-0000-0000-0000-000000000502"
    receipt_object = "urn:portfolio-research:00000000-0000-0000-0000-000000000503"
    receipt_version = "urn:portfolio-research:00000000-0000-0000-0000-000000000504"
    events = [
        {
            "event_id": "evt-axis-target",
            "event_type": "claim_version_appended",
            "object_id": claim_object,
            "version_id": claim_version,
            "ontology_version": "1.0.0",
            "recorded_at": "2026-01-01T00:00:00Z",
            "payload": {
                "record_type": "ClaimVersion",
                "claim_kind": "structural",
                "scope": {"universe": "fixture"},
                "research_only": True,
                "execution_allowed": False,
            },
        },
        {
            "event_id": "evt-axis-receipt",
            "event_type": "axis_receipt_appended",
            "object_id": receipt_object,
            "version_id": receipt_version,
            "ontology_version": "1.0.0",
            "recorded_at": "2026-01-02T00:00:00Z",
            "payload": {
                "record_type": "AxisReceipt",
                "target_object_id": claim_object,
                "target_version_id": claim_version,
                "axis_name": "evidence",
                "axis_value": "insufficient",
                "research_only": True,
                "execution_allowed": False,
            },
        },
    ]

    projection = build_graph_projection(events, as_of="2026-01-03T00:00:00Z")

    assert _node(projection, claim_version)["axes"]["evidence"] == "insufficient"
    receipt = _node(projection, receipt_version)
    assert receipt["object_id"] == receipt_object
    assert receipt["version_id"] == receipt_version

    wrong_owner = copy.deepcopy(events)
    wrong_owner[1]["payload"]["target_object_id"] = opaque(509)
    with pytest.raises(
        ValueError, match="projection_exact_target_object_version_mismatch"
    ):
        build_graph_projection(wrong_owner, as_of="2026-01-03T00:00:00Z")

    missing_target = copy.deepcopy(events)
    missing_target[1]["payload"]["target_version_id"] = opaque(508)
    with pytest.raises(ValueError, match="projection_exact_target_version_not_found"):
        build_graph_projection(missing_target, as_of="2026-01-03T00:00:00Z")


def test_ontology_release_preserves_explicit_envelope_identity() -> None:
    release_object = opaque(530)
    release_version = opaque(531)
    event = {
        "event_id": "evt-release-envelope-identity",
        "event_type": "ontology_release_appended",
        "object_id": release_object,
        "version_id": release_version,
        "ontology_version": "0.1.0",
        "recorded_at": "2026-01-01T00:00:00Z",
        "payload": {
            "record_type": "OntologyRelease",
            "release_id": release_object,
            "version": "0.1.0",
            "released_at": "2026-01-01T00:00:00Z",
            "research_only": True,
            "execution_allowed": False,
        },
    }

    projection = build_graph_projection([event], as_of="2026-01-02T00:00:00Z")

    release = _node(projection, release_version)
    assert release["object_id"] == release_object
    assert release["version_id"] == release_version
    assert release["ids"]["release_id"] == release_object


def test_future_effective_and_expired_receipts_do_not_govern_as_of() -> None:
    claim_object = opaque(540)
    claim_version = opaque(541)
    events = [
        {
            "event_id": "evt-temporal-claim",
            "event_type": "claim_version_appended",
            "object_id": claim_object,
            "version_id": claim_version,
            "ontology_version": "0.1.0",
            "recorded_at": "2026-01-01T00:00:00Z",
            "payload": {
                "record_type": "ClaimVersion",
                "claim_kind": "structural",
                "scope": {"universe": "fixture"},
                "research_only": True,
                "execution_allowed": False,
            },
        },
        {
            "event_id": "evt-active-receipt",
            "event_type": "axis_receipt_appended",
            "object_id": opaque(542),
            "version_id": opaque(543),
            "ontology_version": "0.1.0",
            "recorded_at": "2026-01-02T00:00:00Z",
            "payload": {
                "record_type": "AxisReceipt",
                "target_object_id": claim_object,
                "target_version_id": claim_version,
                "axis_name": "evidence",
                "axis_value": "insufficient",
                "effective_at": "2026-01-02T00:00:00Z",
                "expires_at": "2026-01-20T00:00:00Z",
                "research_only": True,
                "execution_allowed": False,
            },
        },
        {
            "event_id": "evt-expired-receipt",
            "event_type": "axis_receipt_appended",
            "object_id": opaque(544),
            "version_id": opaque(545),
            "ontology_version": "0.1.0",
            "recorded_at": "2026-01-03T00:00:00Z",
            "payload": {
                "record_type": "AxisReceipt",
                "target_object_id": claim_object,
                "target_version_id": claim_version,
                "axis_name": "evidence",
                "axis_value": "mixed",
                "effective_at": "2026-01-03T00:00:00Z",
                "expires_at": "2026-01-05T00:00:00Z",
                "research_only": True,
                "execution_allowed": False,
            },
        },
        {
            "event_id": "evt-future-effective-receipt",
            "event_type": "axis_receipt_appended",
            "object_id": opaque(546),
            "version_id": opaque(547),
            "ontology_version": "0.1.0",
            "recorded_at": "2026-01-04T00:00:00Z",
            "payload": {
                "record_type": "AxisReceipt",
                "target_object_id": claim_object,
                "target_version_id": claim_version,
                "axis_name": "evidence",
                "axis_value": "contradicted_in_scope",
                "effective_at": "2026-02-01T00:00:00Z",
                "research_only": True,
                "execution_allowed": False,
            },
        },
    ]

    projection = build_graph_projection(events, as_of="2026-01-10T00:00:00Z")

    claim = _node(projection, claim_version)
    assert claim["axes"]["evidence"] == "insufficient"
    assert claim["axis_provenance"]["evidence"]["event_id"] == "evt-active-receipt"


def test_explicit_edges_require_registered_rule_relation_and_version() -> None:
    event = {
        "event_id": "evt-explicit-rules",
        "event_type": "claim_version_appended",
        "object_id": opaque(550),
        "version_id": opaque(551),
        "ontology_version": "0.1.0",
        "recorded_at": "2026-01-01T00:00:00Z",
        "payload": {
            "record_type": "ClaimVersion",
            "claim_kind": "structural",
            "scope": {"universe": "fixture"},
            "relations": [
                {
                    "relation": "derived_from",
                    "source_id": opaque(551),
                    "target_id": opaque(552),
                    "relation_version": "0.1.0",
                    "rule_id": "projection_provenance_v0",
                    "deterministic": True,
                    "provenance_refs": ["evt-source"],
                },
                {
                    "relation": "derived_from",
                    "source_id": opaque(551),
                    "target_id": opaque(553),
                    "relation_version": "0.1.0",
                    "rule_id": "unregistered-rule",
                    "deterministic": True,
                    "provenance_refs": ["evt-source"],
                },
            ],
            "research_only": True,
            "execution_allowed": False,
        },
    }

    projection = build_graph_projection([event], as_of="2026-01-02T00:00:00Z")

    assert any(
        edge["relation"] == "derived_from"
        and edge["rule_id"] == "projection_provenance_v0"
        and edge["target_id"] == opaque(552)
        for edge in projection["edges"]
    )
    assert not any(edge["target_id"] == opaque(553) for edge in projection["edges"])
    assert any(
        excluded["reason"] == "relation_rule_not_registered"
        for excluded in projection["excluded_relations"]
    )


def test_tier1_uses_positive_allowlists_for_nested_context_data(
    replayed_events: list[dict[str, object]],
) -> None:
    events = copy.deepcopy(replayed_events)
    child_event = next(event for event in events if event["event_id"] == "evt-child-claim")
    child_event["payload"]["scope"]["document"] = {
        "text": "raw body hidden behind innocuous keys"
    }
    child_event["payload"]["caveats"] = [
        {
            "code": "bounded_scope",
            "message": "Safe context metadata.",
            "document": {"text": "secret caveat body"},
        }
    ]
    child_event["payload"]["artifact_refs"].append(
        {
            "object_id": opaque(560),
            "content_sha256": "a" * 64,
            "document": {"text": "raw artifact body"},
        }
    )

    context = build_tier1_context(events, as_of="2026-01-06T00:00:00Z")
    child = next(
        record for record in context["records"] if record["record_id"] == CHILD_VERSION_ID
    )

    assert child["scope"]["geography"] == "USGC"
    assert child["caveats"] == [
        {"code": "bounded_scope", "message": "Safe context metadata."}
    ]
    assert {
        "object_id": opaque(560),
        "content_sha256": "a" * 64,
    } in child["artifact_refs"]
    assert "document" not in _all_keys(child)
    assert "text" not in _all_keys(child)


def test_same_timestamp_receipts_follow_hash_chain_order_when_input_is_shuffled() -> None:
    recorded_at = "2026-01-01T00:00:00Z"
    claim_object = opaque(600)
    claim_version = opaque(601)
    claim = build_event(
        object_id=claim_object,
        version_id=claim_version,
        event_type="claim_version_appended",
        ontology_version="0.1.0",
        actor_id="test-system",
        actor_kind="system",
        recorded_at=recorded_at,
        payload={
            "record_type": "TestRecord",
            "research_only": True,
            "execution_allowed": False,
        },
        previous_event_hash=None,
        event_id=opaque(602),
    )
    first_receipt = build_event(
        object_id=opaque(610),
        version_id=opaque(611),
        event_type="axis_receipt_appended",
        ontology_version="0.1.0",
        actor_id="test-system",
        actor_kind="system",
        recorded_at=recorded_at,
        payload={
            "record_type": "AxisReceipt",
            "target_object_id": claim_object,
            "target_version_id": claim_version,
            "axis_name": "evidence",
            "axis_value": "insufficient",
            "research_only": True,
            "execution_allowed": False,
        },
        previous_event_hash=claim["event_hash"],
        event_id=opaque(999),
    )
    last_receipt = build_event(
        object_id=opaque(620),
        version_id=opaque(621),
        event_type="axis_receipt_appended",
        ontology_version="0.1.0",
        actor_id="test-system",
        actor_kind="system",
        recorded_at=recorded_at,
        payload={
            "record_type": "AxisReceipt",
            "target_object_id": claim_object,
            "target_version_id": claim_version,
            "axis_name": "evidence",
            "axis_value": "mixed",
            "research_only": True,
            "execution_allowed": False,
        },
        previous_event_hash=first_receipt["event_hash"],
        event_id=opaque(1),
    )

    ordered = build_graph_projection(
        [claim, first_receipt, last_receipt], as_of="2026-01-02T00:00:00Z"
    )
    shuffled = build_graph_projection(
        [last_receipt, claim, first_receipt], as_of="2026-01-02T00:00:00Z"
    )

    assert ordered == shuffled
    assert _node(ordered, claim_version)["axes"]["evidence"] == "mixed"


def test_tier1_rejects_limits_above_the_governed_caps(
    replayed_events: list[dict[str, object]],
) -> None:
    with pytest.raises(ValueError, match="tier1_max_records"):
        build_tier1_context(
            replayed_events, as_of="2026-01-06T00:00:00Z", max_records=51
        )
    with pytest.raises(ValueError, match="tier1_max_bytes"):
        build_tier1_context(
            replayed_events, as_of="2026-01-06T00:00:00Z", max_bytes=65_537
        )
