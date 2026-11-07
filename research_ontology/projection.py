"""Deterministic, research-only projections over replayed ontology events.

The ledger remains authoritative.  This module deliberately emits only a
rebuildable structural graph and a bounded, allowlisted Tier-1 context view.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .contracts import canonical_json, canonical_sha256, require_iso
from .policy import DERIVATION_RELATIONS, FORBIDDEN_BARE_RELATIONS


PROJECTION_SCHEMA_VERSION = "0.1.0"
DEFAULT_MAX_RECORDS = 50
DEFAULT_MAX_BYTES = 65_536

_AXIS_VALUES = {
    "lifecycle": frozenset({"active", "superseded", "retracted"}),
    "evidence": frozenset(
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
    "admissibility": frozenset({"admissible", "inadmissible", "blocked"}),
}
_TIME_FIELDS = (
    "recorded_at",
    "effective_at",
    "assessed_at",
    "decision_at",
    "released_at",
    "completed_at",
    "frozen_at",
    "created_at",
    "started_at",
)
_OBJECT_ID_FIELDS = {
    "RunReference": "run_id",
    "WorkflowMethodSpec": "method_id",
    "VerificationSpec": "verification_id",
    "EvaluationSpec": "evaluation_id",
    "WorkflowSkillBinding": "skill_id",
    "OntologyRelease": "release_id",
}
_RECORD_TYPE_ALIASES = {
    "mechanism": "MechanismRecord",
    "mechanism_record": "MechanismRecord",
    "claim": "ClaimVersion",
    "claim_version": "ClaimVersion",
    "hypothesis": "HypothesisRecord",
    "hypothesis_record": "HypothesisRecord",
    "experiment": "ExperimentSpec",
    "experiment_spec": "ExperimentSpec",
    "run": "RunReference",
    "run_reference": "RunReference",
    "artifact": "ArtifactReference",
    "artifact_reference": "ArtifactReference",
    "evidence_assessment": "EvidenceAssessment",
    "proxy_binding": "ProxyBinding",
    "disposition": "DispositionRecord",
    "disposition_record": "DispositionRecord",
    "ambiguity": "AmbiguityPacket",
    "ambiguity_packet": "AmbiguityPacket",
    "axis_assessment": "AxisAssessment",
    "axis_receipt": "AxisReceipt",
    "ontology_release": "OntologyRelease",
}
_FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "raw",
        "raw_body",
        "raw_bodies",
        "body",
        "bodies",
        "content",
        "log",
        "logs",
        "raw_log",
        "raw_logs",
        "sample",
        "samples",
        "sample_rows",
        "raw_sample",
        "raw_samples",
        "secret",
        "secrets",
        "credential",
        "credentials",
        "api_key",
        "access_token",
        "refresh_token",
        "private_key",
        "broker",
        "broker_state",
        "trading",
        "trade",
        "trades",
        "order",
        "orders",
        "position",
        "positions",
        "hidden_reasoning",
        "chain_of_thought",
        "scratchpad",
    }
)

# These triples mirror the immutable derivation rules in ontology release
# 0.1.0. Projection is intentionally not allowed to mint a convenient local
# rule name: an emitted edge must bind the exact registered rule and version.
_REGISTERED_DERIVATION_RULES: dict[str, tuple[str, str]] = {
    "version_of": ("version_identity_v0", "0.1.0"),
    "parent_of": ("parent_reference_v0", "0.1.0"),
    "instantiates": ("claim_instantiation_v0", "0.1.0"),
    "assesses": ("assessment_target_v0", "0.1.0"),
    "references_artifact": ("artifact_reference_v0", "0.1.0"),
    "derived_from": ("projection_provenance_v0", "0.1.0"),
    "supersedes": ("version_supersession_v0", "0.1.0"),
}

# Tier-1 context is a positive projection, not a recursively filtered copy of
# source payloads. Unknown keys are dropped even when they have innocuous
# names such as ``document`` or ``text``.
_TIER1_SCOPE_KEYS = frozenset(
    {
        "applies_to",
        "asset",
        "asset_class",
        "asset_ids",
        "baseline",
        "benchmark",
        "claim_version_id",
        "commodity",
        "commodity_chain",
        "control",
        "controls",
        "cost_model",
        "costs",
        "currency",
        "effective_end",
        "effective_start",
        "end_at",
        "entities",
        "entity",
        "forecast_origin",
        "geography",
        "horizon",
        "horizon_days",
        "industry",
        "information_cutoff",
        "market",
        "mechanism_type",
        "metric",
        "multiple_testing_family",
        "regime",
        "regimes",
        "sample_size",
        "sector",
        "source_ids",
        "start_at",
        "state",
        "target",
        "test",
        "time_window",
        "universe",
    }
)
_TIER1_FINDING_KEYS = frozenset(
    {
        "ambiguity_version_id",
        "assessment_version_id",
        "artifact_id",
        "code",
        "description",
        "limitation",
        "message",
        "object_id",
        "question",
        "rationale",
        "safe_default",
        "scope",
        "source_id",
        "version_id",
    }
)
_TIER1_ARTIFACT_KEYS = frozenset(
    {
        "artifact_id",
        "artifact_type",
        "content_sha256",
        "media_type",
        "object_id",
        "schema_version",
        "sha256",
        "version_id",
    }
)


def _parse_time(value: Any, field_name: str) -> datetime:
    text = require_iso(value, field_name)
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    nested = event.get("payload")
    if isinstance(nested, Mapping):
        payload = dict(nested)
    elif isinstance(event.get("record"), Mapping):
        payload = dict(event["record"])
    else:
        payload = {
            key: value
            for key, value in event.items()
            if key
            not in {
                "event_id",
                "event_type",
                "recorded_at",
                "event_at",
                "timestamp",
                "payload_sha256",
                "event_sha256",
            }
        }
    raw_record_type = str(
        payload.get("record_type") or event.get("event_type") or ""
    ).strip()
    event_key = raw_record_type.lower()
    if event_key.endswith("_appended"):
        event_key = event_key[: -len("_appended")]
    record_type = _RECORD_TYPE_ALIASES.get(event_key, raw_record_type)
    if not record_type:
        raise ValueError("projection_record_type_required")
    payload["record_type"] = record_type
    # Ledger envelopes carry exact identities even for receipt-like payloads
    # that are not ContractMixin records.  Prefer payload values, but retain
    # envelope identities when the direct record mapping omits them.
    for key in ("object_id", "version_id", "ontology_version"):
        if payload.get(key) and event.get(key) and payload[key] != event[key]:
            raise ValueError(f"projection_payload_{key}_mismatch")
        if not payload.get(key) and event.get(key):
            payload[key] = event[key]
    canonical_json(payload)
    return payload


def _event_datetime(event: Mapping[str, Any], payload: Mapping[str, Any]) -> datetime:
    for key in ("recorded_at", "event_at", "timestamp"):
        if event.get(key):
            return _parse_time(event[key], f"event_{key}")
    for key in _TIME_FIELDS:
        if payload.get(key):
            return _parse_time(payload[key], f"payload_{key}")
    raise ValueError("projection_event_time_required")


def _ledger_chain_positions(events: Sequence[Mapping[str, Any]]) -> dict[str, int] | None:
    """Recover append order from a complete ledger chain, independent of input order."""

    chain_fields_present = any(
        event.get("event_hash") is not None
        or event.get("previous_event_hash") is not None
        for event in events
    )
    if not chain_fields_present:
        return None
    if any(
        not isinstance(event.get("event_hash"), str)
        or len(str(event["event_hash"])) != 64
        or (
            event.get("previous_event_hash") is not None
            and (
                not isinstance(event.get("previous_event_hash"), str)
                or len(str(event["previous_event_hash"])) != 64
            )
        )
        for event in events
    ):
        raise ValueError("projection_hash_chain_incomplete")

    by_hash: dict[str, Mapping[str, Any]] = {}
    children: dict[str | None, list[str]] = {}
    for event in events:
        event_hash = str(event["event_hash"])
        if event_hash in by_hash:
            raise ValueError("projection_event_hash_reuse")
        by_hash[event_hash] = event
        previous = event.get("previous_event_hash")
        children.setdefault(previous, []).append(event_hash)
    if len(children.get(None, [])) != 1:
        raise ValueError("projection_hash_chain_root_invalid")
    if any(len(values) != 1 for values in children.values()):
        raise ValueError("projection_hash_chain_branch_invalid")

    positions: dict[str, int] = {}
    current: str | None = children[None][0]
    while current is not None:
        event = by_hash.get(current)
        if event is None:
            raise ValueError("projection_hash_chain_dangling")
        event_id = str(event.get("event_id") or "")
        if not event_id or event_id in positions:
            raise ValueError("projection_hash_chain_event_id_invalid")
        positions[event_id] = len(positions)
        next_hashes = children.get(current, [])
        current = next_hashes[0] if next_hashes else None
    if len(positions) != len(events):
        raise ValueError("projection_hash_chain_disconnected")
    return positions


def _normalized_events(
    events: Sequence[Mapping[str, Any]], *, as_of: datetime
) -> list[dict[str, Any]]:
    by_event_id: dict[str, str] = {}
    normalized_all: list[dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, Mapping):
            raise TypeError("projection_event_must_be_mapping")
        payload = _event_payload(raw)
        recorded = _event_datetime(raw, payload)
        event_id = str(raw.get("event_id") or "").strip()
        if not event_id:
            event_id = "urn:projection-event:" + canonical_sha256(
                "synthetic_projection_event_id_v0",
                {"recorded_at": _iso_utc(recorded), "payload": payload},
            )
        fingerprint = canonical_sha256(
            "projection_event_v0",
            {
                "event_id": event_id,
                "recorded_at": _iso_utc(recorded),
                "payload": payload,
                "previous_event_hash": raw.get("previous_event_hash"),
                "event_hash": raw.get("event_hash"),
            },
        )
        previous = by_event_id.get(event_id)
        if previous is not None:
            if previous != fingerprint:
                raise ValueError(f"projection_event_id_conflict:{event_id}")
            continue
        by_event_id[event_id] = fingerprint
        normalized_all.append(
            {
                "event_id": event_id,
                "recorded_at": _iso_utc(recorded),
                "recorded_dt": recorded,
                "payload": payload,
                "fingerprint": fingerprint,
                "previous_event_hash": raw.get("previous_event_hash"),
                "event_hash": raw.get("event_hash"),
            }
        )
    positions = _ledger_chain_positions(normalized_all)
    normalized = [item for item in normalized_all if item["recorded_dt"] <= as_of]
    if positions is not None:
        normalized.sort(key=lambda item: positions[item["event_id"]])
    else:
        normalized.sort(
            key=lambda item: (
                item["recorded_at"],
                item["event_id"],
                item["fingerprint"],
            )
        )
    return normalized


def _record_identity(payload: Mapping[str, Any], event_id: str) -> tuple[str, str, str]:
    record_type = str(payload["record_type"])
    object_field = _OBJECT_ID_FIELDS.get(record_type)
    object_id = str(
        payload.get("object_id")
        or (payload.get(object_field) if object_field else "")
        or ""
    )
    version_id = str(payload.get("version_id") or "")
    if record_type == "RunReference":
        version_id = str(payload.get("run_id") or version_id)
    elif record_type == "WorkflowSkillBinding" and not version_id:
        skill_id = str(payload.get("skill_id") or "")
        skill_version = str(payload.get("skill_version") or "")
        version_id = f"{skill_id}@{skill_version}" if skill_id and skill_version else ""
    if not object_id:
        object_id = version_id or event_id
    if not version_id:
        version_id = object_id or event_id
    return object_id, version_id, record_type


def _exact_ids(payload: Mapping[str, Any]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for key, value in payload.items():
        if (key == "id" or key.endswith("_id")) and isinstance(value, str) and value.strip():
            ids[str(key)] = value
    return {key: ids[key] for key in sorted(ids)}


def _axis_value(payload: Mapping[str, Any], axis: str) -> str | None:
    axes = payload.get("axes")
    raw = axes.get(axis) if isinstance(axes, Mapping) and axis in axes else payload.get(axis)
    if raw is None:
        return None
    value = str(raw)
    if value not in _AXIS_VALUES[axis]:
        raise ValueError(f"projection_{axis}_invalid:{value}")
    return value


def _base_axes(payload: Mapping[str, Any], record_type: str) -> dict[str, str | None]:
    legacy = bool(payload.get("legacy_label") or payload.get("legacy_aliases"))
    axes: dict[str, str | None] = {
        "lifecycle": "active",
        "evidence": "untested" if record_type == "ClaimVersion" else None,
        "authority": "legacy_import_unreviewed" if legacy else "agent_proposed",
        "decision": "pending",
        "freshness": "unknown",
        "admissibility": None,
    }
    for axis in _AXIS_VALUES:
        explicit = _axis_value(payload, axis)
        if explicit is not None:
            axes[axis] = explicit
    return axes


def _list_items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _unique_canonical(values: Iterable[Any]) -> list[Any]:
    by_json: dict[str, Any] = {}
    for value in values:
        encoded = canonical_json(value)
        by_json[encoded] = value
    return [by_json[key] for key in sorted(by_json)]


def _artifact_refs(payload: Mapping[str, Any]) -> list[Any]:
    values: list[Any] = []
    for key in (
        "artifact_ref",
        "artifact_refs",
        "validation_artifact_refs",
        "verification_result_ref",
        "evaluation_result_ref",
    ):
        values.extend(_list_items(payload.get(key)))
    return _unique_canonical(values)


def _planned_expiry(payload: Mapping[str, Any]) -> str | None:
    direct = payload.get("expires_at") or payload.get("valid_until")
    if direct:
        _parse_time(direct, "projection_expiry")
        return str(direct)
    spec = payload.get("spec")
    if not isinstance(spec, Mapping):
        return None
    expiry = spec.get("expiry")
    if isinstance(expiry, Mapping) and expiry.get("state") == "specified" and expiry.get("value"):
        _parse_time(expiry["value"], "projection_planned_expiry")
        return str(expiry["value"])
    return None


def _forbidden_context_key(key: Any) -> bool:
    text = str(key).strip().lower().replace("-", "_")
    if text in _FORBIDDEN_CONTEXT_KEYS or text.startswith("raw_") or text.endswith("_raw"):
        return True
    parts = set(text.split("_"))
    return bool(
        parts
        & {
            "secret",
            "secrets",
            "credential",
            "credentials",
            "broker",
            "brokers",
            "trading",
            "trade",
            "trades",
            "order",
            "orders",
            "position",
            "positions",
            "log",
            "logs",
            "reasoning",
            "scratchpad",
        }
    )


def _sanitize_context(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_context(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _forbidden_context_key(key)
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize_context(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _allowlisted_context(
    value: Any,
    *,
    allowed_keys: frozenset[str],
) -> Any:
    """Return only explicitly permitted Tier-1 metadata fields."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            key = str(raw_key).strip()
            if key not in allowed_keys:
                continue
            if key == "scope":
                result[key] = _allowlisted_context(
                    item, allowed_keys=_TIER1_SCOPE_KEYS
                )
            else:
                result[key] = _allowlisted_context(item, allowed_keys=allowed_keys)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _allowlisted_context(item, allowed_keys=allowed_keys) for item in value
        ]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _tier1_scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return _allowlisted_context(value, allowed_keys=_TIER1_SCOPE_KEYS)


def _tier1_findings(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        value = _list_items(value)
    return _allowlisted_context(value, allowed_keys=_TIER1_FINDING_KEYS)


def _tier1_artifact_refs(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        value = _list_items(value)
    return _allowlisted_context(value, allowed_keys=_TIER1_ARTIFACT_KEYS)


def _scope(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = payload.get("scope")
    return _sanitize_context(value) if isinstance(value, Mapping) else {}


def _caveats(payload: Mapping[str, Any]) -> list[Any]:
    values: list[Any] = []
    for key in ("caveats", "limitations"):
        values.extend(_list_items(payload.get(key)))
    return _unique_canonical(_sanitize_context(values))


def _blockers(payload: Mapping[str, Any]) -> list[Any]:
    return _unique_canonical(_sanitize_context(_list_items(payload.get("blockers"))))


def _contradictions(payload: Mapping[str, Any]) -> list[Any]:
    return _unique_canonical(_sanitize_context(_list_items(payload.get("contradictions"))))


def _new_record_node(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event["payload"]
    object_id, version_id, record_type = _record_identity(payload, event["event_id"])
    declared_freshness = _axis_value(payload, "freshness")
    return {
        "node_id": version_id,
        "object_id": object_id,
        "version_id": version_id,
        "record_type": record_type,
        "kind": str(
            payload.get("claim_kind")
            or payload.get("method_kind")
            or payload.get("artifact_type")
            or record_type
        ),
        "ids": _exact_ids(payload),
        "axes": _base_axes(payload, record_type),
        "axis_provenance": {},
        "scope": _scope(payload),
        "blockers": _blockers(payload),
        "contradictions": _contradictions(payload),
        "caveats": _caveats(payload),
        "artifact_refs": _artifact_refs(payload),
        "recorded_at": event["recorded_at"],
        "source_event_ids": [event["event_id"]],
        "research_only": True,
        "execution_allowed": False,
        "_record_fingerprint": canonical_sha256("projection_record_v0", payload),
        "_freshness_input": {
            "declared": declared_freshness,
            "expires_at": _planned_expiry(payload),
            "source_event_id": event["event_id"],
            "recorded_at": event["recorded_at"],
        },
        "_is_record": True,
    }


def _ensure_reference_node(nodes: dict[str, dict[str, Any]], node_id: str) -> None:
    if not node_id or node_id in nodes:
        return
    nodes[node_id] = {
        "node_id": node_id,
        "object_id": node_id,
        "version_id": None,
        "record_type": "Reference",
        "kind": "Reference",
        "ids": {"reference_id": node_id},
        "axes": {axis: None for axis in _AXIS_VALUES},
        "axis_provenance": {},
        "scope": {},
        "blockers": [],
        "contradictions": [],
        "caveats": [],
        "artifact_refs": [],
        "recorded_at": None,
        "source_event_ids": [],
        "research_only": True,
        "execution_allowed": False,
        "_freshness_input": {},
        "_is_record": False,
    }


def _apply_axis(
    node: dict[str, Any],
    *,
    axis: str,
    value: Any,
    event: Mapping[str, Any],
    source_version_id: str,
) -> None:
    if value is None:
        return
    text = str(value)
    if text not in _AXIS_VALUES[axis]:
        raise ValueError(f"projection_{axis}_invalid:{text}")
    node["axes"][axis] = text
    node["axis_provenance"][axis] = {
        "event_id": event["event_id"],
        "recorded_at": event["recorded_at"],
        "source_version_id": source_version_id,
    }


def _apply_target_updates(
    nodes: dict[str, dict[str, Any]],
    event: Mapping[str, Any],
    *,
    as_of: datetime,
) -> None:
    payload = event["payload"]
    record_type = str(payload["record_type"])
    _, source_version_id, _ = _record_identity(payload, event["event_id"])
    target_version_id: str | None = None
    if record_type == "EvidenceAssessment":
        target_version_id = str(payload.get("claim_version_id") or "") or None
    elif record_type in {
        "DispositionRecord",
        "AmbiguityPacket",
        "AxisAssessment",
        "AxisReceipt",
    }:
        target_version_id = str(payload.get("target_version_id") or "") or None
    if not target_version_id:
        return
    target = nodes.get(target_version_id)
    if target is None or target.get("_is_record") is not True:
        raise ValueError(f"projection_exact_target_version_not_found:{target_version_id}")
    target_object_id = payload.get("target_object_id")
    if target_object_id and target.get("object_id") != target_object_id:
        raise ValueError("projection_exact_target_object_version_mismatch")
    effective_value = payload.get("effective_at")
    if effective_value and _parse_time(effective_value, "projection_effective_at") > as_of:
        return
    expires_value = payload.get("expires_at")
    if expires_value and _parse_time(expires_value, "projection_expires_at") <= as_of:
        return

    if record_type == "AxisReceipt":
        axis_name = str(payload.get("axis_name") or "")
        if axis_name not in _AXIS_VALUES:
            raise ValueError(f"projection_axis_receipt_name_invalid:{axis_name}")
        if axis_name == "freshness":
            declared_freshness = str(payload.get("axis_value") or "")
            if declared_freshness not in _AXIS_VALUES["freshness"]:
                raise ValueError(
                    f"projection_freshness_invalid:{declared_freshness}"
                )
            target["_freshness_input"] = {
                "declared": declared_freshness,
                "expires_at": _planned_expiry(payload),
                "source_event_id": event["event_id"],
                "recorded_at": event["recorded_at"],
                "source_version_id": source_version_id,
            }
        else:
            _apply_axis(
                target,
                axis=axis_name,
                value=payload.get("axis_value"),
                event=event,
                source_version_id=source_version_id,
            )

    if record_type in {"EvidenceAssessment", "AxisAssessment"}:
        for axis in ("evidence", "admissibility"):
            _apply_axis(
                target,
                axis=axis,
                value=_axis_value(payload, axis),
                event=event,
                source_version_id=source_version_id,
            )
    if record_type in {"DispositionRecord", "AxisAssessment"}:
        for axis in ("lifecycle", "authority", "decision"):
            _apply_axis(
                target,
                axis=axis,
                value=_axis_value(payload, axis),
                event=event,
                source_version_id=source_version_id,
            )

    if record_type != "AxisReceipt":
        declared_freshness = _axis_value(payload, "freshness")
        expires_at = _planned_expiry(payload)
        if declared_freshness is not None or expires_at is not None:
            target["_freshness_input"] = {
                "declared": declared_freshness,
                "expires_at": expires_at,
                "source_event_id": event["event_id"],
                "recorded_at": event["recorded_at"],
                "source_version_id": source_version_id,
            }

    target["artifact_refs"] = _unique_canonical(
        [*target["artifact_refs"], *_artifact_refs(payload)]
    )
    target["blockers"] = _unique_canonical([*target["blockers"], *_blockers(payload)])
    target["contradictions"] = _unique_canonical(
        [*target["contradictions"], *_contradictions(payload)]
    )
    target["caveats"] = _unique_canonical([*target["caveats"], *_caveats(payload)])

    evidence = _axis_value(payload, "evidence")
    if evidence == "blocked_by_data":
        target["blockers"] = _unique_canonical(
            [
                *target["blockers"],
                {
                    "code": "blocked_by_data",
                    "assessment_version_id": source_version_id,
                    "rationale": str(payload.get("rationale") or ""),
                },
            ]
        )
    elif evidence == "contradicted_in_scope":
        target["contradictions"] = _unique_canonical(
            [
                *target["contradictions"],
                {
                    "code": "contradicted_in_scope",
                    "assessment_version_id": source_version_id,
                    "scope": _scope(payload),
                },
            ]
        )
    if record_type == "AmbiguityPacket":
        target["blockers"] = _unique_canonical(
            [
                *target["blockers"],
                {
                    "code": "unresolved_ambiguity",
                    "ambiguity_version_id": source_version_id,
                    "question": str(payload.get("question") or ""),
                    "safe_default": str(payload.get("safe_default") or ""),
                },
            ]
        )


def _edge_endpoint(relation: Mapping[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = relation.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _add_edge(
    edges: dict[tuple[str, str, str, str, str], dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    *,
    relation: str,
    source_id: str,
    target_id: str,
    relation_version: str,
    rule_id: str,
    event_id: str,
) -> None:
    if relation not in DERIVATION_RELATIONS:
        raise ValueError(f"projection_relation_not_whitelisted:{relation}")
    if not source_id or not target_id or not relation_version or not rule_id:
        raise ValueError("projection_edge_provenance_incomplete")
    if _REGISTERED_DERIVATION_RULES.get(relation) != (rule_id, relation_version):
        raise ValueError("projection_derivation_rule_not_registered")
    _ensure_reference_node(nodes, source_id)
    _ensure_reference_node(nodes, target_id)
    key = (relation, source_id, target_id, relation_version, rule_id)
    edge = edges.get(key)
    if edge is None:
        edge = {
            "relation": relation,
            "source_id": source_id,
            "target_id": target_id,
            "relation_version": relation_version,
            "rule_id": rule_id,
            "deterministic": True,
            "provenance_refs": [],
            "source_event_ids": [],
        }
        edges[key] = edge
    edge["source_event_ids"] = sorted(set(edge["source_event_ids"]) | {event_id})
    edge["provenance_refs"] = sorted(set(edge["provenance_refs"]) | {event_id})


def _generated_edges(
    event: Mapping[str, Any],
    edges: dict[tuple[str, str, str, str, str], dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
) -> None:
    payload = event["payload"]
    object_id, version_id, record_type = _record_identity(payload, event["event_id"])
    event_id = event["event_id"]

    def add_registered(relation: str, source_id: str, target_id: str) -> None:
        rule_id, relation_version = _REGISTERED_DERIVATION_RULES[relation]
        _add_edge(
            edges,
            nodes,
            relation=relation,
            source_id=source_id,
            target_id=target_id,
            relation_version=relation_version,
            rule_id=rule_id,
            event_id=event_id,
        )

    if object_id != version_id:
        add_registered("version_of", version_id, object_id)

    parent_fields = ("parent_claim_ids", "parent_mechanism_ids", "parent_hypothesis_id")
    for field in parent_fields:
        for parent_id in _list_items(payload.get(field)):
            if isinstance(parent_id, str) and parent_id:
                add_registered("parent_of", parent_id, object_id)

    instantiates: list[str] = []
    if record_type == "ClaimVersion":
        instantiates.extend(str(value) for value in _list_items(payload.get("mechanism_ids")))
    elif record_type == "HypothesisRecord":
        instantiates.extend(str(value) for value in _list_items(payload.get("claim_version_id")))
    elif record_type == "ExperimentSpec":
        instantiates.extend(str(value) for value in _list_items(payload.get("hypothesis_id")))
    elif record_type == "RunReference":
        instantiates.extend(str(value) for value in _list_items(payload.get("experiment_version_id")))
    for target_id in instantiates:
        if target_id:
            add_registered("instantiates", version_id, target_id)

    if record_type == "EvidenceAssessment" and payload.get("claim_version_id"):
        add_registered("assesses", version_id, str(payload["claim_version_id"]))

    for artifact_ref in _artifact_refs(payload):
        target_id = artifact_ref if isinstance(artifact_ref, str) else ""
        if isinstance(artifact_ref, Mapping):
            target_id = str(
                artifact_ref.get("version_id")
                or artifact_ref.get("object_id")
                or artifact_ref.get("artifact_id")
                or ""
            )
        if target_id:
            add_registered("references_artifact", version_id, target_id)

    derived_values = _list_items(payload.get("derived_from"))
    if record_type == "EvidenceAssessment":
        derived_values.extend(_list_items(payload.get("run_id")))
    for source_ref in derived_values:
        source_ref_id = str(source_ref) if isinstance(source_ref, str) else ""
        if source_ref_id:
            add_registered("derived_from", version_id, source_ref_id)

    superseded = [
        *_list_items(payload.get("supersedes")),
        *_list_items(payload.get("supersedes_version_id")),
    ]
    for previous_version_id in superseded:
        if isinstance(previous_version_id, str) and previous_version_id:
            add_registered("supersedes", version_id, previous_version_id)


def _explicit_edges(
    event: Mapping[str, Any],
    edges: dict[tuple[str, str, str, str, str], dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    exclusions: list[dict[str, Any]],
) -> None:
    relations = event["payload"].get("relations")
    for raw in _list_items(relations):
        relation_ref = canonical_sha256("excluded_or_explicit_relation_v0", raw)
        if not isinstance(raw, Mapping):
            exclusions.append(
                {
                    "event_id": event["event_id"],
                    "relation_ref": relation_ref,
                    "reason": "relation_not_mapping",
                }
            )
            continue
        relation = str(
            raw.get("relation") or raw.get("relation_type") or raw.get("type") or ""
        ).strip()
        if relation in FORBIDDEN_BARE_RELATIONS or relation not in DERIVATION_RELATIONS:
            exclusions.append(
                {
                    "event_id": event["event_id"],
                    "relation_ref": relation_ref,
                    "relation": relation,
                    "reason": "relation_default_denied",
                }
            )
            continue
        relation_version = str(
            raw.get("relation_version") or raw.get("rule_version") or raw.get("version") or ""
        ).strip()
        source_id = _edge_endpoint(
            raw, ("source_id", "from_id", "source", "from", "subject_id", "subject")
        )
        target_id = _edge_endpoint(
            raw, ("target_id", "to_id", "target", "to", "object_id", "object")
        )
        rule_id = str(raw.get("rule_id") or raw.get("derivation_rule_id") or "").strip()
        provenance_refs = [
            str(value)
            for value in _list_items(raw.get("provenance_refs"))
            if isinstance(value, str) and value.strip()
        ]
        if (
            not relation_version
            or not source_id
            or not target_id
            or not rule_id
            or raw.get("deterministic") is not True
            or not provenance_refs
        ):
            exclusions.append(
                {
                    "event_id": event["event_id"],
                    "relation_ref": relation_ref,
                    "relation": relation,
                    "reason": "relation_provenance_incomplete",
                }
            )
            continue
        if _REGISTERED_DERIVATION_RULES.get(relation) != (
            rule_id,
            relation_version,
        ):
            exclusions.append(
                {
                    "event_id": event["event_id"],
                    "relation_ref": relation_ref,
                    "relation": relation,
                    "reason": "relation_rule_not_registered",
                }
            )
            continue
        _add_edge(
            edges,
            nodes,
            relation=relation,
            source_id=source_id,
            target_id=target_id,
            relation_version=relation_version,
            rule_id=rule_id,
            event_id=event["event_id"],
        )
        key = (relation, source_id, target_id, relation_version, rule_id)
        edges[key]["provenance_refs"] = sorted(
            set(edges[key]["provenance_refs"]) | set(provenance_refs)
        )


def _derive_freshness(node: dict[str, Any], as_of: datetime) -> None:
    basis = dict(node.get("_freshness_input") or {})
    expiry = basis.get("expires_at")
    declared = basis.get("declared")
    if expiry:
        expires_at = _parse_time(expiry, "projection_freshness_expiry")
        freshness = "expired" if as_of >= expires_at else "current"
        basis["expires_at"] = _iso_utc(expires_at)
    elif declared == "not_applicable":
        freshness = "not_applicable"
    elif declared == "expired":
        freshness = "expired"
    else:
        # A prior declaration of "current" without a validity boundary cannot
        # prove currency at a later requested time.
        freshness = "unknown"
    node["axes"]["freshness"] = freshness
    node["freshness_basis"] = {
        key: value
        for key, value in sorted(basis.items())
        if value is not None and key != "declared"
    }
    if declared is not None:
        node["freshness_basis"]["declared"] = declared


def _public_node(node: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in node.items()
        if not key.startswith("_")
    }


def build_graph_projection(
    events: Sequence[Mapping[str, Any]], *, as_of: str
) -> dict[str, Any]:
    """Replay events into a deterministic, structural current-as-of graph."""

    as_of_dt = _parse_time(as_of, "projection_as_of")
    normalized = _normalized_events(events, as_of=as_of_dt)
    nodes: dict[str, dict[str, Any]] = {}

    for event in normalized:
        node = _new_record_node(event)
        existing = nodes.get(node["node_id"])
        if existing is not None:
            if existing.get("_record_fingerprint") != node["_record_fingerprint"]:
                raise ValueError(f"projection_version_id_conflict:{node['node_id']}")
            existing["source_event_ids"] = sorted(
                set(existing["source_event_ids"]) | set(node["source_event_ids"])
            )
            continue
        nodes[node["node_id"]] = node

    for event in normalized:
        _apply_target_updates(nodes, event, as_of=as_of_dt)

    edges: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    exclusions: list[dict[str, Any]] = []
    for event in normalized:
        _generated_edges(event, edges, nodes)
        _explicit_edges(event, edges, nodes, exclusions)

    for node in nodes.values():
        _derive_freshness(node, as_of_dt)

    public_nodes = sorted(
        (_public_node(node) for node in nodes.values()), key=lambda item: item["node_id"]
    )
    public_edges: list[dict[str, Any]] = []
    for edge in sorted(
        edges.values(),
        key=lambda item: (
            item["relation"],
            item["source_id"],
            item["target_id"],
            item["relation_version"],
            item["rule_id"],
        ),
    ):
        material = dict(edge)
        material["edge_id"] = "urn:projection-edge:" + canonical_sha256(
            "projection_edge_v0", edge
        )
        public_edges.append(material)
    exclusions = _unique_canonical(exclusions)
    core: dict[str, Any] = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "as_of": _iso_utc(as_of_dt),
        "event_count": len(normalized),
        "nodes": public_nodes,
        "edges": public_edges,
        "excluded_relations": exclusions,
        "research_only": True,
        "execution_allowed": False,
    }
    return {
        **core,
        "projection_sha256": canonical_sha256("research_graph_projection_v0", core),
    }


def _context_record(node: Mapping[str, Any]) -> dict[str, Any]:
    axes = _sanitize_context(node["axes"])
    return {
        "record_id": node["node_id"],
        "object_id": node["object_id"],
        "version_id": node["version_id"],
        "ids": _sanitize_context(node["ids"]),
        "record_type": node["record_type"],
        "kind": node["kind"],
        "axes": axes,
        "scope": _tier1_scope(node["scope"]),
        "freshness": axes["freshness"],
        "freshness_basis": _sanitize_context(node["freshness_basis"]),
        "blockers": _tier1_findings(node["blockers"]),
        "contradictions": _tier1_findings(node["contradictions"]),
        "caveats": _tier1_findings(node["caveats"]),
        "artifact_refs": _tier1_artifact_refs(node["artifact_refs"]),
        "source_event_ids": sorted(node["source_event_ids"]),
    }


def _context_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        0 if record["blockers"] else 1,
        0 if record["contradictions"] else 1,
        0 if record["freshness"] == "expired" else 1,
        str(record["record_type"]),
        str(record["record_id"]),
    )


def build_tier1_context(
    events: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    """Build a deterministic, bounded, recursively allowlisted Tier-1 context."""

    if (
        not isinstance(max_records, int)
        or isinstance(max_records, bool)
        or max_records < 1
        or max_records > DEFAULT_MAX_RECORDS
    ):
        raise ValueError("tier1_max_records_must_be_between_1_and_50")
    if (
        not isinstance(max_bytes, int)
        or isinstance(max_bytes, bool)
        or max_bytes < 1
        or max_bytes > DEFAULT_MAX_BYTES
    ):
        raise ValueError("tier1_max_bytes_must_be_between_1_and_65536")

    projection = build_graph_projection(events, as_of=as_of)
    record_nodes = [
        node
        for node in projection["nodes"]
        if node["record_type"] != "Reference" and node.get("recorded_at") is not None
    ]
    candidates = sorted((_context_record(node) for node in record_nodes), key=_context_sort_key)
    selected = list(candidates[:max_records])

    def assemble(records: list[dict[str, Any]]) -> dict[str, Any]:
        core: dict[str, Any] = {
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "as_of": projection["as_of"],
            "projection_sha256": projection["projection_sha256"],
            "records": records,
            "record_count": len(records),
            "candidate_count": len(candidates),
            "omitted_record_count": len(candidates) - len(records),
            "truncated": len(records) < len(candidates),
            "limits": {"max_records": max_records, "max_bytes": max_bytes},
            "research_only": True,
            "execution_allowed": False,
        }
        return {
            **core,
            "context_sha256": canonical_sha256("tier1_context_v0", core),
        }

    context = assemble(selected)
    while len(canonical_json(context).encode("utf-8")) > max_bytes and selected:
        selected.pop()
        context = assemble(selected)
    if len(canonical_json(context).encode("utf-8")) > max_bytes:
        raise ValueError("tier1_max_bytes_too_small_for_envelope")
    return context


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_RECORDS",
    "PROJECTION_SCHEMA_VERSION",
    "build_graph_projection",
    "build_tier1_context",
]
