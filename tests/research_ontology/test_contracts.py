from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from research_ontology import (
    Admissibility,
    ArtifactReference,
    Authority,
    AxisReceipt,
    ClaimKind,
    ClaimVersion,
    Decision,
    DispositionRecord,
    EvaluationSpec,
    Evidence,
    EvidenceAssessment,
    Freshness,
    Lifecycle,
    OntologyRelease,
    WorkflowSkillBinding,
)
from research_ontology.contracts import DERIVATION_RELATIONS, PREDICTIVE_FIELDS

from .conftest import opaque, predictive_spec


def claim(*, object_number: int = 1, version_number: int = 2, **spec_overrides) -> ClaimVersion:
    return ClaimVersion(
        object_id=opaque(object_number),
        version_id=opaque(version_number),
        ontology_version="0.1.0-rc.1",
        claim_kind=ClaimKind.PREDICTIVE,
        proposition="A compound refining condition predicts relative performance.",
        scope={"geography": "US"},
        spec=predictive_spec(**spec_overrides),
        created_at="2026-09-01T00:00:00Z",
        created_by="analyst",
    )


def derivation_rules() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "rule_id": f"{relation}_v0",
            "relation": relation,
            "version": "0.1.0",
            "source_record": "typed_record",
            "source_field": "exact_reference",
            "deterministic": True,
            "provenance_required": True,
            "semantic_authority_added": False,
            "transitive": False,
        }
        for relation in sorted(DERIVATION_RELATIONS)
    )


def ontology_release(**overrides) -> OntologyRelease:
    data = {
        "release_id": opaque(50),
        "version": "0.1.0",
        "released_at": "2026-09-01T00:00:00Z",
        "terms": (
            {
                "term_id": opaque(51),
                "term_key": "claim_version",
                "definition": "An immutable claim version.",
            },
        ),
        "derivation_rules": derivation_rules(),
        "lifecycle_values": tuple(value.value for value in Lifecycle),
        "evidence_values": tuple(value.value for value in Evidence),
        "authority_values": tuple(value.value for value in Authority),
        "decision_values": tuple(value.value for value in Decision),
        "freshness_values": tuple(value.value for value in Freshness),
        "admissibility_values": tuple(value.value for value in Admissibility),
    }
    data.update(overrides)
    return OntologyRelease(**data)


def test_predictive_claim_requires_every_individually_planned_field():
    record = claim()
    assert tuple(record.spec) == PREDICTIVE_FIELDS
    assert all(set(record.spec[name]) >= {"field_name", "state", "value"} for name in PREDICTIVE_FIELDS)
    with pytest.raises(ValueError, match="claim_spec_fields_missing:expiry"):
        spec = predictive_spec()
        spec.pop("expiry")
        ClaimVersion(
            object_id=opaque(3),
            version_id=opaque(4),
            ontology_version="0.1.0-rc.1",
            claim_kind=ClaimKind.PREDICTIVE,
            proposition="Missing expiry is not a complete predictive claim.",
            scope={"geography": "US"},
            spec=spec,
            created_at="2026-09-01T00:00:00Z",
            created_by="analyst",
        )


def test_contracts_are_frozen_and_boundaries_fail_closed():
    record = claim()
    with pytest.raises(FrozenInstanceError):
        record.proposition = "rewritten"  # type: ignore[misc]
    with pytest.raises(ValueError, match="execution_allowed_must_be_false"):
        ClaimVersion(
            **{**record.to_dict(), "claim_kind": ClaimKind.PREDICTIVE, "execution_allowed": True}
        )
    with pytest.raises(ValueError, match="must_be_uuid4"):
        ClaimVersion(
            **{
                **record.to_dict(),
                "object_id": "urn:portfolio-research:00000000-0000-0000-0000-000000000001",
                "claim_kind": ClaimKind.PREDICTIVE,
            }
        )


def test_contracts_defensively_deep_freeze_caller_owned_mappings():
    scope = {"geography": "US", "nested": {"regimes": ["base"]}}
    spec = predictive_spec()
    record = ClaimVersion(
        object_id=opaque(6),
        version_id=opaque(7),
        ontology_version="0.1.0-rc.1",
        claim_kind=ClaimKind.PREDICTIVE,
        proposition="Caller-owned containers cannot rewrite an immutable version.",
        scope=scope,
        spec=spec,
        created_at="2026-09-01T00:00:00Z",
        created_by="analyst",
    )
    fingerprint = record.semantic_fingerprint

    scope["nested"]["regimes"].append("stress")
    spec["target"]["value"] = "rewritten"

    assert record.scope["nested"]["regimes"] == ("base",)
    assert record.spec["target"]["value"] == "relative return"
    assert record.semantic_fingerprint == fingerprint
    with pytest.raises(TypeError):
        record.scope["geography"] = "EU"  # type: ignore[index]


def test_artifact_requires_all_admissibility_sections_and_reproducible_hash_is_explicit():
    artifact = ArtifactReference(
        object_id=opaque(10),
        version_id=opaque(11),
        artifact_type="dataset_snapshot",
        uri="artifact://snapshot",
        sha256=None,
        source_identity={"publisher": "example"},
        timing={"first_public_at": "2026-01-01T00:00:00Z"},
        rights={"research_use": True},
        scope={"universe": "US"},
        revision={"policy": "vintage_frozen"},
        missingness={"no_event": "explicit"},
    )
    assert artifact.sha256 is None
    with pytest.raises(ValueError, match="artifact_rights_must_be_nonempty_mapping"):
        ArtifactReference(**{**artifact.to_dict(), "rights": {}})


def test_data_blockage_is_a_distinct_evidence_value():
    assessment = EvidenceAssessment(
        object_id=opaque(20),
        version_id=opaque(21),
        claim_version_id=opaque(2),
        evidence=Evidence.BLOCKED_BY_DATA,
        admissibility=Admissibility.BLOCKED,
        freshness=Freshness.UNKNOWN,
        scope={"test": "exact"},
        rationale="Required historical release timestamps are unavailable.",
        artifact_refs=(),
        assessed_at="2026-09-01T00:00:00Z",
        assessed_by="migration",
    )
    assert assessment.evidence.value == "blocked_by_data"
    with pytest.raises(ValueError, match="freshness_axis_invalid"):
        EvidenceAssessment(
            **{
                **assessment.to_dict(),
                "evidence": Evidence.BLOCKED_BY_DATA,
                "admissibility": Admissibility.BLOCKED,
                "freshness": "unknown",
            }
        )


def test_llm_judge_can_never_be_authoritative():
    with pytest.raises(ValueError, match="llm_judge_must_not_be_authoritative"):
        EvaluationSpec(
            evaluation_id=opaque(30),
            version_id=opaque(31),
            deterministic_checks=("schema",),
            rubric={"clarity": 1},
            thresholds={"minimum": 1},
            holdout_refs=("fixture",),
            max_iterations=2,
            llm_judge_authoritative=True,
        )


def test_skill_binding_is_content_hash_bound():
    binding = WorkflowSkillBinding(
        skill_id="governed-research-workflow",
        skill_version="0.1.0",
        skill_path="research_ontology/skills/governed-research-workflow/SKILL.md",
        skill_sha256="a" * 64,
        allowed_stages=("plan", "verify"),
    )
    assert binding.skill_sha256 == "a" * 64


def test_axis_receipts_are_exact_and_never_a_universal_status():
    receipt = AxisReceipt(
        object_id=opaque(40),
        version_id=opaque(41),
        target_object_id=opaque(1),
        target_version_id=opaque(2),
        axis_name="lifecycle",
        axis_value="active",
        rationale="Initial imported lifecycle receipt.",
        recorded_at="2026-09-01T00:00:00Z",
        recorded_by="migration",
        effective_at="2026-09-01T00:00:00Z",
        scope={"applies_to": "exact_version"},
    )
    assert "status" not in receipt.to_dict()
    with pytest.raises(ValueError, match="axis_receipt_scope_wildcards_forbidden"):
        AxisReceipt(**{**receipt.to_dict(), "scope": {"applies_to": "*"}})


def test_disposition_requires_an_exact_nonpending_decision_enum_member():
    data = {
        "object_id": opaque(60),
        "version_id": opaque(61),
        "target_object_id": opaque(1),
        "target_version_id": opaque(2),
        "reviewer_id": "reviewer@example.test",
        "rationale": "Exact claim version was reviewed in the declared scope.",
        "decision": Decision.KEPT,
        "decision_at": "2026-09-01T00:00:00Z",
        "scope": {"applies_to": "exact_version"},
    }
    assert DispositionRecord(**data).decision is Decision.KEPT
    with pytest.raises(ValueError, match="disposition_decision_axis_invalid"):
        DispositionRecord(**{**data, "version_id": opaque(62), "decision": "kept"})
    with pytest.raises(ValueError, match="human_disposition_cannot_be_pending"):
        DispositionRecord(**{**data, "version_id": opaque(63), "decision": Decision.PENDING})


def test_ontology_release_registers_exact_safe_derivation_whitelist():
    release = ontology_release()
    assert {rule["relation"] for rule in release.derivation_rules} == DERIVATION_RELATIONS

    non_deterministic = [dict(rule) for rule in derivation_rules()]
    non_deterministic[0]["deterministic"] = False
    with pytest.raises(ValueError, match="derivation_rule_must_be_deterministic"):
        ontology_release(derivation_rules=tuple(non_deterministic))

    duplicate_id = [dict(rule) for rule in derivation_rules()]
    duplicate_id[1]["rule_id"] = duplicate_id[0]["rule_id"]
    with pytest.raises(ValueError, match="ontology_derivation_rule_ids_must_be_unique"):
        ontology_release(derivation_rules=tuple(duplicate_id))

    bare_causal = [dict(rule) for rule in derivation_rules()]
    bare_causal[0]["relation"] = "causes"
    with pytest.raises(ValueError, match="ontology_derivation_relation_not_whitelisted"):
        ontology_release(derivation_rules=tuple(bare_causal))

    unstable_id = [dict(rule) for rule in derivation_rules()]
    unstable_id[0]["rule_id"] = "temporary-rule"
    with pytest.raises(ValueError, match="derivation_rule_id_must_be_stable"):
        ontology_release(derivation_rules=tuple(unstable_id))
