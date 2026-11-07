"""Fail-closed semantic policy for Portfolio research ontology records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from .contracts import (
    Admissibility,
    ArtifactReference,
    Authority,
    ClaimVersion,
    DERIVATION_RELATIONS as CONTRACT_DERIVATION_RELATIONS,
    DispositionRecord,
    Evidence,
    Lifecycle,
    ProxyBinding,
    PROXY_USES,
    STABLE_DERIVATION_RULE_ID_RE,
    canonical_sha256,
    is_bounded_scope,
    require_iso,
    require_semver,
    require_sha256,
    require_text,
)


DERIVATION_RELATIONS = CONTRACT_DERIVATION_RELATIONS
FORBIDDEN_BARE_RELATIONS = frozenset(
    {
        "predicts",
        "causes",
        "supports",
        "contradicts",
        "proxy_for",
        "same_as",
        "equivalent_to",
        "equivalence",
        "approved",
        "approval",
        "authority",
        "execution_allowed",
    }
)
MATERIAL_SPEC_FIELDS = frozenset(
    {
        "target",
        "forecast_origin",
        "information_cutoff",
        "horizon",
        "universe",
        "benchmark",
        "baseline",
        "feature_proxy_refs",
        "metric",
        "success_thresholds",
        "disproof_thresholds",
        "controls",
        "regimes",
        "costs",
        "multiple_testing_family",
        "expiry",
        "missingness",
        "estimand",
        "causal_estimand",
        "identification_assumptions",
        "support_rules",
        "disproof_rules",
    }
)
MATERIAL_PROXY_SUBSTITUTIONS = frozenset(
    {"target", "causal", "entity", "geography", "outcome"}
)


class PolicyError(ValueError):
    """Typed, machine-readable policy refusal."""

    def __init__(self, code: str, *, details: Mapping[str, Any] | None = None):
        self.code = require_text(code, "policy_error_code")
        self.details = dict(details or {})
        super().__init__(self.code)


@dataclass(frozen=True)
class ChangeClassification:
    outcome: str
    changed_fields: tuple[str, ...]
    old_semantic_fingerprint: str
    new_semantic_fingerprint: str


@dataclass(frozen=True)
class ProxyGateDecision:
    outcome: str
    reason: str
    binding_id: str
    requested_use: str


@dataclass(frozen=True)
class InferenceReceipt:
    rule_id: str
    rule_version: str
    relation: str
    source_ids: tuple[str, ...]
    target_ids: tuple[str, ...]
    input_sha256: str
    output_sha256: str
    implementation_sha256: str


def _flatten_changed_fields(old: Any, new: Any, prefix: str = "") -> list[str]:
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        changed: list[str] = []
        for key in sorted(set(old) | set(new)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in old or key not in new:
                changed.append(path)
            else:
                changed.extend(_flatten_changed_fields(old[key], new[key], path))
        return changed
    if old != new:
        return [prefix or "value"]
    return []


def classify_claim_change(old: ClaimVersion, new: ClaimVersion) -> ChangeClassification:
    """Classify whether ``new`` may version ``old`` without semantic drift."""

    if old.version_id == new.version_id:
        raise PolicyError("version_id_reuse_forbidden")
    if old.semantic_fingerprint == new.semantic_fingerprint:
        if old.object_id != new.object_id:
            raise PolicyError("metadata_version_must_retain_object_id")
        outcome = "metadata_version_allowed"
    else:
        outcome = "new_child_or_hypothesis_required"
        if old.object_id == new.object_id:
            raise PolicyError(
                outcome,
                details={
                    "changed_fields": _flatten_changed_fields(
                        {
                            "claim_kind": old.claim_kind.value,
                            "proposition": old.proposition,
                            "scope": old.scope,
                            "spec": old.spec,
                            "parent_claim_ids": old.parent_claim_ids,
                            "mechanism_ids": old.mechanism_ids,
                        },
                        {
                            "claim_kind": new.claim_kind.value,
                            "proposition": new.proposition,
                            "scope": new.scope,
                            "spec": new.spec,
                            "parent_claim_ids": new.parent_claim_ids,
                            "mechanism_ids": new.mechanism_ids,
                        },
                    )
                },
            )
    return ChangeClassification(
        outcome=outcome,
        changed_fields=tuple(
            _flatten_changed_fields(
                {
                    "claim_kind": old.claim_kind.value,
                    "proposition": old.proposition,
                    "scope": old.scope,
                    "spec": old.spec,
                },
                {
                    "claim_kind": new.claim_kind.value,
                    "proposition": new.proposition,
                    "scope": new.scope,
                    "spec": new.spec,
                },
            )
        ),
        old_semantic_fingerprint=old.semantic_fingerprint,
        new_semantic_fingerprint=new.semantic_fingerprint,
    )


def validate_lifecycle_transition(previous: Lifecycle, requested: Lifecycle) -> None:
    allowed = {
        Lifecycle.ACTIVE: {Lifecycle.SUPERSEDED, Lifecycle.RETRACTED},
        Lifecycle.SUPERSEDED: set(),
        Lifecycle.RETRACTED: set(),
    }
    if requested == previous:
        raise PolicyError("lifecycle_receipt_must_change_value")
    if requested not in allowed[previous]:
        raise PolicyError(
            "lifecycle_transition_forbidden",
            details={"previous": previous.value, "requested": requested.value},
        )


def validate_no_universal_status(payload: Mapping[str, Any]) -> None:
    """Reject a generic status axis while allowing opaque legacy annotations."""

    def visit(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                new_path = (*path, str(key))
                if key == "status" and "legacy_annotations" not in path:
                    raise PolicyError(
                        "universal_status_forbidden", details={"path": ".".join(new_path)}
                    )
                visit(item, new_path)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                visit(item, (*path, str(index)))

    visit(payload, ())


def require_human_disposition_actor(
    disposition: DispositionRecord, *, actor: str, actor_kind: str
) -> None:
    if actor_kind != "human":
        raise PolicyError("agent_generated_human_authority_forbidden")
    if actor != disposition.reviewer_id:
        raise PolicyError("disposition_actor_reviewer_mismatch")
    if disposition.authority != Authority.HUMAN_REVIEWED:
        raise PolicyError("disposition_requires_human_authority")


def assess_artifact_admissibility(artifact: ArtifactReference) -> tuple[Admissibility, tuple[str, ...]]:
    missing: list[str] = []
    if artifact.sha256 is None:
        missing.append("reproducible_artifact_hash")
    required_sections = {
        "source_identity": artifact.source_identity,
        "timing": artifact.timing,
        "rights": artifact.rights,
        "scope": artifact.scope,
        "revision": artifact.revision,
        "missingness": artifact.missingness,
    }
    incomplete_markers = {"", "unknown", "unspecified", "unavailable", "not_provided"}

    def incomplete(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip().casefold() in incomplete_markers
        if isinstance(value, Mapping):
            return not value or any(incomplete(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return not value or any(incomplete(item) for item in value)
        return False

    for name, section in required_sections.items():
        if incomplete(section):
            missing.append(name)

    rights_denied_values = {"denied", "forbidden", "prohibited", "not_permitted"}
    permission_keys = {
        "research_use",
        "use_allowed",
        "access_allowed",
        "licensed_for_research",
        "permitted",
    }
    for key, value in artifact.rights.items():
        normalized_key = str(key).strip().casefold()
        if normalized_key in permission_keys and value is not True:
            missing.append("rights_denied")
        if isinstance(value, str) and value.strip().casefold() in rights_denied_values:
            missing.append("rights_denied")

    timing_keys = {
        "at",
        "as_of",
        "available_at",
        "captured_at",
        "effective_at",
        "first_public_at",
        "observed_at",
        "published_at",
        "released_at",
        "start_at",
        "end_at",
        "timestamp",
    }
    timing_values = [
        value
        for key, value in artifact.timing.items()
        if str(key).strip().casefold() in timing_keys
        or str(key).strip().casefold().endswith(("_at", "_time", "_timestamp"))
    ]
    if not timing_values:
        missing.append("timing_semantics")
    else:
        for value in timing_values:
            try:
                require_iso(value, "artifact_timing_value")
            except (TypeError, ValueError):
                missing.append("timing_invalid_or_timezone_missing")
                break

    revision_semantic_keys = {
        "policy",
        "revision_policy",
        "revision_id",
        "revision",
        "version",
        "vintage",
        "as_of",
        "revisions_possible",
    }
    if not any(
        str(key).strip().casefold() in revision_semantic_keys and not incomplete(value)
        for key, value in artifact.revision.items()
    ):
        missing.append("revision_semantics")

    missingness_semantic_keys = {
        "meaning",
        "no_event",
        "policy",
        "null_semantics",
        "missing_value_policy",
        "coverage",
    }
    if not any(
        str(key).strip().casefold() in missingness_semantic_keys and not incomplete(value)
        for key, value in artifact.missingness.items()
    ):
        missing.append("missingness_semantics")
    if artifact.missingness.get("blocked") is True:
        return Admissibility.BLOCKED, tuple(sorted(set(missing) | {"data_blocked"}))
    if missing:
        return Admissibility.INADMISSIBLE, tuple(sorted(set(missing)))
    return Admissibility.ADMISSIBLE, ()


def validate_evidence_assessment(
    *, evidence: Evidence, admissibility: Admissibility
) -> None:
    if evidence == Evidence.BLOCKED_BY_DATA and admissibility != Admissibility.BLOCKED:
        raise PolicyError("blocked_data_requires_blocked_admissibility")
    if admissibility == Admissibility.BLOCKED and evidence != Evidence.BLOCKED_BY_DATA:
        raise PolicyError("blocked_admissibility_is_not_negative_evidence")
    if evidence == Evidence.CONTRADICTED_IN_SCOPE and admissibility != Admissibility.ADMISSIBLE:
        raise PolicyError("contradiction_requires_admissible_evidence")
    if evidence == Evidence.SUPPORTED_IN_SCOPE and admissibility != Admissibility.ADMISSIBLE:
        raise PolicyError("support_requires_admissible_evidence")


def gate_proxy_use(
    binding: ProxyBinding,
    *,
    requested_use: str,
    as_of: str,
    requested_scope: Mapping[str, Any],
    registered_bindings: Mapping[str, str] | None = None,
) -> ProxyGateDecision:
    requested = require_text(requested_use, "requested_proxy_use")
    at = datetime.fromisoformat(require_iso(as_of, "proxy_gate_as_of").replace("Z", "+00:00"))
    expires = datetime.fromisoformat(binding.expires_at.replace("Z", "+00:00"))
    if requested in MATERIAL_PROXY_SUBSTITUTIONS:
        return ProxyGateDecision(
            "review_required",
            "material_proxy_substitution",
            binding.object_id,
            requested,
        )
    if requested not in PROXY_USES or requested not in binding.permitted_uses:
        return ProxyGateDecision(
            "review_required", "proxy_use_not_preapproved", binding.object_id, requested
        )
    if at >= expires:
        return ProxyGateDecision("blocked", "proxy_binding_expired", binding.object_id, requested)
    if not registered_bindings or registered_bindings.get(binding.object_id) != binding.version_id:
        return ProxyGateDecision(
            "review_required", "proxy_binding_not_registered", binding.object_id, requested
        )
    if not is_bounded_scope(binding.scope):
        return ProxyGateDecision(
            "review_required", "proxy_binding_scope_unbounded", binding.object_id, requested
        )
    if not is_bounded_scope(requested_scope):
        return ProxyGateDecision(
            "review_required", "proxy_requested_scope_required", binding.object_id, requested
        )
    if dict(requested_scope) != dict(binding.scope):
        return ProxyGateDecision(
            "review_required", "proxy_scope_mismatch", binding.object_id, requested
        )
    return ProxyGateDecision("preapproved", "registered_bounded_proxy", binding.object_id, requested)


def validate_inference(
    *,
    relation: str,
    rule_id: str,
    rule_version: str,
    deterministic: bool,
    source_ids: Sequence[str],
    target_ids: Sequence[str],
    input_sha256: str,
    output_sha256: str,
    implementation_sha256: str,
    registered_rules: Sequence[Mapping[str, Any]] | None = None,
) -> InferenceReceipt:
    relation_name = require_text(relation, "inference_relation")
    if relation_name in FORBIDDEN_BARE_RELATIONS or relation_name not in DERIVATION_RELATIONS:
        raise PolicyError("inference_relation_default_denied", details={"relation": relation_name})
    if deterministic is not True:
        raise PolicyError("inference_must_be_deterministic")
    registered_rule_id = require_text(rule_id, "inference_rule_id")
    registered_rule_version = require_semver(rule_version, "inference_rule_version")
    if not registered_rules:
        raise PolicyError("inference_rule_registry_required")
    registry_ids = [str(rule.get("rule_id") or "") for rule in registered_rules]
    if len(set(registry_ids)) != len(registry_ids):
        raise PolicyError("inference_rule_registry_invalid")
    matching_rules = [
        rule
        for rule in registered_rules
        if rule.get("rule_id") == registered_rule_id
        and rule.get("version") == registered_rule_version
        and rule.get("relation") == relation_name
    ]
    if len(matching_rules) != 1:
        raise PolicyError("inference_rule_not_registered")
    registered_rule = matching_rules[0]
    if (
        not STABLE_DERIVATION_RULE_ID_RE.fullmatch(registered_rule_id)
        or not str(registered_rule.get("source_record") or "").strip()
        or not str(registered_rule.get("source_field") or "").strip()
        or registered_rule.get("deterministic") is not True
        or registered_rule.get("provenance_required") is not True
        or registered_rule.get("semantic_authority_added") is not False
        or registered_rule.get("transitive") is not False
    ):
        raise PolicyError("inference_registered_rule_semantics_invalid")
    if not source_ids or not target_ids:
        raise PolicyError("inference_complete_provenance_required")
    for value, field_name in (
        (input_sha256, "inference_input_sha256"),
        (output_sha256, "inference_output_sha256"),
        (implementation_sha256, "inference_implementation_sha256"),
    ):
        require_sha256(value, field_name)
    if len(set(source_ids)) != len(source_ids) or len(set(target_ids)) != len(target_ids):
        raise PolicyError("inference_provenance_ids_must_be_unique")
    receipt = InferenceReceipt(
        rule_id=registered_rule_id,
        rule_version=registered_rule_version,
        relation=relation_name,
        source_ids=tuple(sorted(source_ids)),
        target_ids=tuple(sorted(target_ids)),
        input_sha256=input_sha256,
        output_sha256=output_sha256,
        implementation_sha256=implementation_sha256,
    )
    # Exercise canonical serialization here so malformed provenance fails before use.
    canonical_sha256("inference_receipt_v0", receipt.__dict__)
    return receipt
