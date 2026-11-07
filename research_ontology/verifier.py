"""Independent raw-ledger verification for the Portfolio research ontology.

This module intentionally does not import the ontology writer, contracts, policy,
migration, or projection implementations.  It verifies raw JSONL bytes so a bug in
the production serializer or validators cannot automatically bless its own output.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from uuid import UUID


EVENT_SCHEMA = "research_ontology_ledger_event_v0"
VERIFICATION_SCHEMA = "research_ontology_ledger_verification_v0"
HASH_DOMAIN = b"research_ontology_ledger_event_v0\0"
ID_PREFIX = "urn:portfolio-research:"

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
ACTOR_FIELDS = frozenset({"actor_id", "actor_kind"})
ACTOR_KINDS = frozenset({"human", "agent", "system", "migration"})
CLAIM_KINDS = frozenset(
    {
        "structural",
        "association",
        "predictive",
        "causal",
        "proxy_adequacy",
        "economic_utility",
    }
)
EVIDENCE_VALUES = frozenset(
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
)
ADMISSIBILITY_VALUES = frozenset({"admissible", "inadmissible", "blocked"})
AXIS_VALUES = {
    "lifecycle": frozenset({"active", "superseded", "retracted"}),
    "evidence": EVIDENCE_VALUES,
    "authority": frozenset(
        {"agent_proposed", "legacy_import_unreviewed", "human_reviewed"}
    ),
    "decision": frozenset(
        {
            "pending",
            "kept",
            "rejected_exact",
            "retyped",
            "revision_requested",
            "deferred",
        }
    ),
    "freshness": frozenset({"not_applicable", "current", "expired", "unknown"}),
    "admissibility": ADMISSIBILITY_VALUES,
}
PROXY_USES = frozenset({"context", "screening", "control"})
MATERIAL_PROXY_SUBSTITUTIONS = frozenset(
    {"target", "causal", "entity", "geography", "outcome"}
)
ALLOWED_DERIVATION_RELATIONS = frozenset(
    {
        "version_of",
        "parent_of",
        "instantiates",
        "assesses",
        "references_artifact",
        "derived_from",
        "supersedes",
    }
)
FORBIDDEN_BARE_RELATIONS = frozenset(
    {
        "predicts",
        "causes",
        "supports",
        "contradicts",
        "refutes",
        "proxy_for",
        "same_as",
        "equivalent_to",
        "equivalence",
        "approved",
        "approval",
        "authority",
        "canonical",
        "execution_allowed",
    }
)
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_CLAIM_SEMANTIC_FIELDS = (
    "claim_kind",
    "proposition",
    "scope",
    "spec",
    "parent_claim_ids",
    "mechanism_ids",
)

_RELEASE_MACHINE_MEANING_FIELDS = (
    "terms",
    "derivation_rules",
    "lifecycle_values",
    "evidence_values",
    "authority_values",
    "decision_values",
    "freshness_values",
    "admissibility_values",
)


class _DuplicateJsonKey(ValueError):
    pass


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"nonfinite_json_number:{value}")


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("nonfinite_json_number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical_json_keys_must_be_strings")
            _validate_json_value(item)
        return
    raise TypeError(f"canonical_json_type_forbidden:{type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return the independent canonical JSON representation used for event hashes."""

    _validate_json_value(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_event_hash(event: Mapping[str, Any]) -> str:
    """Recompute an event hash from every envelope field except ``event_hash``."""

    core = {key: value for key, value in event.items() if key != "event_hash"}
    return hashlib.sha256(HASH_DOMAIN + canonical_json_bytes(core)).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _is_semver(value: Any) -> bool:
    return isinstance(value, str) and SEMVER_RE.fullmatch(value) is not None


def _release_core(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.split("-", 1)[0].split(".")
    return int(major), int(minor), int(patch)


def _release_prerelease(version: str) -> str | None:
    return version.split("-", 1)[1] if "-" in version else None


def _is_opaque_id(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith(ID_PREFIX):
        return False
    raw = value.removeprefix(ID_PREFIX)
    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError):
        return False
    return raw == str(parsed) and parsed.version == 4


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _event_is(event_type: Any, *names: str) -> bool:
    normalized = str(event_type or "").strip().lower()
    return normalized in names or any(
        normalized.startswith(f"{name}_") or normalized.endswith(f"_{name}")
        for name in names
    )


def _type_token(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _record_is(event: Mapping[str, Any], *names: str) -> bool:
    """Recognize semantic record type independently of the writer event label."""

    expected = {_type_token(name) for name in names}
    payload = event.get("payload")
    record_type = payload.get("record_type") if isinstance(payload, Mapping) else None
    if _type_token(record_type) in expected:
        return True
    event_token = _type_token(event.get("event_type"))
    return any(
        event_token == name or event_token.startswith(name) or event_token.endswith(name)
        for name in expected
    )


def _nonempty_mapping(value: Any) -> bool:
    return isinstance(value, Mapping) and bool(value)


def _nonempty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
        and len(set(value)) == len(value)
    )


def _contains_wildcard(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_wildcard(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_wildcard(item) for item in value)
    return value == "*"


def _semantic_edge_qualified(edge: Mapping[str, Any]) -> bool:
    qualification = edge.get("qualification")
    if not isinstance(qualification, Mapping):
        return False
    return (
        _is_opaque_id(qualification.get("claim_version_id"))
        and _nonempty_mapping(qualification.get("scope"))
        and _nonempty_string_list(qualification.get("provenance_refs"))
    )


class _Errors:
    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._keys: set[tuple[Any, ...]] = set()

    def add(
        self,
        code: str,
        *,
        line: int | None = None,
        event_id: Any = None,
        path: str | None = None,
        detail: Any = None,
    ) -> None:
        normalized_event_id = event_id if isinstance(event_id, str) else None
        detail_text = None if detail is None else str(detail)
        key = (line, normalized_event_id, code, path, detail_text)
        if key in self._keys:
            return
        self._keys.add(key)
        row: dict[str, Any] = {"code": code}
        if line is not None:
            row["line"] = line
        if normalized_event_id:
            row["event_id"] = normalized_event_id
        if path:
            row["path"] = path
        if detail_text is not None:
            row["detail"] = detail_text
        self._rows.append(row)

    def sorted(self) -> list[dict[str, Any]]:
        return sorted(
            self._rows,
            key=lambda row: (
                int(row.get("line", 0)),
                str(row.get("event_id", "")),
                str(row["code"]),
                str(row.get("path", "")),
                str(row.get("detail", "")),
            ),
        )


def _check_payload_tree(
    value: Any,
    *,
    errors: _Errors,
    line: int,
    event_id: Any,
    actor_kind: Any,
    root_record_type: str,
    path: tuple[str, ...] = ("payload",),
) -> None:
    if isinstance(value, Mapping):
        in_legacy = "legacy_annotations" in path
        is_root = path == ("payload",)
        typed_human_record = root_record_type in {
            _type_token("AxisReceipt"),
            _type_token("DispositionRecord"),
        }
        if not in_legacy:
            axes = value.get("axes")
            if axes is not None and not isinstance(axes, Mapping):
                errors.add(
                    "axes_must_be_mapping",
                    line=line,
                    event_id=event_id,
                    path=".".join((*path, "axes")),
                )
            elif isinstance(axes, Mapping):
                unknown_axes = sorted(set(axes) - set(AXIS_VALUES))
                if unknown_axes:
                    errors.add(
                        "unknown_axis_forbidden",
                        line=line,
                        event_id=event_id,
                        path=".".join((*path, "axes")),
                        detail=",".join(unknown_axes),
                    )
            for axis_name, allowed_values in AXIS_VALUES.items():
                direct = value.get(axis_name)
                nested = axes.get(axis_name) if isinstance(axes, Mapping) else None
                if direct is not None and nested is not None and direct != nested:
                    errors.add(
                        "axis_value_conflict",
                        line=line,
                        event_id=event_id,
                        path=".".join(path),
                        detail=axis_name,
                    )
                for selected in (direct, nested):
                    if selected is not None and selected not in allowed_values:
                        errors.add(
                            f"{axis_name}_axis_invalid",
                            line=line,
                            event_id=event_id,
                        )

            # DispositionRecord and AxisReceipt have dedicated validators for their
            # root human-authority declarations.  All other declarations, including
            # nested ones inside those records, are checked here.
            if not (is_root and typed_human_record):
                authority = value.get("authority")
                decision = value.get("decision")
                if isinstance(axes, Mapping):
                    authority = axes.get("authority", authority)
                    decision = axes.get("decision", decision)
                if authority == "human_reviewed" and actor_kind != "human":
                    errors.add(
                        "agent_generated_human_authority_forbidden",
                        line=line,
                        event_id=event_id,
                    )
                if decision not in (None, "pending") and actor_kind != "human":
                    errors.add(
                        "agent_generated_human_decision_forbidden",
                        line=line,
                        event_id=event_id,
                    )
        if "relation" in value and not in_legacy:
            relation = str(value.get("relation") or "").strip().lower()
            if relation in FORBIDDEN_BARE_RELATIONS and not _semantic_edge_qualified(value):
                errors.add(
                    "unqualified_forbidden_semantic_edge",
                    line=line,
                    event_id=event_id,
                    path=".".join(path),
                    detail=relation,
                )
            if value.get("derived") is True:
                if relation not in ALLOWED_DERIVATION_RELATIONS:
                    errors.add(
                        "derived_relation_default_denied",
                        line=line,
                        event_id=event_id,
                        path=".".join(path),
                        detail=relation,
                    )
                if value.get("deterministic") is not True:
                    errors.add(
                        "derived_relation_must_be_deterministic",
                        line=line,
                        event_id=event_id,
                        path=".".join(path),
                    )
                if not (
                    isinstance(value.get("rule_id"), str)
                    and bool(value["rule_id"].strip())
                    and _is_semver(value.get("rule_version"))
                    and _nonempty_string_list(value.get("provenance_refs"))
                ):
                    errors.add(
                        "derived_relation_complete_provenance_required",
                        line=line,
                        event_id=event_id,
                        path=".".join(path),
                    )
        for key, item in value.items():
            key_text = str(key)
            item_path = (*path, key_text)
            dotted = ".".join(item_path)
            if key_text == "status" and "legacy_annotations" not in path:
                errors.add(
                    "universal_status_forbidden",
                    line=line,
                    event_id=event_id,
                    path=dotted,
                )
            if key_text == "research_only" and item is not True:
                errors.add(
                    "nested_research_boundary_invalid",
                    line=line,
                    event_id=event_id,
                    path=dotted,
                )
            if key_text == "execution_allowed" and item is not False:
                errors.add(
                    "nested_execution_boundary_invalid",
                    line=line,
                    event_id=event_id,
                    path=dotted,
                )
            if key_text in {"can_affect_trading", "is_trading_signal"} and item is True:
                errors.add(
                    "trading_authority_forbidden",
                    line=line,
                    event_id=event_id,
                    path=dotted,
                )
            _check_payload_tree(
                item,
                errors=errors,
                line=line,
                event_id=event_id,
                actor_kind=actor_kind,
                root_record_type=root_record_type,
                path=item_path,
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_payload_tree(
                item,
                errors=errors,
                line=line,
                event_id=event_id,
                actor_kind=actor_kind,
                root_record_type=root_record_type,
                path=(*path, str(index)),
            )


def _check_claim(
    event: Mapping[str, Any],
    *,
    errors: _Errors,
    line: int,
    claim_semantics: dict[str, str],
) -> None:
    payload = event["payload"]
    event_id = event.get("event_id")
    claim_kind = payload.get("claim_kind")
    if claim_kind not in CLAIM_KINDS:
        errors.add("claim_kind_invalid", line=line, event_id=event_id)
    missing = [field for field in _CLAIM_SEMANTIC_FIELDS if field not in payload]
    if missing:
        errors.add(
            "claim_semantic_envelope_incomplete",
            line=line,
            event_id=event_id,
            detail=",".join(missing),
        )
        return
    core = {field: payload[field] for field in _CLAIM_SEMANTIC_FIELDS}
    fingerprint = hashlib.sha256(
        b"claim_semantic_fingerprint_v0\0" + canonical_json_bytes(core)
    ).hexdigest()
    supplied_fingerprint = payload.get("semantic_fingerprint")
    if not _is_sha256(supplied_fingerprint):
        errors.add(
            "claim_semantic_fingerprint_required",
            line=line,
            event_id=event_id,
        )
    elif supplied_fingerprint != fingerprint:
        errors.add(
            "claim_semantic_fingerprint_mismatch",
            line=line,
            event_id=event_id,
        )
    object_id = str(event.get("object_id") or "")
    previous = claim_semantics.get(object_id)
    if previous is not None and previous != fingerprint:
        errors.add(
            "claim_semantic_change_requires_new_object",
            line=line,
            event_id=event_id,
        )
    claim_semantics.setdefault(object_id, fingerprint)


def _check_release(
    event: Mapping[str, Any],
    *,
    errors: _Errors,
    line: int,
    release_versions: dict[str, str],
    term_by_id: dict[str, str],
    term_key_to_id: dict[str, str],
    release_history: list[dict[str, Any]],
) -> None:
    payload = event["payload"]
    event_id = event.get("event_id")
    version = payload.get("version")
    if not _is_semver(version):
        errors.add("ontology_release_version_invalid", line=line, event_id=event_id)
    elif version != event.get("ontology_version"):
        errors.add("ontology_release_version_mismatch", line=line, event_id=event_id)
    terms = payload.get("terms")
    if not isinstance(terms, list) or not terms:
        errors.add("ontology_terms_required", line=line, event_id=event_id)
        return
    try:
        release_hash = hashlib.sha256(
            b"ontology_release_machine_meaning_v0\0"
            + canonical_json_bytes(
                {field: payload.get(field) for field in _RELEASE_MACHINE_MEANING_FIELDS}
            )
        ).hexdigest()
    except (TypeError, ValueError, UnicodeError):
        errors.add("ontology_terms_invalid", line=line, event_id=event_id)
        return
    release_reused = isinstance(version, str) and version in release_versions
    if release_reused:
        code = (
            "ontology_release_version_rewrite"
            if release_versions[version] != release_hash
            else "ontology_release_version_reused"
        )
        errors.add(code, line=line, event_id=event_id)
        return

    local_ids: set[str] = set()
    local_keys: set[str] = set()
    current_terms: dict[str, str] = {}
    specific_term_violation = False
    for index, term in enumerate(terms):
        path = f"payload.terms.{index}"
        if not isinstance(term, Mapping):
            errors.add("ontology_term_invalid", line=line, event_id=event_id, path=path)
            continue
        term_id = term.get("term_id")
        term_key = term.get("term_key")
        definition = term.get("definition")
        if not _is_opaque_id(term_id):
            errors.add("ontology_term_id_invalid", line=line, event_id=event_id, path=path)
            continue
        if not isinstance(term_key, str) or not term_key.strip() or not isinstance(definition, str) or not definition.strip():
            errors.add("ontology_term_content_incomplete", line=line, event_id=event_id, path=path)
            continue
        if term_id in local_ids or term_key in local_keys:
            errors.add("ontology_release_duplicate_term", line=line, event_id=event_id, path=path)
        local_ids.add(term_id)
        local_keys.add(term_key)
        term_hash = hashlib.sha256(
            b"research_ontology_term_v0\0" + canonical_json_bytes(term)
        ).hexdigest()
        current_terms[str(term_id)] = term_hash
        if term_id in term_by_id and term_by_id[term_id] != term_hash:
            specific_term_violation = True
            errors.add(
                "ontology_term_rewrite_forbidden",
                line=line,
                event_id=event_id,
                path=path,
            )
        else:
            term_by_id.setdefault(term_id, term_hash)
        if term_key in term_key_to_id and term_key_to_id[term_key] != term_id:
            specific_term_violation = True
            errors.add(
                "ontology_term_key_rebound",
                line=line,
                event_id=event_id,
                path=path,
            )
        else:
            term_key_to_id.setdefault(term_key, term_id)

    rules = payload.get("derivation_rules")
    current_rules: dict[str, str] = {}
    if not isinstance(rules, list) or not rules:
        errors.add(
            "ontology_derivation_rules_required",
            line=line,
            event_id=event_id,
        )
    else:
        for index, rule in enumerate(rules):
            path = f"payload.derivation_rules.{index}"
            if not isinstance(rule, Mapping):
                errors.add(
                    "ontology_derivation_rule_invalid",
                    line=line,
                    event_id=event_id,
                    path=path,
                )
                continue
            rule_id = rule.get("rule_id")
            relation = rule.get("relation")
            valid_rule = (
                isinstance(rule_id, str)
                and bool(rule_id.strip())
                and relation in ALLOWED_DERIVATION_RELATIONS
                and _is_semver(rule.get("version"))
                and rule.get("deterministic") is True
                and rule.get("provenance_required") is True
                and rule.get("semantic_authority_added") is False
                and rule.get("transitive") is False
            )
            if relation not in ALLOWED_DERIVATION_RELATIONS:
                errors.add(
                    "ontology_derivation_relation_default_denied",
                    line=line,
                    event_id=event_id,
                    path=path,
                )
            elif not valid_rule:
                errors.add(
                    "ontology_derivation_rule_invalid",
                    line=line,
                    event_id=event_id,
                    path=path,
                )
            if not isinstance(rule_id, str) or not rule_id.strip():
                continue
            rule_hash = hashlib.sha256(
                b"research_ontology_derivation_rule_v0\0"
                + canonical_json_bytes(rule)
            ).hexdigest()
            if rule_id in current_rules:
                errors.add(
                    "ontology_derivation_rule_id_reuse",
                    line=line,
                    event_id=event_id,
                    path=path,
                )
            else:
                current_rules[rule_id] = rule_hash

    if not isinstance(version, str) or not _is_semver(version):
        return
    release_versions[version] = release_hash
    current_core = _release_core(version)
    current_prerelease = _release_prerelease(version)
    if release_history:
        previous = release_history[-1]
        previous_core = previous["core"]
        if current_core < previous_core:
            errors.add("ontology_release_order_invalid", line=line, event_id=event_id)
        elif current_core == previous_core:
            if previous["prerelease"] is None or current_prerelease is not None:
                errors.add("ontology_release_order_invalid", line=line, event_id=event_id)
            elif release_hash != previous["signature"]:
                errors.add("ontology_release_freeze_mismatch", line=line, event_id=event_id)
        elif current_core[:2] == previous_core[:2]:
            if release_hash != previous["signature"]:
                errors.add(
                    "ontology_patch_meaning_change_forbidden",
                    line=line,
                    event_id=event_id,
                )
        elif current_core[0] == previous_core[0]:
            if current_core[1] <= previous_core[1] or current_core[2] != 0:
                errors.add("ontology_release_order_invalid", line=line, event_id=event_id)
            else:
                additive = all(
                    current_terms.get(term_id) == term_hash
                    for term_id, term_hash in previous["terms"].items()
                ) and all(
                    current_rules.get(rule_id) == rule_hash
                    for rule_id, rule_hash in previous["rules"].items()
                )
                if not additive and not specific_term_violation:
                    errors.add(
                        "ontology_minor_must_be_additive",
                        line=line,
                        event_id=event_id,
                    )
    release_history.append(
        {
            "version": version,
            "core": current_core,
            "prerelease": current_prerelease,
            "signature": release_hash,
            "terms": current_terms,
            "rules": current_rules,
        }
    )


def _check_evidence(
    event: Mapping[str, Any], *, errors: _Errors, line: int
) -> None:
    payload = event["payload"]
    event_id = event.get("event_id")
    evidence = payload.get("evidence")
    admissibility = payload.get("admissibility")
    if evidence not in EVIDENCE_VALUES:
        errors.add("evidence_axis_invalid", line=line, event_id=event_id)
    if admissibility not in ADMISSIBILITY_VALUES:
        errors.add("admissibility_axis_invalid", line=line, event_id=event_id)
    if evidence == "blocked_by_data" and admissibility != "blocked":
        errors.add(
            "blocked_data_requires_blocked_admissibility",
            line=line,
            event_id=event_id,
        )
    if admissibility == "blocked" and evidence in {
        "supported_in_scope",
        "contradicted_in_scope",
    }:
        errors.add(
            "blocked_admissibility_is_not_support_or_contradiction",
            line=line,
            event_id=event_id,
        )
    elif admissibility == "blocked" and evidence not in {None, "blocked_by_data"}:
        errors.add(
            "blocked_admissibility_is_not_negative_evidence",
            line=line,
            event_id=event_id,
        )
    if evidence in {"supported_in_scope", "contradicted_in_scope"} and admissibility != "admissible":
        # Keep the locked blocked-admissibility case single-coded while rejecting
        # every other inadmissible support/contradiction declaration.
        if admissibility != "blocked":
            errors.add(
                "support_or_contradiction_requires_admissible_evidence",
                line=line,
                event_id=event_id,
            )
    if (
        admissibility == "admissible"
        and evidence in {"supported_in_scope", "contradicted_in_scope", "mixed"}
        and not payload.get("artifact_refs")
    ):
        errors.add(
            "admissible_assessment_artifact_refs_required",
            line=line,
            event_id=event_id,
        )
    if payload.get("evidence_basis") == "proxy_only" and evidence in {
        "supported_in_scope",
        "contradicted_in_scope",
    }:
        errors.add(
            "proxy_only_evidence_cannot_promote_exact_claim",
            line=line,
            event_id=event_id,
        )
    negative_or_positive = {
        "support",
        "supports",
        "positive_evidence",
        "contradiction",
        "contradicts",
        "negative_evidence",
    }
    effect = str(payload.get("evidence_effect") or "").strip().lower()
    paired = (
        effect in negative_or_positive
        or payload.get("supports") is True
        or payload.get("contradicts") is True
    )
    if evidence == "blocked_by_data" and paired:
        errors.add(
            "blocked_data_is_not_support_or_contradiction",
            line=line,
            event_id=event_id,
        )


def _check_artifact(
    event: Mapping[str, Any], *, errors: _Errors, line: int
) -> None:
    payload = event["payload"]
    event_id = event.get("event_id")
    required = (
        "source_identity",
        "timing",
        "rights",
        "scope",
        "revision",
        "missingness",
    )
    missing = [name for name in required if not _nonempty_mapping(payload.get(name))]
    if missing:
        errors.add(
            "artifact_evidence_envelope_incomplete",
            line=line,
            event_id=event_id,
            detail=",".join(missing),
        )
    artifact_hash = payload.get("sha256")
    if artifact_hash is not None and not _is_sha256(artifact_hash):
        errors.add("artifact_sha256_invalid", line=line, event_id=event_id)


def _check_disposition(
    event: Mapping[str, Any], *, errors: _Errors, line: int
) -> None:
    payload = event["payload"]
    event_id = event.get("event_id")
    actor = event.get("actor")
    if not isinstance(actor, Mapping) or actor.get("actor_kind") != "human":
        errors.add("disposition_requires_human_actor", line=line, event_id=event_id)
    reviewer_id = payload.get("reviewer_id")
    if (
        isinstance(actor, Mapping)
        and isinstance(reviewer_id, str)
        and actor.get("actor_id") != reviewer_id
    ):
        errors.add(
            "disposition_actor_reviewer_mismatch", line=line, event_id=event_id
        )
    if payload.get("authority") != "human_reviewed":
        errors.add("disposition_requires_human_authority", line=line, event_id=event_id)
    if payload.get("decision") in {None, "", "pending"}:
        errors.add("human_disposition_cannot_be_pending", line=line, event_id=event_id)
    required = (
        "target_object_id",
        "target_version_id",
        "reviewer_id",
        "rationale",
        "decision_at",
    )
    if any(not payload.get(name) for name in required) or not (
        _is_opaque_id(payload.get("target_object_id"))
        and _is_opaque_id(payload.get("target_version_id"))
        and _parse_timestamp(payload.get("decision_at")) is not None
    ):
        errors.add("disposition_exact_binding_required", line=line, event_id=event_id)
    scope = payload.get("scope")
    if not _nonempty_mapping(scope):
        errors.add("disposition_scope_required", line=line, event_id=event_id)
    elif _contains_wildcard(scope):
        errors.add("disposition_scope_wildcards_forbidden", line=line, event_id=event_id)


def _check_axis_receipt(
    event: Mapping[str, Any], *, errors: _Errors, line: int
) -> None:
    payload = event["payload"]
    event_id = event.get("event_id")
    axis_name = payload.get("axis_name")
    axis_value = payload.get("axis_value")
    if axis_name not in AXIS_VALUES or axis_value not in AXIS_VALUES.get(axis_name, ()):
        errors.add("axis_receipt_value_invalid", line=line, event_id=event_id)
    actor = event.get("actor")
    actor_kind = actor.get("actor_kind") if isinstance(actor, Mapping) else None
    if axis_name == "authority" and axis_value == "human_reviewed" and actor_kind != "human":
        errors.add(
            "agent_generated_human_authority_forbidden",
            line=line,
            event_id=event_id,
        )
    if axis_name == "decision" and axis_value != "pending" and actor_kind != "human":
        errors.add(
            "agent_generated_human_decision_forbidden",
            line=line,
            event_id=event_id,
        )
    if axis_name == "evidence" and axis_value in {
        "supported_in_scope",
        "contradicted_in_scope",
    }:
        errors.add(
            "support_or_contradiction_requires_evidence_assessment",
            line=line,
            event_id=event_id,
        )
    if not (
        _is_opaque_id(payload.get("target_object_id"))
        and _is_opaque_id(payload.get("target_version_id"))
    ):
        errors.add("axis_receipt_exact_binding_required", line=line, event_id=event_id)
    scope = payload.get("scope")
    if not _nonempty_mapping(scope) or _contains_wildcard(scope):
        errors.add("axis_receipt_scope_invalid", line=line, event_id=event_id)


def _check_proxy(
    event: Mapping[str, Any], *, errors: _Errors, line: int
) -> None:
    payload = event["payload"]
    event_id = event.get("event_id")
    if _record_is(event, "ProxyBinding"):
        permitted = payload.get("permitted_uses")
        if (
            not isinstance(permitted, list)
            or not permitted
            or any(value not in PROXY_USES for value in permitted)
            or len(set(permitted)) != len(permitted)
        ):
            errors.add("proxy_permitted_uses_invalid", line=line, event_id=event_id)
    requested = payload.get("requested_use")
    outcome = str(
        payload.get("proxy_gate")
        or payload.get("outcome")
        or payload.get("decision")
        or ""
    ).lower()
    if requested in MATERIAL_PROXY_SUBSTITUTIONS and outcome in {
        "preapproved",
        "approved",
        "allow",
        "allowed",
    }:
        errors.add(
            "material_proxy_substitution_requires_review",
            line=line,
            event_id=event_id,
            detail=requested,
        )


def _check_inference(
    event: Mapping[str, Any], *, errors: _Errors, line: int
) -> None:
    payload = event["payload"]
    event_id = event.get("event_id")
    relation = payload.get("relation")
    if relation not in ALLOWED_DERIVATION_RELATIONS:
        errors.add(
            "inference_relation_default_denied",
            line=line,
            event_id=event_id,
            detail=relation,
        )
    if payload.get("deterministic") is not True:
        errors.add("inference_must_be_deterministic", line=line, event_id=event_id)
    provenance_ok = (
        isinstance(payload.get("rule_id"), str)
        and bool(payload["rule_id"].strip())
        and _is_semver(payload.get("rule_version"))
        and _nonempty_string_list(payload.get("source_ids"))
        and _nonempty_string_list(payload.get("target_ids"))
    )
    if not provenance_ok:
        errors.add(
            "inference_complete_provenance_required", line=line, event_id=event_id
        )
    for name in ("input_sha256", "output_sha256", "implementation_sha256"):
        if not _is_sha256(payload.get(name)):
            errors.add(
                "inference_provenance_hash_invalid",
                line=line,
                event_id=event_id,
                path=f"payload.{name}",
            )


def _check_event_semantics(
    event: Mapping[str, Any],
    *,
    errors: _Errors,
    line: int,
    claim_semantics: dict[str, str],
    release_versions: dict[str, str],
    term_by_id: dict[str, str],
    term_key_to_id: dict[str, str],
    release_history: list[dict[str, Any]],
) -> None:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return
    if _record_is(event, "ClaimVersion"):
        _check_claim(
            event, errors=errors, line=line, claim_semantics=claim_semantics
        )
    if _record_is(event, "OntologyRelease"):
        _check_release(
            event,
            errors=errors,
            line=line,
            release_versions=release_versions,
            term_by_id=term_by_id,
            term_key_to_id=term_key_to_id,
            release_history=release_history,
        )
    if _record_is(event, "EvidenceAssessment") or {
        "evidence",
        "admissibility",
    } <= set(payload):
        _check_evidence(event, errors=errors, line=line)
    if _record_is(event, "ArtifactReference"):
        _check_artifact(event, errors=errors, line=line)
    if _record_is(event, "Disposition", "DispositionRecord"):
        _check_disposition(event, errors=errors, line=line)
    if _record_is(event, "AxisReceipt"):
        _check_axis_receipt(event, errors=errors, line=line)
    if _record_is(event, "ProxyBinding", "ProxyGateDecision") or "requested_use" in payload:
        _check_proxy(event, errors=errors, line=line)
    if _record_is(event, "Inference", "InferenceReceipt", "Derivation", "DerivedRelation"):
        _check_inference(event, errors=errors, line=line)


def verify_ledger_bytes(raw: bytes) -> dict[str, Any]:
    """Verify raw JSONL bytes without consulting production ontology code."""

    errors = _Errors()
    ledger_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        errors.add("invalid_utf8", line=exc.start + 1)
        return {
            "schema": VERIFICATION_SCHEMA,
            "valid": False,
            "event_count": 0,
            "head_hash": None,
            "ledger_sha256": ledger_sha256,
            "errors": errors.sorted(),
        }

    lines = text.splitlines()
    if raw and not raw.endswith(b"\n"):
        errors.add("ledger_missing_final_newline")
    events: list[tuple[int, Mapping[str, Any]]] = []
    for line_number, line_text in enumerate(lines, start=1):
        if not line_text.strip():
            errors.add("blank_jsonl_line", line=line_number)
            continue
        try:
            parsed = json.loads(
                line_text,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
            _validate_json_value(parsed)
        except _DuplicateJsonKey as exc:
            errors.add("duplicate_json_key", line=line_number, detail=str(exc))
            continue
        except (json.JSONDecodeError, TypeError, ValueError, UnicodeError) as exc:
            errors.add("invalid_json", line=line_number, detail=type(exc).__name__)
            continue
        if not isinstance(parsed, Mapping):
            errors.add("event_must_be_object", line=line_number)
            continue
        events.append((line_number, parsed))

    seen_event_ids: set[str] = set()
    seen_version_ids: set[str] = set()
    previous_hash: str | None = None
    previous_recorded_at: datetime | None = None
    claim_semantics: dict[str, str] = {}
    object_record_types: dict[str, str] = {}
    release_versions: dict[str, str] = {}
    term_by_id: dict[str, str] = {}
    term_key_to_id: dict[str, str] = {}
    release_history: list[dict[str, Any]] = []
    version_owners: dict[str, str] = {}
    version_lifecycle: dict[str, str] = {}
    pending_exact_targets: list[tuple[int, Any, str, str]] = []
    pending_assessment_targets: list[tuple[int, Any, str]] = []
    pending_lifecycle_updates: list[tuple[int, Any, str, str]] = []
    head_hash: str | None = None

    for index, (line_number, event) in enumerate(events):
        event_id = event.get("event_id")
        missing = sorted(ENVELOPE_FIELDS - set(event))
        unknown = sorted(set(event) - ENVELOPE_FIELDS)
        if missing:
            errors.add(
                "envelope_missing_fields",
                line=line_number,
                event_id=event_id,
                detail=",".join(missing),
            )
        if unknown:
            errors.add(
                "envelope_unknown_fields",
                line=line_number,
                event_id=event_id,
                detail=",".join(unknown),
            )
        if event.get("schema") != EVENT_SCHEMA:
            errors.add("event_schema_invalid", line=line_number, event_id=event_id)

        for name in ("event_id", "object_id", "version_id"):
            value = event.get(name)
            if not _is_opaque_id(value):
                errors.add(
                    f"{name}_invalid", line=line_number, event_id=event_id
                )
        if isinstance(event_id, str):
            if event_id in seen_event_ids:
                errors.add("duplicate_event_id", line=line_number, event_id=event_id)
            seen_event_ids.add(event_id)
        version_id = event.get("version_id")
        if isinstance(version_id, str):
            if version_id in seen_version_ids:
                errors.add("duplicate_version_id", line=line_number, event_id=event_id)
            seen_version_ids.add(version_id)

        if not isinstance(event.get("event_type"), str) or not str(
            event.get("event_type")
        ).strip():
            errors.add("event_type_required", line=line_number, event_id=event_id)
        if not _is_semver(event.get("ontology_version")):
            errors.add("ontology_version_invalid", line=line_number, event_id=event_id)

        actor = event.get("actor")
        if not isinstance(actor, Mapping):
            errors.add("actor_invalid", line=line_number, event_id=event_id)
        else:
            actor_missing = sorted(ACTOR_FIELDS - set(actor))
            actor_unknown = sorted(set(actor) - ACTOR_FIELDS)
            if actor_missing or actor_unknown:
                errors.add(
                    "actor_envelope_invalid",
                    line=line_number,
                    event_id=event_id,
                    detail=f"missing={','.join(actor_missing)};unknown={','.join(actor_unknown)}",
                )
            if not isinstance(actor.get("actor_id"), str) or not actor.get(
                "actor_id", ""
            ).strip():
                errors.add("actor_id_required", line=line_number, event_id=event_id)
            if actor.get("actor_kind") not in ACTOR_KINDS:
                errors.add("actor_kind_invalid", line=line_number, event_id=event_id)

        recorded_at = _parse_timestamp(event.get("recorded_at"))
        if recorded_at is None:
            errors.add("recorded_at_invalid", line=line_number, event_id=event_id)
        elif previous_recorded_at is not None and recorded_at < previous_recorded_at:
            errors.add("recorded_at_order_invalid", line=line_number, event_id=event_id)
        if recorded_at is not None:
            previous_recorded_at = recorded_at

        payload = event.get("payload")
        if not _nonempty_mapping(payload):
            errors.add("payload_must_be_nonempty_object", line=line_number, event_id=event_id)
        else:
            record_type = payload.get("record_type")
            if not isinstance(record_type, str) or not record_type.strip():
                errors.add(
                    "payload_record_type_required",
                    line=line_number,
                    event_id=event_id,
                )
            else:
                object_id = event.get("object_id")
                if isinstance(object_id, str):
                    normalized_type = _type_token(record_type)
                    previous_type = object_record_types.get(object_id)
                    if previous_type is not None and previous_type != normalized_type:
                        errors.add(
                            "object_type_reuse_forbidden",
                            line=line_number,
                            event_id=event_id,
                        )
                    object_record_types.setdefault(object_id, normalized_type)
            for identity_name in ("object_id", "version_id"):
                if identity_name in payload and payload[identity_name] != event.get(identity_name):
                    errors.add(
                        "payload_identity_mismatch",
                        line=line_number,
                        event_id=event_id,
                        path=f"payload.{identity_name}",
                    )
            if payload.get("research_only") is not True:
                errors.add(
                    "nested_research_boundary_invalid",
                    line=line_number,
                    event_id=event_id,
                    path="payload.research_only",
                )
            if payload.get("execution_allowed") is not False:
                errors.add(
                    "nested_execution_boundary_invalid",
                    line=line_number,
                    event_id=event_id,
                    path="payload.execution_allowed",
                )
            _check_payload_tree(
                payload,
                errors=errors,
                line=line_number,
                event_id=event_id,
                actor_kind=(actor.get("actor_kind") if isinstance(actor, Mapping) else None),
                root_record_type=_type_token(record_type),
            )

            if _record_is(
                event,
                "AxisReceipt",
                "DispositionRecord",
                "AmbiguityPacket",
                "AxisAssessment",
            ):
                target_object_id = str(payload.get("target_object_id") or "")
                target_version_id = str(payload.get("target_version_id") or "")
                pending_exact_targets.append(
                    (line_number, event_id, target_object_id, target_version_id)
                )
                requested_lifecycle = None
                axes = payload.get("axes")
                if isinstance(axes, Mapping) and "lifecycle" in axes:
                    requested_lifecycle = axes.get("lifecycle")
                elif "lifecycle" in payload:
                    requested_lifecycle = payload.get("lifecycle")
                if (
                    _record_is(event, "AxisReceipt")
                    and payload.get("axis_name") == "lifecycle"
                ):
                    requested_lifecycle = payload.get("axis_value")
                if requested_lifecycle is not None:
                    pending_lifecycle_updates.append(
                        (
                            line_number,
                            event_id,
                            target_version_id,
                            str(requested_lifecycle),
                        )
                    )

            if _record_is(event, "EvidenceAssessment"):
                pending_assessment_targets.append(
                    (
                        line_number,
                        event_id,
                        str(payload.get("claim_version_id") or ""),
                    )
                )

        if event.get("research_only") is not True:
            errors.add("research_only_must_be_true", line=line_number, event_id=event_id)
        if event.get("execution_allowed") is not False:
            errors.add(
                "execution_allowed_must_be_false", line=line_number, event_id=event_id
            )

        supplied_previous = event.get("previous_event_hash")
        if index == 0:
            if supplied_previous is not None:
                errors.add(
                    "first_event_previous_hash_must_be_null",
                    line=line_number,
                    event_id=event_id,
                )
        else:
            if not _is_sha256(supplied_previous):
                errors.add(
                    "previous_event_hash_invalid",
                    line=line_number,
                    event_id=event_id,
                )
            elif supplied_previous != previous_hash:
                errors.add(
                    "previous_event_hash_mismatch",
                    line=line_number,
                    event_id=event_id,
                )

        supplied_hash = event.get("event_hash")
        if not _is_sha256(supplied_hash):
            errors.add("event_hash_invalid", line=line_number, event_id=event_id)
            current_hash = None
        else:
            try:
                expected_hash = compute_event_hash(event)
            except (TypeError, ValueError, UnicodeError):
                errors.add(
                    "event_hash_basis_invalid", line=line_number, event_id=event_id
                )
                current_hash = None
            else:
                if supplied_hash != expected_hash:
                    errors.add(
                        "event_hash_mismatch", line=line_number, event_id=event_id
                    )
                current_hash = supplied_hash
                head_hash = supplied_hash
        previous_hash = current_hash

        if _nonempty_mapping(payload):
            try:
                _check_event_semantics(
                    event,
                    errors=errors,
                    line=line_number,
                    claim_semantics=claim_semantics,
                    release_versions=release_versions,
                    term_by_id=term_by_id,
                    term_key_to_id=term_key_to_id,
                    release_history=release_history,
                )
            except (TypeError, ValueError, UnicodeError) as exc:
                errors.add(
                    "semantic_verification_input_invalid",
                    line=line_number,
                    event_id=event_id,
                    detail=type(exc).__name__,
                )

        object_id = event.get("object_id")
        version_id = event.get("version_id")
        if isinstance(version_id, str) and isinstance(object_id, str):
            version_owners.setdefault(version_id, object_id)
            initial_lifecycle: Any = None
            if isinstance(payload, Mapping):
                axes = payload.get("axes")
                if isinstance(axes, Mapping) and "lifecycle" in axes:
                    initial_lifecycle = axes.get("lifecycle")
                elif "lifecycle" in payload:
                    initial_lifecycle = payload.get("lifecycle")
            version_lifecycle.setdefault(
                version_id,
                initial_lifecycle
                if initial_lifecycle in AXIS_VALUES["lifecycle"]
                else "active",
            )

    for line_number, event_id, target_object_id, target_version_id in pending_exact_targets:
        owner = version_owners.get(target_version_id)
        if owner is None:
            errors.add(
                "exact_target_version_not_found",
                line=line_number,
                event_id=event_id,
            )
        elif owner != target_object_id:
            errors.add(
                "exact_target_object_version_mismatch",
                line=line_number,
                event_id=event_id,
            )

    for line_number, event_id, target_version_id in pending_assessment_targets:
        if target_version_id not in version_owners:
            errors.add(
                "assessment_target_version_not_found",
                line=line_number,
                event_id=event_id,
            )

    for line_number, event_id, target_version_id, requested in pending_lifecycle_updates:
        previous = version_lifecycle.get(target_version_id)
        if previous is None or requested not in AXIS_VALUES["lifecycle"]:
            continue
        if requested == previous:
            errors.add(
                "lifecycle_receipt_must_change_value",
                line=line_number,
                event_id=event_id,
            )
        elif previous != "active" or requested not in {"superseded", "retracted"}:
            errors.add(
                "lifecycle_transition_forbidden",
                line=line_number,
                event_id=event_id,
                detail=f"previous={previous};requested={requested}",
            )
        else:
            version_lifecycle[target_version_id] = requested

    rows = errors.sorted()
    return {
        "schema": VERIFICATION_SCHEMA,
        "valid": not rows,
        "event_count": len(events),
        "head_hash": head_hash,
        "ledger_sha256": ledger_sha256,
        "errors": rows,
    }


def verify_ledger_path(path: str | Path) -> dict[str, Any]:
    return verify_ledger_bytes(Path(path).read_bytes())


__all__ = [
    "EVENT_SCHEMA",
    "HASH_DOMAIN",
    "VERIFICATION_SCHEMA",
    "canonical_json_bytes",
    "compute_event_hash",
    "verify_ledger_bytes",
    "verify_ledger_path",
]
