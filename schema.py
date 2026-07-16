"""Pydantic schemas for evidence-grounded ACLF phenotyping."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Type, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OrganName = Literal[
    "liver", "kidney", "brain", "coagulation", "circulation", "respiration"
]
EvidenceSource = Literal["structured_ehr", "clinical_notes", "both", "none"]
Confidence = Literal["high", "moderate", "low"]
EligibilityStatus = Literal["yes", "no", "unknown"]

ORGAN_ORDER: tuple[str, ...] = (
    "liver",
    "kidney",
    "brain",
    "coagulation",
    "circulation",
    "respiration",
)


class StrictModel(BaseModel):
    """Base model that rejects fields outside the clinical contract."""

    model_config = ConfigDict(extra="forbid")


class EvidenceReference(StrictModel):
    """Traceable source record supporting a clinical assertion."""

    source_type: Literal[
        "clinical_note",
        "measurement",
        "drug_exposure",
        "condition_occurrence",
        "procedure_occurrence",
        "other",
    ] = Field(description="Source table or narrative source category.")
    source_id: str | None = Field(
        description=(
            "Report ID for a note or OMOP record ID for structured evidence; "
            "null only when the source has no record identifier."
        )
    )
    event_date: str | None = Field(description="ISO date of the evidence, or null.")
    description: str = Field(
        min_length=5,
        description="Concise value, finding, medication, diagnosis, or procedure.",
    )
    quote: str | None = Field(
        description="Short verbatim note excerpt for narrative evidence, otherwise null."
    )

    @model_validator(mode="after")
    def validate_record_identifier(self) -> "EvidenceReference":
        if self.source_type != "other" and not self.source_id:
            raise ValueError(f"{self.source_type} evidence requires a source_id")
        return self


class OrganAssessment(StrictModel):
    """Assessment of one organ system using EASL-CLIF-C OF criteria."""

    organ: OrganName = Field(description="Organ system being assessed.")
    peak_value: float | None = Field(
        description=(
            "Worst relevant numeric value during the acute episode. Use null when "
            "the value is unavailable; never infer a normal value."
        )
    )
    peak_value_unit: str | None = Field(
        description="Unit for peak_value, or null when no numeric value is available."
    )
    peak_value_date: str | None = Field(
        description="ISO date for peak_value, or null when unknown."
    )
    peak_value_datetime: str | None = Field(
        description="ISO datetime for a structured numeric peak, or null."
    )
    clinical_finding: str | None = Field(
        description=(
            "Worst non-numeric finding, such as HE grade III, sustained "
            "norepinephrine, RRT, or mechanical ventilation context."
        )
    )
    clif_score: int | None = Field(
        default=None,
        ge=1,
        le=3,
        description=(
            "CLIF-C OF sub-score: 1 normal, 2 dysfunction, 3 failure. Use null "
            "when missing evidence prevents defensible scoring."
        ),
    )
    evidence_source: EvidenceSource = Field(
        description="Source category for the evidence supporting this assessment."
    )
    evidence_text: str = Field(
        description="Specific supporting values or a short verbatim note excerpt."
    )
    evidence_references: list[EvidenceReference] = Field(
        description="Traceable report or OMOP record references supporting the score."
    )
    reasoning: str = Field(
        min_length=10,
        description="Clinical reasoning tying evidence to the CLIF-C OF criterion.",
    )
    confidence: Confidence = Field(description="Confidence in this organ assessment.")
    missing_data_reason: str | None = Field(
        default=None,
        description="Why the organ could not be scored, or null when it was scored.",
    )

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> "OrganAssessment":
        if self.clif_score is None:
            if not self.missing_data_reason:
                raise ValueError("missing_data_reason is required when clif_score is null")
            if self.confidence != "low":
                raise ValueError("an indeterminate organ score must have low confidence")
            return self

        if self.missing_data_reason is not None:
            raise ValueError("missing_data_reason must be null when clif_score is assigned")
        if not self.evidence_references:
            raise ValueError("a scored organ requires at least one evidence reference")

        if self.organ in {"liver", "coagulation"} and self.peak_value is None:
            raise ValueError(f"peak_value is required to score {self.organ}")
        if (
            self.organ == "kidney"
            and self.peak_value is None
            and not self.clinical_finding
        ):
            raise ValueError("kidney scoring requires creatinine or an RRT finding")
        if (
            self.organ in {"liver", "kidney", "coagulation"}
            and self.peak_value is not None
            and (self.peak_value_date is None or self.peak_value_datetime is None)
        ):
            raise ValueError(
                f"peak_value_date and peak_value_datetime are required when numeric {self.organ} evidence is scored"
            )
        return self


class Precipitant(StrictModel):
    """Documented precipitant of acute decompensation."""

    type: Literal[
        "bacterial_infection",
        "alcohol_related_hepatitis",
        "gi_hemorrhage_with_shock",
        "drug_induced_brain_injury",
        "drug_induced_kidney_injury",
        "hbv_reactivation",
        "hev_infection",
        "other",
        "none_identified",
    ] = Field(description="Precipitant category from the ACLF clinical reference.")
    subtype: str | None = Field(
        description="Specific subtype, such as SBP, pneumonia, or UTI, when applicable."
    )
    evidence_text: str = Field(
        description="Specific documented evidence supporting the precipitant."
    )
    evidence_references: list[EvidenceReference] = Field(
        description="Traceable source records supporting this precipitant."
    )
    confidence: Confidence = Field(description="Confidence in precipitant attribution.")


class EligibilityCriterion(StrictModel):
    """Evidence-grounded status for one study eligibility criterion."""

    status: EligibilityStatus = Field(
        description="yes/no/unknown; unknown is required when the chart cannot decide it."
    )
    reasoning: str = Field(
        min_length=5, description="Concise explanation tied to retrieved evidence."
    )
    evidence_references: list[EvidenceReference] = Field(
        default_factory=list,
        description="Traceable evidence; may be empty only when status is unknown.",
    )

    @model_validator(mode="after")
    def evidence_for_known_status(self) -> "EligibilityCriterion":
        if self.status != "unknown" and not self.evidence_references:
            raise ValueError("known eligibility status requires evidence")
        return self


class EpisodeEligibility(StrictModel):
    """CANONIC/PREDICT-aligned eligibility information at admission."""

    canonical_acute_decompensation: EligibilityCriterion
    non_elective_admission: EligibilityCriterion
    scheduled_procedure_or_treatment: EligibilityCriterion
    prior_liver_transplant: EligibilityCriterion
    hcc_outside_milan: EligibilityCriterion
    hiv: EligibilityCriterion
    immunosuppression: EligibilityCriterion
    severe_extrahepatic_disease: EligibilityCriterion


class EpisodeScreen(StrictModel):
    """Lightweight chronological eligibility screen before full organ assessment."""

    sample_id: str
    visit_occurrence_id: int
    episode_start_datetime: str
    episode_end_datetime: str
    eligibility: EpisodeEligibility
    decompensation_type: list[
        Literal["ascites", "encephalopathy", "gi_hemorrhage", "infection"]
    ]
    evidence_references: list[EvidenceReference]
    summary: str = Field(min_length=10)
    normalization_warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_unsupported_screen_claims(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        warnings = list(data.get("normalization_warnings") or [])
        eligibility = {
            name: dict(value) if isinstance(value, dict) else value
            for name, value in (data.get("eligibility") or {}).items()
        }
        canonical = eligibility.get("canonical_acute_decompensation")
        screen_refs = list(data.get("evidence_references") or [])
        if (
            isinstance(canonical, dict)
            and canonical.get("status") == "yes"
            and not canonical.get("evidence_references")
            and screen_refs
        ):
            canonical["evidence_references"] = screen_refs
            warnings.append("canonical acute decompensation reused screen evidence")
        for name, criterion in eligibility.items():
            if (
                isinstance(criterion, dict)
                and criterion.get("status") in {"yes", "no"}
                and not criterion.get("evidence_references")
            ):
                prior = criterion.get("status")
                criterion["status"] = "unknown"
                criterion["reasoning"] = (
                    f"Unsupported {prior} normalized to unknown: "
                    + str(criterion.get("reasoning") or "no traceable evidence")
                )
                warnings.append(f"eligibility.{name}: unsupported {prior} -> unknown")
        data["eligibility"] = eligibility
        if isinstance(canonical, dict) and canonical.get("status") != "yes":
            data["decompensation_type"] = []
        data["normalization_warnings"] = list(dict.fromkeys(warnings))
        return data

    @model_validator(mode="after")
    def validate_canonical_screen(self) -> "EpisodeScreen":
        canonical = self.eligibility.canonical_acute_decompensation.status == "yes"
        if canonical and not self.decompensation_type:
            raise ValueError("confirmed acute decompensation requires a canonical type")
        return self


class PrognosticInputs(StrictModel):
    """Additional admission-time inputs required by comparator scores."""

    serum_albumin: float | None = Field(default=None, gt=0, description="Albumin in g/dL.")
    albumin_datetime: str | None = Field(
        default=None, description="ISO datetime of the admission albumin value."
    )
    ascites_severity: Literal["none", "mild", "moderate_severe", "unknown"] = Field(
        description="Admission ascites severity for Child-Pugh scoring."
    )
    hepatic_encephalopathy_grade: int | None = Field(
        default=None, ge=0, le=4, description="West Haven grade at admission."
    )
    renal_replacement_therapy: bool | None = Field(
        default=None,
        description="Dialysis/RRT at admission or at least twice in the preceding 7 days.",
    )
    evidence_references: list[EvidenceReference] = Field(
        default_factory=list,
        description="Evidence supporting albumin, ascites, HE and RRT inputs.",
    )

    @model_validator(mode="after")
    def albumin_has_datetime(self) -> "PrognosticInputs":
        if self.serum_albumin is not None and self.albumin_datetime is None:
            raise ValueError("albumin_datetime is required when serum_albumin is present")
        return self


class ACLFAssessment(StrictModel):
    """Complete ACLF assessment for one patient and acute episode."""

    sample_id: str = Field(description="Persistent OMOP person identifier.")
    assessment_timepoint: Literal["admission_baseline", "aclf_diagnosis", "follow_up"] = Field(
        description="Prespecified prognostic time zero represented by this assessment."
    )
    visit_occurrence_id: int = Field(
        description="Exact OMOP inpatient visit identifier for this assessment."
    )
    episode_start_datetime: str = Field(description="Exact inpatient admission datetime.")
    episode_end_datetime: str = Field(description="Exact inpatient discharge datetime.")
    baseline_window_start: str = Field(
        description="ISO datetime equal to episode_start_datetime."
    )
    baseline_window_end: str = Field(
        description="ISO datetime exactly 24 hours after baseline_window_start; exclusive."
    )
    eligibility: EpisodeEligibility
    assessment_date: str = Field(description="ISO date of assessment.")
    has_acute_decompensation: bool = Field(
        description="Whether new or worsening acute decompensation was documented."
    )
    decompensation_type: list[
        Literal[
            "ascites",
            "encephalopathy",
            "gi_hemorrhage",
            "infection",
            "jaundice",
            "other",
        ]
    ] = Field(description="Documented types of acute decompensation.")
    decompensation_evidence_references: list[EvidenceReference] = Field(
        description=(
            "Traceable records supporting new/worsening acute decompensation; "
            "when acute decompensation is false, may instead document evidence "
            "against eligibility."
        )
    )
    organs: list[OrganAssessment] = Field(
        min_length=6,
        max_length=6,
        description="Exactly six assessments, one for each CLIF-C organ system.",
    )
    precipitants: list[Precipitant] = Field(
        description="All supported precipitants, or one none_identified item."
    )
    age_years: int | None = Field(
        default=None, ge=0, le=130, description="Age at the assessed episode."
    )
    wbc_count: float | None = Field(
        default=None, gt=0, description="WBC count in 10^9/L closest to the episode."
    )
    wbc_date: str | None = Field(default=None, description="ISO date of WBC value.")
    wbc_datetime: str | None = Field(default=None, description="ISO datetime of WBC value.")
    serum_sodium: float | None = Field(
        default=None,
        gt=80,
        lt=200,
        description="Serum sodium in mEq/L closest to the episode.",
    )
    sodium_date: str | None = Field(
        default=None, description="ISO date of serum sodium value."
    )
    sodium_datetime: str | None = Field(
        default=None, description="ISO datetime of serum sodium value."
    )
    prognostic_inputs: PrognosticInputs
    clinical_summary: str = Field(
        min_length=20,
        description="Three-to-five sentence evidence-grounded acute episode summary.",
    )
    data_quality: Literal["sufficient", "limited", "insufficient"] = Field(
        description="Overall completeness of evidence for ACLF phenotyping."
    )
    episode_start_date: str | None = Field(
        description="ISO start date of the assessed hospitalization or null."
    )
    episode_end_date: str | None = Field(
        description="ISO end date of the assessed hospitalization or null."
    )
    normalization_warnings: list[str] = Field(
        default_factory=list,
        description="Deterministic conservative normalizations applied before scoring.",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_unsupported_claims(cls, raw: Any) -> Any:
        """Downgrade unsupported claims to unknown/null instead of guessing."""
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        warnings = list(data.get("normalization_warnings") or [])

        eligibility = {
            name: dict(value) if isinstance(value, dict) else value
            for name, value in (data.get("eligibility") or {}).items()
        }
        canonical = eligibility.get("canonical_acute_decompensation")
        decomp_refs = list(data.get("decompensation_evidence_references") or [])
        if (
            isinstance(canonical, dict)
            and canonical.get("status") == "yes"
            and not canonical.get("evidence_references")
            and decomp_refs
        ):
            canonical["evidence_references"] = decomp_refs
            warnings.append("canonical acute decompensation reused its traceable episode evidence")
        for name, criterion in eligibility.items():
            if (
                isinstance(criterion, dict)
                and criterion.get("status") in {"yes", "no"}
                and not criterion.get("evidence_references")
            ):
                prior = criterion.get("status")
                criterion["status"] = "unknown"
                criterion["reasoning"] = (
                    f"Unsupported {prior} normalized to unknown: "
                    + str(criterion.get("reasoning") or "no traceable evidence")
                )
                warnings.append(f"eligibility.{name}: unsupported {prior} -> unknown")
        data["eligibility"] = eligibility
        if isinstance(canonical, dict) and canonical.get("status") != "yes":
            if data.get("has_acute_decompensation") is True:
                warnings.append("unsupported acute decompensation -> not confirmed")
            data["has_acute_decompensation"] = False
            data["decompensation_type"] = []

        try:
            window_start = datetime.fromisoformat(
                str(data.get("baseline_window_start")).replace("Z", "+00:00")
            )
            window_end = datetime.fromisoformat(
                str(data.get("baseline_window_end")).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            window_start = window_end = None

        def in_window(value: Any) -> bool:
            if not value or window_start is None or window_end is None:
                return False
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return False
            return window_start <= parsed < window_end

        normalized_organs = []
        for item in data.get("organs") or []:
            organ = dict(item) if isinstance(item, dict) else item
            if not isinstance(organ, dict):
                normalized_organs.append(organ)
                continue
            scored = organ.get("clif_score") is not None
            numeric = organ.get("organ") in {"liver", "kidney", "coagulation"}
            unsupported = scored and not organ.get("evidence_references")
            invalid_numeric = scored and numeric and (
                organ.get("peak_value") is None
                or not organ.get("peak_value_date")
                or not in_window(organ.get("peak_value_datetime"))
            )
            if unsupported or invalid_numeric:
                reason = (
                    "No traceable evidence for assigned organ score"
                    if unsupported
                    else "Numeric organ value missing or outside the baseline 24-hour window"
                )
                warnings.append(f"organ.{organ.get('organ')}: score -> indeterminate ({reason})")
                organ["clif_score"] = None
                organ["confidence"] = "low"
                organ["missing_data_reason"] = reason
                if numeric:
                    organ["peak_value"] = None
                    organ["peak_value_unit"] = None
                    organ["peak_value_date"] = None
                    organ["peak_value_datetime"] = None
            normalized_organs.append(organ)
        data["organs"] = normalized_organs

        for value_name, date_name, datetime_name in (
            ("wbc_count", "wbc_date", "wbc_datetime"),
            ("serum_sodium", "sodium_date", "sodium_datetime"),
        ):
            if data.get(value_name) is not None and not in_window(data.get(datetime_name)):
                warnings.append(f"{value_name}: missing/out-of-window datetime -> null")
                data[value_name] = None
                data[date_name] = None
                data[datetime_name] = None

        prognostic = dict(data.get("prognostic_inputs") or {})
        if prognostic.get("serum_albumin") is not None and not in_window(
            prognostic.get("albumin_datetime")
        ):
            warnings.append("serum_albumin: missing/out-of-window datetime -> null")
            prognostic["serum_albumin"] = None
            prognostic["albumin_datetime"] = None
        data["prognostic_inputs"] = prognostic
        data["normalization_warnings"] = list(dict.fromkeys(warnings))
        return data

    @field_validator("sample_id")
    @classmethod
    def sample_id_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("sample_id must not be empty")
        return value

    @model_validator(mode="after")
    def validate_organs_and_precipitants(self) -> "ACLFAssessment":
        names = [organ.organ for organ in self.organs]
        if len(names) != 6 or set(names) != set(ORGAN_ORDER):
            raise ValueError(
                "organs must contain exactly one of each: " + ", ".join(ORGAN_ORDER)
            )
        self.organs = sorted(self.organs, key=lambda item: ORGAN_ORDER.index(item.organ))

        precipitant_types = [item.type for item in self.precipitants]
        if "none_identified" in precipitant_types and len(precipitant_types) > 1:
            raise ValueError("none_identified cannot be combined with other precipitants")
        if not self.has_acute_decompensation and self.decompensation_type:
            raise ValueError(
                "decompensation_type must be empty when acute decompensation is absent"
            )
        if self.has_acute_decompensation and not self.decompensation_evidence_references:
            raise ValueError(
                "acute decompensation requires at least one evidence reference"
            )
        if self.wbc_count is not None and self.wbc_datetime is None:
            raise ValueError("wbc_datetime is required when wbc_count is present")
        if self.serum_sodium is not None and self.sodium_datetime is None:
            raise ValueError("sodium_datetime is required when serum_sodium is present")
        canonical_types = {"ascites", "encephalopathy", "gi_hemorrhage", "infection"}
        if self.eligibility.canonical_acute_decompensation.status == "yes":
            if not canonical_types.intersection(self.decompensation_type):
                raise ValueError(
                    "canonical acute decompensation requires ascites, encephalopathy, "
                    "GI hemorrhage, or infection"
                )
        if self.has_acute_decompensation != (
            self.eligibility.canonical_acute_decompensation.status == "yes"
        ):
            raise ValueError(
                "has_acute_decompensation must agree with canonical_acute_decompensation"
            )
        return self


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Union and type(None) in args:
        remaining = [arg for arg in args if arg is not type(None)]
        if len(remaining) == 1:
            return remaining[0], True
    return annotation, False


def _describe_field(name: str, info: Any, indent: int = 0) -> list[str]:
    prefix = "  " * indent
    inner, optional = _unwrap_optional(info.annotation)
    suffix = " (nullable)" if optional else ""
    description = info.description or name
    origin = get_origin(inner)
    lines = [f"{prefix}- {name}{suffix}: {description}"]
    if origin is list:
        args = get_args(inner)
        if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
            lines.append(f"{prefix}  Each list item contains:")
            for sub_name, sub_info in args[0].model_fields.items():
                lines.extend(_describe_field(sub_name, sub_info, indent + 2))
    elif isinstance(inner, type) and issubclass(inner, Enum):
        values = [member.value for member in inner]
        lines[-1] += f" Allowed values: {values}."
    elif isinstance(inner, type) and issubclass(inner, BaseModel):
        for sub_name, sub_info in inner.model_fields.items():
            lines.extend(_describe_field(sub_name, sub_info, indent + 1))
    return lines


def build_format_instructions(
    model: Type[BaseModel] | None = None,
) -> str:
    """Render schema-derived LLM output instructions without prompt drift."""
    model = model or ACLFAssessment
    lines = [
        "Respond with one JSON object conforming to this schema:",
        "",
        f"Root model: {model.__name__}",
        "",
    ]
    for name, info in model.model_fields.items():
        lines.extend(_describe_field(name, info))
    lines.extend(
        [
            "",
            "Use null when evidence is unavailable. Never infer normal findings.",
            "Use only evidence documented for this patient and episode.",
            "Output valid JSON only. Do not use markdown fences or commentary.",
        ]
    )
    return "\n".join(lines)


def build_json_schema(model: Type[BaseModel] | None = None) -> dict[str, Any]:
    """Build the OpenAI-compatible strict JSON schema envelope."""
    model = model or ACLFAssessment
    return {"name": model.__name__, "schema": model.model_json_schema(), "strict": True}


__all__ = [
    "ACLFAssessment",
    "OrganAssessment",
    "Precipitant",
    "EligibilityCriterion",
    "EpisodeEligibility",
    "EpisodeScreen",
    "PrognosticInputs",
    "EvidenceReference",
    "ORGAN_ORDER",
    "build_format_instructions",
    "build_json_schema",
]
