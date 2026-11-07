"""Explicit, file-locked, append-only JSONL ledger with deterministic replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import (
    Admissibility,
    Authority,
    ClaimKind,
    ClaimVersion,
    ContractMixin,
    Decision,
    Evidence,
    Freshness,
    Lifecycle,
    canonical_json,
    canonical_sha256,
    new_opaque_id,
    require_iso,
    require_opaque_id,
    require_semver,
    require_sha256,
    require_text,
)
from .policy import (
    DERIVATION_RELATIONS,
    FORBIDDEN_BARE_RELATIONS,
    PolicyError,
    validate_lifecycle_transition,
    validate_no_universal_status,
)


LEDGER_SCHEMA = "research_ontology_ledger_event_v0"
EVENT_HASH_DOMAIN = b"research_ontology_ledger_event_v0\0"
ENVELOPE_FIELDS = frozenset(
    {
        "schema",
        "event_id",
        "object_id",
        "version_id",
        "event_type",
        "ontology_version",
        "actor",
        "recorded_at",
        "payload",
        "previous_event_hash",
        "event_hash",
        "research_only",
        "execution_allowed",
    }
)
ACTOR_KINDS = frozenset({"human", "agent", "system", "migration"})
CLAIM_SEMANTIC_FIELDS = (
    "claim_kind",
    "proposition",
    "scope",
    "spec",
    "parent_claim_ids",
    "mechanism_ids",
)


class LedgerError(ValueError):
    """Base error with a stable code and optional diagnostics."""

    def __init__(
        self,
        code: str,
        *,
        line_number: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = require_text(code, "ledger_error_code")
        self.line_number = line_number
        self.details = dict(details or {})
        super().__init__(self.code)


class LedgerParseError(LedgerError):
    pass


class LedgerValidationError(LedgerError):
    pass


@dataclass(frozen=True)
class ReplayResult:
    events: tuple[Mapping[str, Any], ...]
    head_hash: str | None
    ledger_sha256: str


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def event_hash(event_without_hash: Mapping[str, Any]) -> str:
    return hashlib.sha256(EVENT_HASH_DOMAIN + canonical_json_bytes(event_without_hash)).hexdigest()


def ledger_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _validate_actor(actor: Any) -> None:
    if not isinstance(actor, Mapping) or set(actor) != {"actor_id", "actor_kind"}:
        raise LedgerValidationError("actor_contract_invalid")
    require_text(actor.get("actor_id"), "actor_id")
    if actor.get("actor_kind") not in ACTOR_KINDS:
        raise LedgerValidationError("actor_kind_invalid")


def _type_token(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _record_is(payload: Mapping[str, Any], *names: str) -> bool:
    return _type_token(payload.get("record_type")) in {_type_token(name) for name in names}


def _nonempty_string_list(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def _claim_semantic_fingerprint(payload: Mapping[str, Any]) -> str:
    if any(field not in payload for field in CLAIM_SEMANTIC_FIELDS):
        raise LedgerValidationError("claim_semantic_fields_incomplete")
    return canonical_sha256(
        "claim_semantic_fingerprint_v0",
        {field: payload[field] for field in CLAIM_SEMANTIC_FIELDS},
    )


def _payload_axis(payload: Mapping[str, Any], axis_name: str) -> Any:
    axes = payload.get("axes")
    if isinstance(axes, Mapping) and axis_name in axes:
        return axes[axis_name]
    return payload.get(axis_name)


def _contains_wildcard(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_wildcard(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_wildcard(item) for item in value)
    return value == "*"


def _validate_declared_human_authority(
    value: Any,
    *,
    actor: Mapping[str, Any],
    path: tuple[str, ...] = (),
) -> None:
    if isinstance(value, Mapping):
        in_legacy = "legacy_annotations" in path
        if not in_legacy:
            authority = value.get("authority")
            decision = value.get("decision")
            axes = value.get("axes")
            if isinstance(axes, Mapping):
                authority = axes.get("authority", authority)
                decision = axes.get("decision", decision)
            if authority == "human_reviewed" and actor.get("actor_kind") != "human":
                raise LedgerValidationError("agent_generated_human_authority_forbidden")
            if decision not in (None, "pending") and actor.get("actor_kind") != "human":
                raise LedgerValidationError("agent_generated_human_decision_forbidden")
        for key, item in value.items():
            _validate_declared_human_authority(
                item,
                actor=actor,
                path=(*path, str(key)),
            )
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_declared_human_authority(
                item,
                actor=actor,
                path=(*path, str(index)),
            )


def _validate_nested_axis_bundles(value: Any, path: tuple[str, ...] = ()) -> None:
    allowed = {
        "lifecycle": {item.value for item in Lifecycle},
        "evidence": {item.value for item in Evidence},
        "authority": {item.value for item in Authority},
        "decision": {item.value for item in Decision},
        "freshness": {item.value for item in Freshness},
        "admissibility": {item.value for item in Admissibility},
    }
    if isinstance(value, Mapping):
        if "legacy_annotations" not in path:
            axis_keys = set(value) & set(allowed)
            is_axis_bundle = len(axis_keys) >= 2 or (path and path[-1] == "axes")
            if is_axis_bundle:
                for key in axis_keys:
                    if value[key] not in allowed[key]:
                        raise LedgerValidationError(f"{key}_axis_invalid")
        for key, item in value.items():
            _validate_nested_axis_bundles(item, (*path, str(key)))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_nested_axis_bundles(item, (*path, str(index)))


def _walk_semantic_edges(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        if "relation" in value:
            relation = str(value.get("relation") or "").strip().lower()
            in_legacy = "legacy_annotations" in path
            if not in_legacy and relation in FORBIDDEN_BARE_RELATIONS:
                qualification = value.get("qualification")
                if not isinstance(qualification, Mapping):
                    raise LedgerValidationError("bare_semantic_relation_forbidden")
                required = ("claim_version_id", "scope", "provenance_refs")
                if any(not qualification.get(name) for name in required):
                    raise LedgerValidationError("semantic_relation_qualification_incomplete")
            if not in_legacy and value.get("derived") is True:
                if relation not in DERIVATION_RELATIONS:
                    raise LedgerValidationError("derived_relation_default_denied")
                if value.get("deterministic") is not True:
                    raise LedgerValidationError("derived_relation_must_be_deterministic")
                if not isinstance(value.get("rule_id"), str) or not value["rule_id"].strip():
                    raise LedgerValidationError("derived_relation_provenance_incomplete")
                try:
                    require_semver(value.get("rule_version"), "derived_relation_rule_version")
                except ValueError as exc:
                    raise LedgerValidationError("derived_relation_provenance_incomplete") from exc
                if not _nonempty_string_list(value.get("provenance_refs")):
                    raise LedgerValidationError("derived_relation_provenance_incomplete")
        if value.get("execution_allowed") is True:
            raise LedgerValidationError("execution_enablement_forbidden")
        if value.get("can_affect_trading") is True or value.get("is_trading_signal") is True:
            raise LedgerValidationError("trading_authority_forbidden")
        for key, item in value.items():
            _walk_semantic_edges(item, (*path, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_semantic_edges(item, (*path, str(index)))


def _validate_payload(payload: Any, *, actor: Mapping[str, Any]) -> None:
    if not isinstance(payload, Mapping):
        raise LedgerValidationError("payload_must_be_mapping")
    if not payload.get("record_type"):
        raise LedgerValidationError("payload_record_type_required")
    try:
        validate_no_universal_status(payload)
    except PolicyError as exc:
        raise LedgerValidationError(exc.code, details=exc.details) from exc
    if payload.get("research_only") is not True:
        raise LedgerValidationError("payload_research_only_must_be_true")
    if payload.get("execution_allowed") is not False:
        raise LedgerValidationError("payload_execution_allowed_must_be_false")
    axis_values = {
        "lifecycle": {value.value for value in Lifecycle},
        "evidence": {value.value for value in Evidence},
        "authority": {value.value for value in Authority},
        "decision": {value.value for value in Decision},
        "freshness": {value.value for value in Freshness},
        "admissibility": {value.value for value in Admissibility},
    }
    axes = payload.get("axes")
    if axes is not None and not isinstance(axes, Mapping):
        raise LedgerValidationError("axes_must_be_mapping")
    if isinstance(axes, Mapping):
        unknown_axes = set(axes) - set(axis_values)
        if unknown_axes:
            raise LedgerValidationError("unknown_axis_forbidden")
    for axis_name, allowed_values in axis_values.items():
        direct = payload.get(axis_name)
        nested = axes.get(axis_name) if isinstance(axes, Mapping) else None
        if direct is not None and nested is not None and direct != nested:
            raise LedgerValidationError("axis_value_conflict")
        selected = nested if nested is not None else direct
        if selected is not None and selected not in allowed_values:
            raise LedgerValidationError(f"{axis_name}_axis_invalid")
    _validate_declared_human_authority(payload, actor=actor)
    _validate_nested_axis_bundles(payload)
    _walk_semantic_edges(payload)
    if _record_is(payload, "ClaimVersion"):
        if payload.get("claim_kind") not in {value.value for value in ClaimKind}:
            raise LedgerValidationError("claim_kind_invalid")
        supplied = payload.get("semantic_fingerprint")
        if not isinstance(supplied, str) or len(supplied) != 64:
            raise LedgerValidationError("claim_semantic_fingerprint_required")
        if supplied != _claim_semantic_fingerprint(payload):
            raise LedgerValidationError("claim_semantic_fingerprint_mismatch")
    if _record_is(payload, "DispositionRecord"):
        if actor.get("actor_kind") != "human":
            raise LedgerValidationError("agent_generated_human_authority_forbidden")
        if actor.get("actor_id") != payload.get("reviewer_id"):
            raise LedgerValidationError("disposition_actor_reviewer_mismatch")
        if payload.get("authority") != "human_reviewed":
            raise LedgerValidationError("disposition_requires_human_reviewed_authority")
        for name in ("target_object_id", "target_version_id", "reviewer_id", "rationale", "decision_at"):
            if not payload.get(name):
                raise LedgerValidationError("disposition_exact_binding_required")
        try:
            require_opaque_id(payload.get("target_object_id"), "disposition_target_object_id")
            require_opaque_id(payload.get("target_version_id"), "disposition_target_version_id")
            require_iso(payload.get("decision_at"), "disposition_decision_at")
        except ValueError as exc:
            raise LedgerValidationError("disposition_exact_binding_required") from exc
        if not isinstance(payload.get("scope"), Mapping) or any(
            _contains_wildcard(value) for value in payload["scope"].values()
        ):
            raise LedgerValidationError("disposition_broad_scope_forbidden")
    if _record_is(payload, "AxisReceipt"):
        if (
            payload.get("axis_name") == "authority"
            and payload.get("axis_value") == "human_reviewed"
            and actor.get("actor_kind") != "human"
        ):
            raise LedgerValidationError("agent_generated_human_authority_forbidden")
        if (
            payload.get("axis_name") == "decision"
            and payload.get("axis_value") != "pending"
            and actor.get("actor_kind") != "human"
        ):
            raise LedgerValidationError("agent_generated_human_decision_forbidden")
        axis_name = payload.get("axis_name")
        if axis_name not in axis_values or payload.get("axis_value") not in axis_values[axis_name]:
            raise LedgerValidationError("axis_receipt_value_invalid")
        if not payload.get("target_object_id") or not payload.get("target_version_id"):
            raise LedgerValidationError("axis_receipt_exact_binding_required")
        try:
            require_opaque_id(payload.get("target_object_id"), "axis_target_object_id")
            require_opaque_id(payload.get("target_version_id"), "axis_target_version_id")
        except ValueError as exc:
            raise LedgerValidationError("axis_receipt_exact_binding_required") from exc
        if payload.get("axis_name") == "evidence" and payload.get("axis_value") in {
            "supported_in_scope",
            "contradicted_in_scope",
        }:
            raise LedgerValidationError(
                "support_or_contradiction_requires_evidence_assessment"
            )
    if _record_is(payload, "ArtifactReference"):
        required_sections = (
            "source_identity",
            "timing",
            "rights",
            "scope",
            "revision",
            "missingness",
        )
        if any(not isinstance(payload.get(name), Mapping) or not payload.get(name) for name in required_sections):
            raise LedgerValidationError("artifact_admissibility_metadata_incomplete")
        sha = payload.get("sha256")
        if sha is not None and (not isinstance(sha, str) or len(sha) != 64):
            raise LedgerValidationError("artifact_sha256_invalid")
    evidence = payload.get("evidence")
    admissibility = payload.get("admissibility")
    if evidence == "blocked_by_data" and admissibility != "blocked":
        raise LedgerValidationError("blocked_data_requires_blocked_admissibility")
    if admissibility == "blocked" and evidence not in (None, "blocked_by_data"):
        raise LedgerValidationError("blocked_admissibility_is_not_negative_evidence")
    if evidence in {"supported_in_scope", "contradicted_in_scope"} and admissibility != "admissible":
        raise LedgerValidationError("support_or_contradiction_requires_admissible_evidence")
    if admissibility == "admissible" and evidence in {
        "supported_in_scope",
        "contradicted_in_scope",
        "mixed",
    } and not payload.get("artifact_refs"):
        raise LedgerValidationError("admissible_assessment_artifact_refs_required")
    if payload.get("evidence_basis") == "proxy_only" and evidence in {
        "supported_in_scope",
        "contradicted_in_scope",
    }:
        raise LedgerValidationError("proxy_only_evidence_cannot_promote_exact_claim")
    effect = str(payload.get("evidence_effect") or "").strip().lower()
    if evidence == "blocked_by_data" and (
        effect
        in {
            "support",
            "supports",
            "positive_evidence",
            "contradiction",
            "contradicts",
            "negative_evidence",
        }
        or payload.get("supports") is True
        or payload.get("contradicts") is True
    ):
        raise LedgerValidationError("blocked_data_is_not_support_or_contradiction")
    if payload.get("proxy_gate") == "preapproved" and payload.get("requested_use") in {
        "target",
        "causal",
        "entity",
        "geography",
        "outcome",
    }:
        raise LedgerValidationError("material_proxy_substitution_requires_review")
    if _record_is(payload, "ProxyBinding"):
        permitted = payload.get("permitted_uses")
        if (
            not isinstance(permitted, (list, tuple))
            or not permitted
            or any(value not in {"context", "screening", "control"} for value in permitted)
            or len(set(permitted)) != len(permitted)
        ):
            raise LedgerValidationError("proxy_permitted_uses_invalid")
        try:
            require_opaque_id(payload.get("proxy_variable_id"), "proxy_variable_id")
            require_opaque_id(payload.get("construct_id"), "proxy_construct_id")
            require_iso(payload.get("expires_at"), "proxy_expires_at")
        except ValueError as exc:
            raise LedgerValidationError("proxy_binding_contract_invalid") from exc
        if (
            not isinstance(payload.get("scope"), Mapping)
            or not payload["scope"]
            or _contains_wildcard(payload["scope"])
        ):
            raise LedgerValidationError("proxy_scope_must_be_bounded")
    if _record_is(payload, "ProxyGateDecision") and payload.get("proxy_gate") == "preapproved":
        if not (
            payload.get("binding_id")
            and payload.get("binding_version_id")
            and isinstance(payload.get("requested_scope"), Mapping)
            and payload.get("requested_scope")
            and not _contains_wildcard(payload.get("requested_scope"))
        ):
            raise LedgerValidationError("proxy_preapproval_exact_binding_required")
    if _record_is(payload, "InferenceReceipt", "Inference", "Derivation", "DerivedRelation"):
        relation = str(payload.get("relation") or "").strip().lower()
        if relation not in DERIVATION_RELATIONS:
            raise LedgerValidationError("inference_relation_default_denied")
        if payload.get("deterministic") is not True:
            raise LedgerValidationError("inference_must_be_deterministic")
        if not (
            isinstance(payload.get("rule_id"), str)
            and bool(payload["rule_id"].strip())
            and isinstance(payload.get("rule_version"), str)
            and _nonempty_string_list(payload.get("source_ids"))
            and _nonempty_string_list(payload.get("target_ids"))
        ):
            raise LedgerValidationError("inference_complete_provenance_required")
        try:
            require_semver(payload.get("rule_version"), "inference_rule_version")
            for name in ("input_sha256", "output_sha256", "implementation_sha256"):
                require_sha256(payload.get(name), name)
        except ValueError as exc:
            raise LedgerValidationError("inference_complete_provenance_required") from exc


def _semantic_release_signature(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        b"ontology_release_machine_meaning_v0\0"
        + canonical_json_bytes(
            {
                "terms": payload.get("terms"),
                "derivation_rules": payload.get("derivation_rules"),
                "lifecycle_values": payload.get("lifecycle_values"),
                "evidence_values": payload.get("evidence_values"),
                "authority_values": payload.get("authority_values"),
                "decision_values": payload.get("decision_values"),
                "freshness_values": payload.get("freshness_values"),
                "admissibility_values": payload.get("admissibility_values"),
            }
        )
    ).hexdigest()


def _release_core(version: str) -> tuple[int, int, int]:
    base = version.split("-", 1)[0]
    major, minor, patch = base.split(".")
    return int(major), int(minor), int(patch)


def _release_prerelease(version: str) -> str | None:
    return version.split("-", 1)[1] if "-" in version else None


def _release_terms(payload: Mapping[str, Any], *, line_number: int) -> dict[str, str]:
    terms = payload.get("terms")
    if not isinstance(terms, list) or not terms:
        raise LedgerValidationError("ontology_terms_required", line_number=line_number)
    result: dict[str, str] = {}
    keys: set[str] = set()
    for term in terms:
        if not isinstance(term, Mapping):
            raise LedgerValidationError("ontology_term_invalid", line_number=line_number)
        try:
            term_id = require_opaque_id(term.get("term_id"), "ontology_term_id")
            term_key = require_text(term.get("term_key"), "ontology_term_key")
            require_text(term.get("definition"), "ontology_term_definition")
        except ValueError as exc:
            raise LedgerValidationError("ontology_term_invalid", line_number=line_number) from exc
        if term_id in result or term_key in keys:
            raise LedgerValidationError("ontology_release_duplicate_term", line_number=line_number)
        result[term_id] = canonical_sha256("research_ontology_term_v0", term)
        keys.add(term_key)
    return result


def _release_rules(payload: Mapping[str, Any], *, line_number: int) -> dict[str, str]:
    rules = payload.get("derivation_rules")
    if not isinstance(rules, list) or not rules:
        raise LedgerValidationError("ontology_derivation_rules_required", line_number=line_number)
    result: dict[str, str] = {}
    relations: set[str] = set()
    for rule in rules:
        if not isinstance(rule, Mapping):
            raise LedgerValidationError("ontology_derivation_rule_invalid", line_number=line_number)
        try:
            rule_id = require_text(rule.get("rule_id"), "derivation_rule_id")
            relation = require_text(rule.get("relation"), "derivation_rule_relation")
            require_semver(rule.get("version"), "derivation_rule_version")
        except ValueError as exc:
            raise LedgerValidationError("ontology_derivation_rule_invalid", line_number=line_number) from exc
        if relation not in DERIVATION_RELATIONS:
            raise LedgerValidationError("ontology_derivation_relation_default_denied", line_number=line_number)
        if (
            rule.get("deterministic") is not True
            or rule.get("provenance_required") is not True
            or rule.get("semantic_authority_added") is not False
            or rule.get("transitive") is not False
        ):
            raise LedgerValidationError("ontology_derivation_rule_invalid", line_number=line_number)
        if rule_id in result:
            raise LedgerValidationError("ontology_derivation_rule_id_reuse", line_number=line_number)
        result[rule_id] = canonical_sha256("research_ontology_derivation_rule_v0", rule)
        if relation in relations:
            raise LedgerValidationError("ontology_derivation_relation_reuse", line_number=line_number)
        relations.add(relation)
    if relations != DERIVATION_RELATIONS:
        raise LedgerValidationError(
            "ontology_derivation_rules_must_cover_exact_whitelist",
            line_number=line_number,
        )
    return result


def _validate_release_axes(payload: Mapping[str, Any], *, line_number: int) -> None:
    expected = {
        "lifecycle_values": [value.value for value in Lifecycle],
        "evidence_values": [value.value for value in Evidence],
        "authority_values": [value.value for value in Authority],
        "decision_values": [value.value for value in Decision],
        "freshness_values": [value.value for value in Freshness],
        "admissibility_values": [value.value for value in Admissibility],
    }
    if any(payload.get(name) != values for name, values in expected.items()):
        raise LedgerValidationError(
            "ontology_axis_values_mismatch", line_number=line_number
        )


def _validate_event(
    event: Any,
    *,
    previous_hash: str | None,
    line_number: int,
) -> None:
    if not isinstance(event, Mapping):
        raise LedgerValidationError("event_must_be_mapping", line_number=line_number)
    if set(event) != ENVELOPE_FIELDS:
        raise LedgerValidationError(
            "event_envelope_fields_invalid",
            line_number=line_number,
            details={
                "missing": sorted(ENVELOPE_FIELDS - set(event)),
                "extra": sorted(set(event) - ENVELOPE_FIELDS),
            },
        )
    if event.get("schema") != LEDGER_SCHEMA:
        raise LedgerValidationError("ledger_schema_invalid", line_number=line_number)
    for key in ("event_id", "object_id", "version_id"):
        try:
            require_opaque_id(event.get(key), key)
        except ValueError as exc:
            raise LedgerValidationError(str(exc), line_number=line_number) from exc
    require_text(event.get("event_type"), "event_type")
    require_semver(event.get("ontology_version"))
    require_iso(event.get("recorded_at"), "recorded_at")
    _validate_actor(event.get("actor"))
    if event.get("research_only") is not True:
        raise LedgerValidationError("event_research_only_must_be_true", line_number=line_number)
    if event.get("execution_allowed") is not False:
        raise LedgerValidationError("event_execution_allowed_must_be_false", line_number=line_number)
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        for identity_name in ("object_id", "version_id"):
            if identity_name in payload and payload[identity_name] != event.get(identity_name):
                raise LedgerValidationError(
                    "payload_identity_mismatch", line_number=line_number
                )
    if event.get("previous_event_hash") != previous_hash:
        raise LedgerValidationError("previous_event_hash_mismatch", line_number=line_number)
    claimed_hash = event.get("event_hash")
    if not isinstance(claimed_hash, str) or len(claimed_hash) != 64:
        raise LedgerValidationError("event_hash_invalid", line_number=line_number)
    basis = dict(event)
    basis.pop("event_hash")
    if event_hash(basis) != claimed_hash:
        raise LedgerValidationError("event_hash_mismatch", line_number=line_number)
    _validate_payload(payload, actor=event["actor"])


def replay_ledger_bytes(raw: bytes) -> ReplayResult:
    if raw and not raw.endswith(b"\n"):
        raise LedgerParseError("ledger_missing_final_newline")
    events: list[Mapping[str, Any]] = []
    event_ids: set[str] = set()
    version_owners: dict[str, str] = {}
    version_lifecycle: dict[str, Lifecycle] = {}
    object_versions: dict[str, list[Mapping[str, Any]]] = {}
    term_meanings: dict[str, str] = {}
    term_key_ids: dict[str, str] = {}
    release_versions: dict[str, str] = {}
    release_history: list[dict[str, Any]] = []
    release_rules_by_version: dict[str, dict[str, Mapping[str, Any]]] = {}
    proxy_bindings: dict[tuple[str, str], Mapping[str, Any]] = {}
    previous_hash: str | None = None
    previous_recorded_at: datetime | None = None
    pending_exact_targets: list[tuple[int, str, str]] = []
    pending_assessment_targets: list[tuple[int, str]] = []
    pending_lifecycle_updates: list[tuple[int, str, str]] = []
    pending_inferences: list[tuple[int, str, Mapping[str, Any]]] = []
    pending_proxy_gates: list[tuple[int, datetime, Mapping[str, Any]]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise LedgerParseError("ledger_blank_line_forbidden", line_number=line_number)
        def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise LedgerParseError("ledger_duplicate_json_key", line_number=line_number)
                result[key] = value
            return result

        def reject_constant(_: str) -> None:
            raise LedgerParseError("ledger_nonfinite_number", line_number=line_number)

        try:
            event = json.loads(line, object_pairs_hook=pairs_hook, parse_constant=reject_constant)
        except LedgerParseError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LedgerParseError("ledger_json_invalid", line_number=line_number) from exc
        try:
            _validate_event(event, previous_hash=previous_hash, line_number=line_number)
        except LedgerError:
            raise
        except (TypeError, ValueError) as exc:
            raise LedgerValidationError(str(exc), line_number=line_number) from exc
        event_id = event["event_id"]
        version_id = event["version_id"]
        object_id = event["object_id"]
        if event_id in event_ids:
            raise LedgerValidationError("event_id_reuse_forbidden", line_number=line_number)
        if version_id in version_owners:
            raise LedgerValidationError("version_id_reuse_forbidden", line_number=line_number)
        event_ids.add(event_id)
        payload = event["payload"]
        recorded_at = datetime.fromisoformat(
            str(event["recorded_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        if previous_recorded_at is not None and recorded_at < previous_recorded_at:
            raise LedgerValidationError("recorded_at_order_invalid", line_number=line_number)
        previous_recorded_at = recorded_at
        prior_types = {
            _type_token(prior["payload"].get("record_type"))
            for prior in object_versions.get(object_id, [])
        }
        if prior_types and _type_token(payload.get("record_type")) not in prior_types:
            raise LedgerValidationError("object_type_reuse_forbidden", line_number=line_number)
        if _record_is(payload, "ClaimVersion"):
            prior_claims = [
                prior
                for prior in object_versions.get(object_id, [])
                if _record_is(prior["payload"], "ClaimVersion")
            ]
            if prior_claims:
                old_fingerprint = _claim_semantic_fingerprint(prior_claims[-1]["payload"])
                new_fingerprint = _claim_semantic_fingerprint(payload)
                if old_fingerprint != new_fingerprint:
                    raise LedgerValidationError(
                        "material_change_requires_child_object", line_number=line_number
                    )

        exact_target_types = (
            "AxisReceipt",
            "DispositionRecord",
            "AmbiguityPacket",
            "AxisAssessment",
        )
        if _record_is(payload, *exact_target_types):
            target_object_id = str(payload.get("target_object_id") or "")
            target_version_id = str(payload.get("target_version_id") or "")
            pending_exact_targets.append(
                (line_number, target_object_id, target_version_id)
            )
            requested_lifecycle = _payload_axis(payload, "lifecycle")
            if _record_is(payload, "AxisReceipt") and payload.get("axis_name") == "lifecycle":
                requested_lifecycle = payload.get("axis_value")
            if requested_lifecycle is not None:
                pending_lifecycle_updates.append(
                    (line_number, target_version_id, str(requested_lifecycle))
                )

        if _record_is(payload, "EvidenceAssessment"):
            target_version_id = str(payload.get("claim_version_id") or "")
            pending_assessment_targets.append((line_number, target_version_id))

        if _record_is(payload, "OntologyRelease"):
            release_version = str(payload.get("version") or "")
            require_semver(release_version, "ontology_release_version")
            if release_version != event.get("ontology_version"):
                raise LedgerValidationError("ontology_release_version_mismatch", line_number=line_number)
            signature = _semantic_release_signature(payload)
            if release_version in release_versions:
                code = (
                    "released_ontology_rewrite_forbidden"
                    if release_versions[release_version] != signature
                    else "ontology_release_version_reuse_forbidden"
                )
                raise LedgerValidationError(code, line_number=line_number)
            current_terms = _release_terms(payload, line_number=line_number)
            current_rules = _release_rules(payload, line_number=line_number)
            _validate_release_axes(payload, line_number=line_number)
            current_core = _release_core(release_version)
            current_prerelease = _release_prerelease(release_version)
            if release_history:
                previous_release = release_history[-1]
                previous_core = previous_release["core"]
                if current_core < previous_core:
                    raise LedgerValidationError(
                        "ontology_release_order_invalid", line_number=line_number
                    )
                if current_core == previous_core:
                    if previous_release["prerelease"] is None or current_prerelease is not None:
                        raise LedgerValidationError(
                            "ontology_release_order_invalid", line_number=line_number
                        )
                    if signature != previous_release["signature"]:
                        raise LedgerValidationError(
                            "ontology_release_freeze_mismatch", line_number=line_number
                        )
                elif current_core[:2] == previous_core[:2]:
                    if signature != previous_release["signature"]:
                        raise LedgerValidationError(
                            "ontology_patch_meaning_change_forbidden", line_number=line_number
                        )
                elif current_core[0] == previous_core[0]:
                    if current_core[1] <= previous_core[1] or current_core[2] != 0:
                        raise LedgerValidationError(
                            "ontology_release_order_invalid", line_number=line_number
                        )
                    if any(
                        current_terms.get(term_id) != term_hash
                        for term_id, term_hash in previous_release["terms"].items()
                    ) or any(
                        current_rules.get(rule_id) != rule_hash
                        for rule_id, rule_hash in previous_release["rules"].items()
                    ):
                        raise LedgerValidationError(
                            "ontology_minor_must_be_additive", line_number=line_number
                        )
            release_versions[release_version] = signature
            for term in payload.get("terms", []):
                if not isinstance(term, Mapping):
                    raise LedgerValidationError("ontology_term_invalid", line_number=line_number)
                term_id = str(term.get("term_id") or "")
                term_key = str(term.get("term_key") or "")
                meaning = canonical_sha256("research_ontology_term_v0", term)
                if term_id in term_meanings and term_meanings[term_id] != meaning:
                    raise LedgerValidationError("ontology_term_rewrite_forbidden", line_number=line_number)
                term_meanings[term_id] = meaning
                if term_key in term_key_ids and term_key_ids[term_key] != term_id:
                    raise LedgerValidationError("ontology_term_key_rebound", line_number=line_number)
                term_key_ids[term_key] = term_id
            release_history.append(
                {
                    "version": release_version,
                    "core": current_core,
                    "prerelease": current_prerelease,
                    "signature": signature,
                    "terms": current_terms,
                    "rules": current_rules,
                }
            )
            release_rules_by_version[release_version] = {
                str(rule["rule_id"]): rule
                for rule in payload["derivation_rules"]
            }
        if _record_is(payload, "InferenceReceipt", "Inference", "Derivation", "DerivedRelation"):
            pending_inferences.append((line_number, str(event["ontology_version"]), payload))
        if _record_is(payload, "ProxyBinding"):
            proxy_bindings[(object_id, version_id)] = payload
        if _record_is(payload, "ProxyGateDecision") and payload.get("proxy_gate") == "preapproved":
            pending_proxy_gates.append((line_number, recorded_at, payload))
        version_owners[version_id] = object_id
        initial_lifecycle = _payload_axis(payload, "lifecycle")
        version_lifecycle[version_id] = (
            Lifecycle(str(initial_lifecycle))
            if initial_lifecycle is not None
            else Lifecycle.ACTIVE
        )
        object_versions.setdefault(object_id, []).append(event)
        previous_hash = event["event_hash"]
        events.append(event)
    for line_number, target_object_id, target_version_id in pending_exact_targets:
        owner = version_owners.get(target_version_id)
        if owner is None:
            raise LedgerValidationError(
                "exact_target_version_not_found", line_number=line_number
            )
        if owner != target_object_id:
            raise LedgerValidationError(
                "exact_target_object_version_mismatch", line_number=line_number
            )
    for line_number, target_version_id in pending_assessment_targets:
        if target_version_id not in version_owners:
            raise LedgerValidationError(
                "assessment_target_version_not_found", line_number=line_number
            )
    for line_number, target_version_id, requested_value in pending_lifecycle_updates:
        previous_lifecycle = version_lifecycle[target_version_id]
        try:
            requested = Lifecycle(requested_value)
            validate_lifecycle_transition(previous_lifecycle, requested)
        except (PolicyError, ValueError) as exc:
            code = exc.code if isinstance(exc, PolicyError) else "lifecycle_axis_invalid"
            raise LedgerValidationError(code, line_number=line_number) from exc
        version_lifecycle[target_version_id] = requested
    for line_number, ontology_version, payload in pending_inferences:
        registered = release_rules_by_version.get(ontology_version, {})
        rule = registered.get(str(payload.get("rule_id") or ""))
        if rule is None:
            raise LedgerValidationError(
                "inference_rule_not_registered", line_number=line_number
            )
        if (
            rule.get("relation") != payload.get("relation")
            or rule.get("version") != payload.get("rule_version")
        ):
            raise LedgerValidationError(
                "inference_rule_registration_mismatch", line_number=line_number
            )
    for line_number, gate_time, payload in pending_proxy_gates:
        binding_id = str(payload.get("binding_id") or "")
        binding_version_id = str(payload.get("binding_version_id") or "")
        binding = proxy_bindings.get((binding_id, binding_version_id))
        if binding is None:
            raise LedgerValidationError(
                "proxy_binding_not_registered", line_number=line_number
            )
        if payload.get("requested_use") not in binding.get("permitted_uses", []):
            raise LedgerValidationError(
                "proxy_use_not_preapproved", line_number=line_number
            )
        if dict(payload.get("requested_scope") or {}) != dict(binding.get("scope") or {}):
            raise LedgerValidationError(
                "proxy_scope_mismatch", line_number=line_number
            )
        expires_at = datetime.fromisoformat(
            str(binding["expires_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        if gate_time >= expires_at:
            raise LedgerValidationError(
                "proxy_binding_expired", line_number=line_number
            )
    return ReplayResult(tuple(events), previous_hash, ledger_sha256(raw))


def build_event(
    *,
    object_id: str,
    version_id: str,
    event_type: str,
    ontology_version: str,
    actor_id: str,
    actor_kind: str,
    recorded_at: str,
    payload: Mapping[str, Any],
    previous_event_hash: str | None,
    event_id: str | None = None,
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema": LEDGER_SCHEMA,
        "event_id": event_id or new_opaque_id(),
        "object_id": object_id,
        "version_id": version_id,
        "event_type": event_type,
        "ontology_version": ontology_version,
        "actor": {"actor_id": actor_id, "actor_kind": actor_kind},
        "recorded_at": recorded_at,
        "payload": dict(payload),
        "previous_event_hash": previous_event_hash,
        "research_only": True,
        "execution_allowed": False,
    }
    envelope["event_hash"] = event_hash(envelope)
    try:
        _validate_event(envelope, previous_hash=previous_event_hash, line_number=1)
    except LedgerError:
        raise
    except (TypeError, ValueError) as exc:
        raise LedgerValidationError(str(exc), line_number=1) from exc
    return envelope


class AppendOnlyLedger:
    """A ledger whose construction is side-effect free and writes are explicit."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def read_bytes(self) -> bytes:
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return b""

    def replay(self) -> ReplayResult:
        return replay_ledger_bytes(self.read_bytes())

    def append(
        self,
        *,
        object_id: str,
        version_id: str,
        event_type: str,
        ontology_version: str,
        actor_id: str,
        actor_kind: str,
        recorded_at: str,
        payload: Mapping[str, Any],
        event_id: str | None = None,
    ) -> Mapping[str, Any]:
        # Validate all caller-controlled values before an absent file can be created.
        candidate = build_event(
            object_id=object_id,
            version_id=version_id,
            event_type=event_type,
            ontology_version=ontology_version,
            actor_id=actor_id,
            actor_kind=actor_kind,
            recorded_at=recorded_at,
            payload=payload,
            previous_event_hash=None,
            event_id=event_id,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                before = handle.read()
                replay = replay_ledger_bytes(before)
                candidate = build_event(
                    object_id=object_id,
                    version_id=version_id,
                    event_type=event_type,
                    ontology_version=ontology_version,
                    actor_id=actor_id,
                    actor_kind=actor_kind,
                    recorded_at=recorded_at,
                    payload=payload,
                    previous_event_hash=replay.head_hash,
                    event_id=candidate["event_id"],
                )
                encoded = canonical_json_bytes(candidate) + b"\n"
                # Validate the complete proposed ledger before touching its bytes.
                replay_ledger_bytes(before + encoded)
                handle.seek(0, os.SEEK_END)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                return candidate
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def append_record(
        self,
        record: ContractMixin,
        *,
        event_type: str,
        ontology_version: str,
        actor_id: str,
        actor_kind: str,
        recorded_at: str,
        event_id: str | None = None,
    ) -> Mapping[str, Any]:
        data = record.to_dict()
        data["record_type"] = type(record).__name__
        if isinstance(record, ClaimVersion):
            data["semantic_fingerprint"] = record.semantic_fingerprint
        object_id = data.get("object_id") or data.get("release_id")
        version_id = data.get("version_id")
        if not version_id and type(record).__name__ == "OntologyRelease":
            raise LedgerValidationError(
                "ontology_release_append_requires_explicit_opaque_version_id"
            )
        return self.append(
            object_id=object_id,
            version_id=version_id,
            event_type=event_type,
            ontology_version=ontology_version,
            actor_id=actor_id,
            actor_kind=actor_kind,
            recorded_at=recorded_at,
            payload=data,
            event_id=event_id,
        )


def encode_events(events: Sequence[Mapping[str, Any]]) -> bytes:
    raw = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
    replay_ledger_bytes(raw)
    return raw
