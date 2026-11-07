from __future__ import annotations

from dataclasses import replace

import pytest

from research_ontology import (
    Admissibility,
    ArtifactReference,
    ClaimKind,
    ClaimVersion,
    Evidence,
    Lifecycle,
    ProxyBinding,
)
from research_ontology.policy import (
    PolicyError,
    assess_artifact_admissibility,
    classify_claim_change,
    gate_proxy_use,
    validate_evidence_assessment,
    validate_inference,
    validate_lifecycle_transition,
    validate_no_universal_status,
)

from .conftest import opaque, predictive_spec


def make_claim(object_number: int, version_number: int, **overrides) -> ClaimVersion:
    data = dict(
        object_id=opaque(object_number),
        version_id=opaque(version_number),
        ontology_version="0.1.0-rc.1",
        claim_kind=ClaimKind.PREDICTIVE,
        proposition="Compound refining condition predicts relative performance.",
        scope={"geography": "US"},
        spec=predictive_spec(),
        created_at="2026-09-01T00:00:00Z",
        created_by="analyst",
    )
    data.update(overrides)
    return ClaimVersion(**data)


def test_metadata_only_version_retains_semantic_fingerprint():
    old = make_claim(1, 2)
    new = replace(old, version_id=opaque(3), created_by="metadata-corrector")
    result = classify_claim_change(old, new)
    assert result.outcome == "metadata_version_allowed"
    assert result.changed_fields == ()


@pytest.mark.parametrize("field", ["target", "universe", "horizon", "baseline", "metric", "controls"])
def test_material_changes_cannot_be_an_ordinary_version(field):
    old = make_claim(10, 11)
    spec = predictive_spec()
    spec[field] = {**spec[field], "value": f"changed-{field}"}
    new = replace(old, version_id=opaque(12), spec=spec)
    with pytest.raises(PolicyError) as raised:
        classify_claim_change(old, new)
    assert raised.value.code == "new_child_or_hypothesis_required"


def test_lifecycle_is_one_way_for_old_version():
    validate_lifecycle_transition(Lifecycle.ACTIVE, Lifecycle.RETRACTED)
    with pytest.raises(PolicyError, match="lifecycle_transition_forbidden"):
        validate_lifecycle_transition(Lifecycle.RETRACTED, Lifecycle.ACTIVE)


def test_universal_status_rejected_but_opaque_legacy_annotation_preserved():
    with pytest.raises(PolicyError, match="universal_status_forbidden"):
        validate_no_universal_status({"status": "supported"})
    validate_no_universal_status({"legacy_annotations": {"status": "supported"}})


def test_proxy_gate_preapproves_only_registered_bounded_use():
    binding = ProxyBinding(
        object_id=opaque(20),
        version_id=opaque(21),
        proxy_variable_id=opaque(22),
        construct_id=opaque(23),
        permitted_uses=("context", "control"),
        scope={"geography": "US"},
        limitations=("Not an outcome substitute",),
        validation_artifact_refs=(),
        expires_at="2027-01-01T00:00:00Z",
        created_at="2026-09-01T00:00:00Z",
        created_by="analyst",
    )
    assert gate_proxy_use(
        binding,
        requested_use="context",
        as_of="2026-10-01T00:00:00Z",
        requested_scope={"geography": "US"},
        registered_bindings={binding.object_id: binding.version_id},
    ).outcome == "preapproved"
    assert gate_proxy_use(
        binding,
        requested_use="target",
        as_of="2026-10-01T00:00:00Z",
        requested_scope={"geography": "US"},
    ).outcome == "review_required"

    assert gate_proxy_use(
        binding,
        requested_use="context",
        as_of="2026-10-01T00:00:00Z",
        requested_scope={"geography": "US"},
    ).reason == "proxy_binding_not_registered"
    assert gate_proxy_use(
        binding,
        requested_use="context",
        as_of="2026-10-01T00:00:00Z",
        requested_scope={},
        registered_bindings={binding.object_id: binding.version_id},
    ).reason == "proxy_requested_scope_required"
    assert gate_proxy_use(
        binding,
        requested_use="context",
        as_of="2026-10-01T00:00:00Z",
        requested_scope={"geography": "US", "sector": "energy"},
        registered_bindings={binding.object_id: binding.version_id},
    ).reason == "proxy_scope_mismatch"
    assert gate_proxy_use(
        binding,
        requested_use="context",
        as_of=binding.expires_at,
        requested_scope={"geography": "US"},
        registered_bindings={binding.object_id: binding.version_id},
    ).reason == "proxy_binding_expired"

    with pytest.raises(ValueError, match="proxy_scope_must_be_bounded_without_wildcards"):
        replace(binding, version_id=opaque(24), scope={"geography": "*"})


def test_inference_is_default_deny_and_provenance_complete():
    registered_rule = {
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
    with pytest.raises(PolicyError, match="inference_relation_default_denied"):
        validate_inference(
            relation="causes",
            rule_id="r",
            rule_version="0.1.0",
            deterministic=True,
            source_ids=(opaque(1),),
            target_ids=(opaque(2),),
            input_sha256="a" * 64,
            output_sha256="b" * 64,
            implementation_sha256="c" * 64,
            registered_rules=(registered_rule,),
        )
    with pytest.raises(PolicyError, match="inference_rule_registry_required"):
        validate_inference(
            relation="version_of",
            rule_id="version_identity_v0",
            rule_version="0.1.0",
            deterministic=True,
            source_ids=(opaque(2),),
            target_ids=(opaque(1),),
            input_sha256="a" * 64,
            output_sha256="b" * 64,
            implementation_sha256="c" * 64,
        )
    with pytest.raises(PolicyError, match="inference_rule_not_registered"):
        validate_inference(
            relation="version_of",
            rule_id="different_rule_v0",
            rule_version="0.1.0",
            deterministic=True,
            source_ids=(opaque(2),),
            target_ids=(opaque(1),),
            input_sha256="a" * 64,
            output_sha256="b" * 64,
            implementation_sha256="c" * 64,
            registered_rules=(registered_rule,),
        )
    receipt = validate_inference(
        relation="version_of",
        rule_id="version_identity_v0",
        rule_version="0.1.0",
        deterministic=True,
        source_ids=(opaque(2),),
        target_ids=(opaque(1),),
        input_sha256="a" * 64,
        output_sha256="b" * 64,
        implementation_sha256="c" * 64,
        registered_rules=(registered_rule,),
    )
    assert receipt.relation == "version_of"


def test_blockage_cannot_be_contradiction_and_admissibility_is_independent():
    validate_evidence_assessment(
        evidence=Evidence.BLOCKED_BY_DATA, admissibility=Admissibility.BLOCKED
    )
    with pytest.raises(PolicyError, match="blocked_admissibility_is_not_negative_evidence"):
        validate_evidence_assessment(
            evidence=Evidence.CONTRADICTED_IN_SCOPE, admissibility=Admissibility.BLOCKED
        )


def test_artifact_admissibility_requires_reproducible_hash_and_metadata():
    artifact = ArtifactReference(
        object_id=opaque(30),
        version_id=opaque(31),
        artifact_type="dataset",
        uri="artifact://x",
        sha256=None,
        source_identity={"publisher": "x"},
        timing={"released_at": "2026-01-01T00:00:00Z"},
        rights={"research_use": True},
        scope={"universe": "US"},
        revision={"policy": "frozen"},
        missingness={"meaning": "explicit"},
    )
    result, missing = assess_artifact_admissibility(artifact)
    assert result == Admissibility.INADMISSIBLE
    assert "reproducible_artifact_hash" in missing


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"rights": {"research_use": False}}, "rights_denied"),
        ({"timing": {"released_at": "2026-01-01T00:00:00"}}, "timing_invalid_or_timezone_missing"),
        ({"timing": {"calendar": "daily"}}, "timing_semantics"),
        ({"revision": {"owner": "publisher"}}, "revision_semantics"),
        ({"missingness": {"owner": "publisher"}}, "missingness_semantics"),
    ],
)
def test_artifact_admissibility_rejects_denied_or_incomplete_semantics(overrides, expected_reason):
    data = {
        "object_id": opaque(40),
        "version_id": opaque(41),
        "artifact_type": "dataset",
        "uri": "artifact://complete",
        "sha256": "d" * 64,
        "source_identity": {"publisher": "x", "dataset": "y"},
        "timing": {"released_at": "2026-01-01T00:00:00Z"},
        "rights": {"research_use": True},
        "scope": {"universe": "US"},
        "revision": {"policy": "vintage_frozen"},
        "missingness": {"meaning": "missing means no published observation"},
    }
    data.update(overrides)
    result, reasons = assess_artifact_admissibility(ArtifactReference(**data))
    assert result == Admissibility.INADMISSIBLE
    assert expected_reason in reasons


def test_artifact_is_admissible_only_with_complete_typed_semantics():
    artifact = ArtifactReference(
        object_id=opaque(50),
        version_id=opaque(51),
        artifact_type="dataset",
        uri="artifact://complete",
        sha256="e" * 64,
        source_identity={"publisher": "x", "dataset": "y"},
        timing={"first_public_at": "2026-01-01T00:00:00Z"},
        rights={"research_use": True},
        scope={"universe": "US"},
        revision={"policy": "vintage_frozen"},
        missingness={"no_event": "explicit_null"},
    )
    assert assess_artifact_admissibility(artifact) == (Admissibility.ADMISSIBLE, ())
