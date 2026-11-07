from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
from functools import wraps
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4


ID_PREFIX = "urn:portfolio-research:"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class ClaimKind(str, Enum):
    STRUCTURAL = "structural"
    ASSOCIATION = "association"
    PREDICTIVE = "predictive"
    CAUSAL = "causal"
    PROXY_ADEQUACY = "proxy_adequacy"
    ECONOMIC_UTILITY = "economic_utility"


class Lifecycle(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class Evidence(str, Enum):
    UNTESTED = "untested"
    SUPPORTED_IN_SCOPE = "supported_in_scope"
    CONTRADICTED_IN_SCOPE = "contradicted_in_scope"
    MIXED = "mixed"
    INSUFFICIENT = "insufficient"
    UNSTABLE = "unstable"
    PROXY_ONLY = "proxy_only"
    BLOCKED_BY_DATA = "blocked_by_data"


class Authority(str, Enum):
    AGENT_PROPOSED = "agent_proposed"
    LEGACY_IMPORT_UNREVIEWED = "legacy_import_unreviewed"
    HUMAN_REVIEWED = "human_reviewed"


class Decision(str, Enum):
    PENDING = "pending"
    KEPT = "kept"
    REJECTED_EXACT = "rejected_exact"
    RETYPED = "retyped"
    REVISION_REQUESTED = "revision_requested"
    DEFERRED = "deferred"


class Freshness(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    CURRENT = "current"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class Admissibility(str, Enum):
    ADMISSIBLE = "admissible"
    INADMISSIBLE = "inadmissible"
    BLOCKED = "blocked"


PLANNED_FIELD_STATES = frozenset({"specified", "unknown", "blocked"})
PROXY_USES = frozenset({"context", "screening", "control"})
DERIVATION_RELATIONS = frozenset(
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
STABLE_DERIVATION_RULE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*_v[0-9]+$")
METHOD_KINDS = frozenset(
    {"data_acquisition", "chart", "research_report", "backtest", "interpretation"}
)

PREDICTIVE_FIELDS = (
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
)
CAUSAL_FIELDS = (
    "population",
    "intervention",
    "comparator",
    "outcome",
    "timing",
    "estimand",
    "identification_assumptions",
)
PROXY_FIELDS = (
    "proxy_id",
    "construct_id",
    "intended_use",
    "scope",
    "limitations",
    "validation_refs",
    "expiry",
)
ECONOMIC_UTILITY_FIELDS = (
    "decision_rule",
    "baseline_decision",
    "costs",
    "constraints",
    "capacity",
    "risk",
    "utility_metric",
    "success_thresholds",
)


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            item.name: _plain(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical_json_dict_keys_must_be_strings")
        return {key: _plain(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical_json_nonfinite_float")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"canonical_json_unsupported_type:{type(value).__name__}")


def _freeze_value(value: Any) -> Any:
    """Defensively detach and recursively freeze caller-owned containers."""

    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical_json_dict_keys_must_be_strings")
        return MappingProxyType(
            {key: _freeze_value(value[key]) for key in value}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((_freeze_value(item) for item in value), key=canonical_json))
    return value


def _freeze_contract_fields(instance: Any) -> None:
    for item in fields(instance):
        object.__setattr__(
            instance,
            item.name,
            _freeze_value(getattr(instance, item.name)),
        )


def canonical_json(value: Any) -> str:
    return json.dumps(
        _plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def canonical_sha256(domain: str, value: Any) -> str:
    if not str(domain).strip():
        raise ValueError("hash_domain_required")
    encoded = domain.encode("utf-8") + b"\0" + canonical_json(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def new_opaque_id() -> str:
    return f"{ID_PREFIX}{uuid4()}"


def require_opaque_id(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text.startswith(ID_PREFIX):
        raise ValueError(f"{field_name}_must_be_opaque_portfolio_urn")
    try:
        parsed = UUID(text.removeprefix(ID_PREFIX))
    except ValueError as exc:
        raise ValueError(f"{field_name}_must_be_opaque_portfolio_urn") from exc
    if str(parsed) != text.removeprefix(ID_PREFIX):
        raise ValueError(f"{field_name}_uuid_must_be_canonical")
    if parsed.version != 4:
        raise ValueError(f"{field_name}_must_be_uuid4")
    return text


def require_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name}_required")
    return text


def require_iso(value: Any, field_name: str) -> str:
    text = require_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name}_must_be_iso8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name}_must_have_timezone")
    return text


def require_semver(value: Any, field_name: str = "ontology_version") -> str:
    text = require_text(value, field_name)
    if not SEMVER_RE.fullmatch(text):
        raise ValueError(f"{field_name}_must_be_semver")
    return text


def require_sha256(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not SHA256_RE.fullmatch(text):
        raise ValueError(f"{field_name}_must_be_sha256")
    return text


def require_research_boundary(research_only: bool, execution_allowed: bool) -> None:
    if research_only is not True:
        raise ValueError("research_only_must_be_true")
    if execution_allowed is not False:
        raise ValueError("execution_allowed_must_be_false")


def _require_mapping(value: Mapping[str, Any], field_name: str, *, nonempty: bool = True) -> None:
    if not isinstance(value, Mapping) or (nonempty and not value):
        raise ValueError(f"{field_name}_must_be_{'nonempty_' if nonempty else ''}mapping")
    canonical_json(value)


def _require_refs(values: Sequence[str], field_name: str, *, allow_empty: bool = True) -> None:
    if not allow_empty and not values:
        raise ValueError(f"{field_name}_required")
    for value in values:
        require_opaque_id(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name}_must_be_unique")


def is_bounded_scope(value: Any) -> bool:
    """Return whether a scope is explicit, nonempty, and contains no wildcard semantics."""

    if isinstance(value, Mapping):
        return bool(value) and all(
            isinstance(key, str)
            and bool(key.strip())
            and "*" not in key
            and is_bounded_scope(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return bool(value) and all(is_bounded_scope(item) for item in value)
    if isinstance(value, str):
        text = value.strip()
        return bool(text) and "*" not in text and text.casefold() not in {
            "all",
            "any",
            "unknown",
            "unspecified",
        }
    return value is not None


class ContractMixin:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        post_init = cls.__dict__.get("__post_init__")
        if post_init is None:
            return

        @wraps(post_init)
        def immutable_post_init(self: Any, *args: Any, **inner_kwargs: Any) -> None:
            _freeze_contract_fields(self)
            post_init(self, *args, **inner_kwargs)

        cls.__post_init__ = immutable_post_init

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(type(self).__name__, self.to_dict())


AXIS_ENUMS: Mapping[str, type[Enum]] = {
    "lifecycle": Lifecycle,
    "evidence": Evidence,
    "authority": Authority,
    "decision": Decision,
    "freshness": Freshness,
    "admissibility": Admissibility,
}


@dataclass(frozen=True)
class PlannedField(ContractMixin):
    field_name: str
    state: str
    value: Any = None
    assumptions: tuple[str, ...] = ()
    test_refs: tuple[str, ...] = ()
    refinement_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.field_name, "planned_field_name")
        if self.state not in PLANNED_FIELD_STATES:
            raise ValueError("planned_field_state_invalid")
        if self.state == "specified" and self.value is None:
            raise ValueError("specified_planned_field_requires_value")
        if self.state != "specified" and self.value is not None:
            raise ValueError("unknown_or_blocked_planned_field_cannot_have_value")
        canonical_json(self.value)
        for value in (*self.assumptions, *self.test_refs, *self.refinement_notes):
            require_text(value, "planned_field_detail")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, expected_name: str | None = None) -> "PlannedField":
        field_name = str(payload.get("field_name") or expected_name or "")
        if expected_name and field_name != expected_name:
            raise ValueError(f"planned_field_name_mismatch:{expected_name}")
        return cls(
            field_name=field_name,
            state=str(payload.get("state") or ""),
            value=payload.get("value"),
            assumptions=tuple(str(value) for value in payload.get("assumptions", [])),
            test_refs=tuple(str(value) for value in payload.get("test_refs", [])),
            refinement_notes=tuple(str(value) for value in payload.get("refinement_notes", [])),
        )


def validate_claim_spec(kind: ClaimKind, spec: Mapping[str, Any]) -> None:
    _require_mapping(spec, "claim_spec")
    required: Sequence[str]
    if kind == ClaimKind.PREDICTIVE:
        required = PREDICTIVE_FIELDS
    elif kind == ClaimKind.CAUSAL:
        required = CAUSAL_FIELDS
    elif kind == ClaimKind.PROXY_ADEQUACY:
        required = PROXY_FIELDS
    elif kind == ClaimKind.ECONOMIC_UTILITY:
        required = ECONOMIC_UTILITY_FIELDS
    elif kind == ClaimKind.ASSOCIATION:
        required = ("population", "variables", "measure", "conditioning")
    else:
        required = ("subjects", "relation", "objects", "conditions")
    missing = [field_name for field_name in required if field_name not in spec]
    if missing:
        raise ValueError(f"claim_spec_fields_missing:{','.join(missing)}")
    for field_name in required:
        raw = spec[field_name]
        if not isinstance(raw, Mapping):
            raise ValueError(f"claim_spec_{field_name}_must_be_planned_field")
        PlannedField.from_mapping(raw, expected_name=field_name)


@dataclass(frozen=True)
class MechanismRecord(ContractMixin):
    object_id: str
    version_id: str
    ontology_version: str
    title: str
    description: str
    scope: Mapping[str, Any]
    source_refs: tuple[str, ...] = ()
    parent_mechanism_ids: tuple[str, ...] = ()
    legacy_aliases: tuple[str, ...] = ()
    created_at: str = "1970-01-01T00:00:00Z"
    created_by: str = "system"
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        require_opaque_id(self.object_id, "mechanism_object_id")
        require_opaque_id(self.version_id, "mechanism_version_id")
        require_semver(self.ontology_version)
        require_text(self.title, "mechanism_title")
        require_text(self.description, "mechanism_description")
        _require_mapping(self.scope, "mechanism_scope")
        _require_refs(self.parent_mechanism_ids, "parent_mechanism_id")
        for value in (*self.source_refs, *self.legacy_aliases):
            require_text(value, "mechanism_reference")
        require_iso(self.created_at, "mechanism_created_at")
        require_text(self.created_by, "mechanism_created_by")
        require_research_boundary(self.research_only, self.execution_allowed)


@dataclass(frozen=True)
class ClaimVersion(ContractMixin):
    object_id: str
    version_id: str
    ontology_version: str
    claim_kind: ClaimKind
    proposition: str
    scope: Mapping[str, Any]
    spec: Mapping[str, Any]
    parent_claim_ids: tuple[str, ...] = ()
    mechanism_ids: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    created_at: str = "1970-01-01T00:00:00Z"
    created_by: str = "system"
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        require_opaque_id(self.object_id, "claim_object_id")
        require_opaque_id(self.version_id, "claim_version_id")
        require_semver(self.ontology_version)
        if not isinstance(self.claim_kind, ClaimKind):
            raise ValueError("claim_kind_invalid")
        require_text(self.proposition, "claim_proposition")
        _require_mapping(self.scope, "claim_scope")
        validate_claim_spec(self.claim_kind, self.spec)
        _require_refs(self.parent_claim_ids, "parent_claim_id")
        _require_refs(self.mechanism_ids, "mechanism_id")
        _require_refs(self.artifact_refs, "claim_artifact_ref")
        require_iso(self.created_at, "claim_created_at")
        require_text(self.created_by, "claim_created_by")
        require_research_boundary(self.research_only, self.execution_allowed)

    @property
    def semantic_fingerprint(self) -> str:
        return canonical_sha256(
            "claim_semantic_fingerprint_v0",
            {
                "claim_kind": self.claim_kind.value,
                "proposition": self.proposition,
                "scope": self.scope,
                "spec": self.spec,
                "parent_claim_ids": self.parent_claim_ids,
                "mechanism_ids": self.mechanism_ids,
            },
        )


@dataclass(frozen=True)
class HypothesisRecord(ContractMixin):
    object_id: str
    version_id: str
    ontology_version: str
    claim_version_id: str
    question: str
    frozen_at: str
    created_by: str
    parent_hypothesis_id: str | None = None
    declared_change: str | None = None
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        require_opaque_id(self.object_id, "hypothesis_object_id")
        require_opaque_id(self.version_id, "hypothesis_version_id")
        require_opaque_id(self.claim_version_id, "hypothesis_claim_version_id")
        require_semver(self.ontology_version)
        require_text(self.question, "hypothesis_question")
        require_iso(self.frozen_at, "hypothesis_frozen_at")
        require_text(self.created_by, "hypothesis_created_by")
        if self.parent_hypothesis_id:
            require_opaque_id(self.parent_hypothesis_id, "parent_hypothesis_id")
            require_text(self.declared_change, "declared_change")
        require_research_boundary(self.research_only, self.execution_allowed)


@dataclass(frozen=True)
class WorkflowSkillBinding(ContractMixin):
    skill_id: str
    skill_version: str
    skill_path: str
    skill_sha256: str
    allowed_stages: tuple[str, ...]

    def __post_init__(self) -> None:
        require_text(self.skill_id, "skill_id")
        require_semver(self.skill_version, "skill_version")
        require_text(self.skill_path, "skill_path")
        require_sha256(self.skill_sha256, "skill_sha256")
        if not self.allowed_stages:
            raise ValueError("skill_allowed_stages_required")
        for stage in self.allowed_stages:
            require_text(stage, "skill_allowed_stage")


@dataclass(frozen=True)
class WorkflowMethodSpec(ContractMixin):
    method_id: str
    version_id: str
    method_kind: str
    name: str
    input_contract: Mapping[str, Any]
    output_contract: Mapping[str, Any]
    skill_binding: WorkflowSkillBinding
    network_allowed: bool = False
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        require_opaque_id(self.method_id, "method_id")
        require_opaque_id(self.version_id, "method_version_id")
        if self.method_kind not in METHOD_KINDS:
            raise ValueError("workflow_method_kind_invalid")
        require_text(self.name, "workflow_method_name")
        _require_mapping(self.input_contract, "method_input_contract")
        _require_mapping(self.output_contract, "method_output_contract")
        if self.network_allowed is not False:
            raise ValueError("v0_workflow_method_network_must_be_false")
        if self.execution_allowed is not False:
            raise ValueError("workflow_method_execution_must_be_false")


@dataclass(frozen=True)
class VerificationSpec(ContractMixin):
    verification_id: str
    version_id: str
    required_checks: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    independent_implementation_required: bool
    input_contract_sha256: str

    def __post_init__(self) -> None:
        require_opaque_id(self.verification_id, "verification_id")
        require_opaque_id(self.version_id, "verification_version_id")
        if not self.required_checks or not self.stop_conditions:
            raise ValueError("verification_checks_and_stop_conditions_required")
        for value in (*self.required_checks, *self.stop_conditions):
            require_text(value, "verification_rule")
        if self.independent_implementation_required is not True:
            raise ValueError("verification_must_require_independent_implementation")
        require_sha256(self.input_contract_sha256, "verification_input_contract_sha256")


@dataclass(frozen=True)
class EvaluationSpec(ContractMixin):
    evaluation_id: str
    version_id: str
    deterministic_checks: tuple[str, ...]
    rubric: Mapping[str, Any]
    thresholds: Mapping[str, Any]
    holdout_refs: tuple[str, ...]
    max_iterations: int
    llm_judge_allowed: bool = True
    llm_judge_authoritative: bool = False

    def __post_init__(self) -> None:
        require_opaque_id(self.evaluation_id, "evaluation_id")
        require_opaque_id(self.version_id, "evaluation_version_id")
        if not self.deterministic_checks:
            raise ValueError("evaluation_deterministic_checks_required")
        for value in (*self.deterministic_checks, *self.holdout_refs):
            require_text(value, "evaluation_reference")
        _require_mapping(self.rubric, "evaluation_rubric")
        _require_mapping(self.thresholds, "evaluation_thresholds")
        if isinstance(self.max_iterations, bool) or self.max_iterations < 1:
            raise ValueError("evaluation_max_iterations_invalid")
        if self.llm_judge_authoritative is not False:
            raise ValueError("llm_judge_must_not_be_authoritative")


@dataclass(frozen=True)
class ExperimentSpec(ContractMixin):
    object_id: str
    version_id: str
    ontology_version: str
    hypothesis_id: str
    claim_version_id: str
    data_contract_refs: tuple[str, ...]
    method_ids: tuple[str, ...]
    verification_spec_id: str
    evaluation_spec_id: str
    frozen_at: str
    multiple_testing_family: str
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.object_id, "experiment_object_id"),
            (self.version_id, "experiment_version_id"),
            (self.hypothesis_id, "experiment_hypothesis_id"),
            (self.claim_version_id, "experiment_claim_version_id"),
            (self.verification_spec_id, "experiment_verification_spec_id"),
            (self.evaluation_spec_id, "experiment_evaluation_spec_id"),
        ):
            require_opaque_id(value, field_name)
        require_semver(self.ontology_version)
        if not self.data_contract_refs or not self.method_ids:
            raise ValueError("experiment_data_contracts_and_methods_required")
        for value in (*self.data_contract_refs, *self.method_ids):
            require_text(value, "experiment_reference")
        require_iso(self.frozen_at, "experiment_frozen_at")
        require_text(self.multiple_testing_family, "multiple_testing_family")
        require_research_boundary(self.research_only, self.execution_allowed)


@dataclass(frozen=True)
class RunReference(ContractMixin):
    run_id: str
    experiment_version_id: str
    model_identity: str
    skill_bindings: tuple[WorkflowSkillBinding, ...]
    input_sha256: str
    output_sha256: str
    verification_result_ref: str
    evaluation_result_ref: str
    started_at: str
    completed_at: str
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        require_opaque_id(self.run_id, "run_id")
        require_opaque_id(self.experiment_version_id, "run_experiment_version_id")
        require_text(self.model_identity, "run_model_identity")
        if not self.skill_bindings:
            raise ValueError("run_skill_bindings_required")
        require_sha256(self.input_sha256, "run_input_sha256")
        require_sha256(self.output_sha256, "run_output_sha256")
        require_text(self.verification_result_ref, "verification_result_ref")
        require_text(self.evaluation_result_ref, "evaluation_result_ref")
        started = datetime.fromisoformat(
            require_iso(self.started_at, "run_started_at").replace("Z", "+00:00")
        )
        completed = datetime.fromisoformat(
            require_iso(self.completed_at, "run_completed_at").replace("Z", "+00:00")
        )
        if completed < started:
            raise ValueError("run_time_order_invalid")
        require_research_boundary(self.research_only, self.execution_allowed)


@dataclass(frozen=True)
class ArtifactReference(ContractMixin):
    object_id: str
    version_id: str
    artifact_type: str
    uri: str
    sha256: str | None
    source_identity: Mapping[str, Any]
    timing: Mapping[str, Any]
    rights: Mapping[str, Any]
    scope: Mapping[str, Any]
    revision: Mapping[str, Any]
    missingness: Mapping[str, Any]
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        require_opaque_id(self.object_id, "artifact_object_id")
        require_opaque_id(self.version_id, "artifact_version_id")
        require_text(self.artifact_type, "artifact_type")
        require_text(self.uri, "artifact_uri")
        if self.sha256 is not None:
            require_sha256(self.sha256, "artifact_sha256")
        for value, field_name in (
            (self.source_identity, "artifact_source_identity"),
            (self.timing, "artifact_timing"),
            (self.rights, "artifact_rights"),
            (self.scope, "artifact_scope"),
            (self.revision, "artifact_revision"),
            (self.missingness, "artifact_missingness"),
        ):
            _require_mapping(value, field_name)
        require_research_boundary(self.research_only, self.execution_allowed)


@dataclass(frozen=True)
class EvidenceAssessment(ContractMixin):
    object_id: str
    version_id: str
    claim_version_id: str
    evidence: Evidence
    admissibility: Admissibility
    freshness: Freshness
    scope: Mapping[str, Any]
    rationale: str
    artifact_refs: tuple[str, ...]
    assessed_at: str
    assessed_by: str
    run_id: str | None = None
    legacy_label: str | None = None
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.object_id, "assessment_object_id"),
            (self.version_id, "assessment_version_id"),
            (self.claim_version_id, "assessment_claim_version_id"),
        ):
            require_opaque_id(value, field_name)
        if not isinstance(self.evidence, Evidence):
            raise ValueError("evidence_axis_invalid")
        if not isinstance(self.admissibility, Admissibility):
            raise ValueError("admissibility_axis_invalid")
        if not isinstance(self.freshness, Freshness):
            raise ValueError("freshness_axis_invalid")
        if self.evidence == Evidence.BLOCKED_BY_DATA and self.admissibility != Admissibility.BLOCKED:
            raise ValueError("blocked_data_requires_blocked_admissibility")
        _require_mapping(self.scope, "assessment_scope")
        require_text(self.rationale, "assessment_rationale")
        _require_refs(self.artifact_refs, "assessment_artifact_ref")
        require_iso(self.assessed_at, "assessment_assessed_at")
        require_text(self.assessed_by, "assessment_assessed_by")
        if self.run_id:
            require_opaque_id(self.run_id, "assessment_run_id")
        require_research_boundary(self.research_only, self.execution_allowed)


@dataclass(frozen=True)
class AxisReceipt(ContractMixin):
    """Append-only receipt for one axis; never a collapsed universal status."""

    object_id: str
    version_id: str
    target_object_id: str
    target_version_id: str
    axis_name: str
    axis_value: str
    rationale: str
    recorded_at: str
    recorded_by: str
    effective_at: str
    expires_at: str | None = None
    scope: Mapping[str, Any] = field(default_factory=lambda: {"applies_to": "exact_version"})
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.object_id, "axis_receipt_object_id"),
            (self.version_id, "axis_receipt_version_id"),
            (self.target_object_id, "axis_target_object_id"),
            (self.target_version_id, "axis_target_version_id"),
        ):
            require_opaque_id(value, field_name)
        if self.axis_name not in AXIS_ENUMS:
            raise ValueError("axis_receipt_name_invalid")
        valid_values = {member.value for member in AXIS_ENUMS[self.axis_name]}
        if self.axis_value not in valid_values:
            raise ValueError("axis_receipt_value_invalid")
        require_text(self.rationale, "axis_receipt_rationale")
        require_iso(self.recorded_at, "axis_receipt_recorded_at")
        require_text(self.recorded_by, "axis_receipt_recorded_by")
        require_iso(self.effective_at, "axis_receipt_effective_at")
        if self.expires_at:
            require_iso(self.expires_at, "axis_receipt_expires_at")
        _require_mapping(self.scope, "axis_receipt_scope")
        if any(value == "*" for value in self.scope.values()):
            raise ValueError("axis_receipt_scope_wildcards_forbidden")
        require_research_boundary(self.research_only, self.execution_allowed)


@dataclass(frozen=True)
class ProxyBinding(ContractMixin):
    object_id: str
    version_id: str
    proxy_variable_id: str
    construct_id: str
    permitted_uses: tuple[str, ...]
    scope: Mapping[str, Any]
    limitations: tuple[str, ...]
    validation_artifact_refs: tuple[str, ...]
    expires_at: str
    created_at: str
    created_by: str
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.object_id, "proxy_binding_object_id"),
            (self.version_id, "proxy_binding_version_id"),
            (self.proxy_variable_id, "proxy_variable_id"),
            (self.construct_id, "proxy_construct_id"),
        ):
            require_opaque_id(value, field_name)
        if not self.permitted_uses or set(self.permitted_uses) - PROXY_USES:
            raise ValueError("proxy_permitted_uses_invalid")
        if len(set(self.permitted_uses)) != len(self.permitted_uses):
            raise ValueError("proxy_permitted_uses_must_be_unique")
        _require_mapping(self.scope, "proxy_scope")
        if not is_bounded_scope(self.scope):
            raise ValueError("proxy_scope_must_be_bounded_without_wildcards")
        if not self.limitations:
            raise ValueError("proxy_limitations_required")
        _require_refs(self.validation_artifact_refs, "proxy_validation_artifact_ref")
        expires = datetime.fromisoformat(
            require_iso(self.expires_at, "proxy_expires_at").replace("Z", "+00:00")
        )
        created = datetime.fromisoformat(
            require_iso(self.created_at, "proxy_created_at").replace("Z", "+00:00")
        )
        if expires <= created:
            raise ValueError("proxy_expiry_must_follow_creation")
        require_text(self.created_by, "proxy_created_by")
        require_research_boundary(self.research_only, self.execution_allowed)


@dataclass(frozen=True)
class DispositionRecord(ContractMixin):
    object_id: str
    version_id: str
    target_object_id: str
    target_version_id: str
    reviewer_id: str
    rationale: str
    decision: Decision
    decision_at: str
    scope: Mapping[str, Any]
    expires_at: str | None = None
    authority: Authority = Authority.HUMAN_REVIEWED
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.object_id, "disposition_object_id"),
            (self.version_id, "disposition_version_id"),
            (self.target_object_id, "disposition_target_object_id"),
            (self.target_version_id, "disposition_target_version_id"),
        ):
            require_opaque_id(value, field_name)
        require_text(self.reviewer_id, "disposition_reviewer_id")
        require_text(self.rationale, "disposition_rationale")
        if not isinstance(self.decision, Decision):
            raise ValueError("disposition_decision_axis_invalid")
        if self.decision == Decision.PENDING:
            raise ValueError("human_disposition_cannot_be_pending")
        if self.authority != Authority.HUMAN_REVIEWED:
            raise ValueError("disposition_requires_human_reviewed_authority")
        require_iso(self.decision_at, "disposition_decision_at")
        _require_mapping(self.scope, "disposition_scope")
        if any(value == "*" for value in self.scope.values()):
            raise ValueError("disposition_scope_wildcards_forbidden")
        if self.expires_at:
            require_iso(self.expires_at, "disposition_expires_at")
        require_research_boundary(self.research_only, self.execution_allowed)


@dataclass(frozen=True)
class AmbiguityPacket(ContractMixin):
    object_id: str
    version_id: str
    target_object_id: str
    target_version_id: str
    question: str
    known_facts: tuple[str, ...]
    missing_facts: tuple[str, ...]
    alternatives: tuple[str, ...]
    consequences: tuple[str, ...]
    safe_default: str
    created_at: str
    created_by: str
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.object_id, "ambiguity_object_id"),
            (self.version_id, "ambiguity_version_id"),
            (self.target_object_id, "ambiguity_target_object_id"),
            (self.target_version_id, "ambiguity_target_version_id"),
        ):
            require_opaque_id(value, field_name)
        require_text(self.question, "ambiguity_question")
        for values, field_name in (
            (self.known_facts, "ambiguity_known_facts"),
            (self.missing_facts, "ambiguity_missing_facts"),
            (self.alternatives, "ambiguity_alternatives"),
            (self.consequences, "ambiguity_consequences"),
        ):
            if not values:
                raise ValueError(f"{field_name}_required")
            for value in values:
                require_text(value, field_name)
        require_text(self.safe_default, "ambiguity_safe_default")
        require_iso(self.created_at, "ambiguity_created_at")
        require_text(self.created_by, "ambiguity_created_by")
        require_research_boundary(self.research_only, self.execution_allowed)


@dataclass(frozen=True)
class OntologyRelease(ContractMixin):
    release_id: str
    version: str
    released_at: str
    terms: tuple[Mapping[str, Any], ...]
    derivation_rules: tuple[Mapping[str, Any], ...]
    lifecycle_values: tuple[str, ...]
    evidence_values: tuple[str, ...]
    authority_values: tuple[str, ...]
    decision_values: tuple[str, ...]
    freshness_values: tuple[str, ...]
    admissibility_values: tuple[str, ...]
    research_only: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        require_opaque_id(self.release_id, "ontology_release_id")
        require_semver(self.version, "ontology_release_version")
        require_iso(self.released_at, "ontology_released_at")
        if not self.terms:
            raise ValueError("ontology_terms_required")
        term_ids: list[str] = []
        term_keys: list[str] = []
        for term in self.terms:
            _require_mapping(term, "ontology_term")
            term_ids.append(require_opaque_id(term.get("term_id"), "ontology_term_id"))
            term_keys.append(require_text(term.get("term_key"), "ontology_term_key"))
            require_text(term.get("definition"), "ontology_term_definition")
        if len(set(term_ids)) != len(term_ids) or len(set(term_keys)) != len(term_keys):
            raise ValueError("ontology_term_ids_and_keys_must_be_unique")
        if len(self.derivation_rules) != len(DERIVATION_RELATIONS):
            raise ValueError("ontology_derivation_rules_must_cover_exact_whitelist")
        rule_ids: list[str] = []
        rule_relations: list[str] = []
        for rule in self.derivation_rules:
            _require_mapping(rule, "ontology_derivation_rule")
            rule_id = require_text(rule.get("rule_id"), "derivation_rule_id")
            if not STABLE_DERIVATION_RULE_ID_RE.fullmatch(rule_id):
                raise ValueError("derivation_rule_id_must_be_stable")
            relation = require_text(rule.get("relation"), "derivation_rule_relation")
            if relation not in DERIVATION_RELATIONS:
                raise ValueError("ontology_derivation_relation_not_whitelisted")
            require_semver(rule.get("version"), "derivation_rule_version")
            require_text(rule.get("source_record"), "derivation_rule_source_record")
            require_text(rule.get("source_field"), "derivation_rule_source_field")
            if rule.get("deterministic") is not True:
                raise ValueError("derivation_rule_must_be_deterministic")
            if rule.get("provenance_required") is not True:
                raise ValueError("derivation_rule_must_require_provenance")
            if rule.get("semantic_authority_added") is not False:
                raise ValueError("derivation_rule_cannot_add_semantic_authority")
            if rule.get("transitive") is not False:
                raise ValueError("derivation_rule_cannot_be_transitive")
            rule_ids.append(rule_id)
            rule_relations.append(relation)
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("ontology_derivation_rule_ids_must_be_unique")
        if len(set(rule_relations)) != len(rule_relations) or set(rule_relations) != DERIVATION_RELATIONS:
            raise ValueError("ontology_derivation_rules_must_cover_exact_whitelist")
        expected_axes = {
            "lifecycle": tuple(value.value for value in Lifecycle),
            "evidence": tuple(value.value for value in Evidence),
            "authority": tuple(value.value for value in Authority),
            "decision": tuple(value.value for value in Decision),
            "freshness": tuple(value.value for value in Freshness),
            "admissibility": tuple(value.value for value in Admissibility),
        }
        actual_axes = {
            "lifecycle": self.lifecycle_values,
            "evidence": self.evidence_values,
            "authority": self.authority_values,
            "decision": self.decision_values,
            "freshness": self.freshness_values,
            "admissibility": self.admissibility_values,
        }
        if actual_axes != expected_axes:
            raise ValueError("ontology_axis_values_mismatch")
        require_research_boundary(self.research_only, self.execution_allowed)
