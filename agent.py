"""Single-hepatologist ACLF agent with separate gather and assess phases."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable, Type

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from config import ACLFConfig
from instructions import GATHER_SYSTEM, build_assess_system, build_screen_system
from rag import TOOL_DEFS, PatientRAG, dispatch_tool
from schema import ACLFAssessment, EpisodeScreen, build_json_schema

logger = logging.getLogger(__name__)


def _iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _episode_anchor_error(
    model: BaseModel, case_context: dict[str, Any]
) -> str | None:
    """Reject cross-admission and out-of-window phenotype assembly."""
    if not isinstance(model, ACLFAssessment):
        return None
    episodes = case_context.get("inpatient_episodes") or []
    by_id = {
        int(item["visit_occurrence_id"]): item
        for item in episodes
        if item.get("visit_occurrence_id") is not None
    }
    supplied = by_id.get(model.visit_occurrence_id)
    if by_id and supplied is None:
        return (
            f"visit_occurrence_id={model.visit_occurrence_id} was not supplied; "
            f"allowed={sorted(by_id)}"
        )
    if supplied:
        expected = (
            _iso_datetime(supplied.get("start_datetime")),
            _iso_datetime(supplied.get("end_datetime")),
        )
        chosen = (
            _iso_datetime(model.episode_start_datetime),
            _iso_datetime(model.episode_end_datetime),
        )
        if None in expected or chosen != expected:
            return (
                f"episode datetimes must match visit {model.visit_occurrence_id}: "
                f"{supplied.get('start_datetime')}, {supplied.get('end_datetime')}"
            )
    start = _iso_date(model.episode_start_date)
    end = _iso_date(model.episode_end_date)
    assessed = _iso_date(model.assessment_date)
    if start and end and (assessed is None or not start <= assessed <= end):
        return "assessment_date must fall within the selected inpatient episode"
    window_start = _iso_datetime(model.baseline_window_start)
    window_end = _iso_datetime(model.baseline_window_end)
    episode_start = _iso_datetime(model.episode_start_datetime)
    if not window_start or not window_end or not episode_start:
        return "episode and baseline window datetimes must be valid ISO datetimes"
    if window_start != episode_start or window_end - window_start != timedelta(hours=24):
        return "baseline window must be [episode_start_datetime, episode_start_datetime + 24h)"
    if start:
        datetime_fields = [
            (f"{organ.organ}.peak_value_datetime", organ.peak_value_datetime)
            for organ in model.organs
            if organ.peak_value_datetime
        ]
        datetime_fields.extend(
            [
                ("wbc_datetime", model.wbc_datetime),
                ("sodium_datetime", model.sodium_datetime),
                ("albumin_datetime", model.prognostic_inputs.albumin_datetime),
            ]
        )
        outside = [
            f"{name}={value}"
            for name, value in datetime_fields
            if value is not None
            and (
                (parsed := _iso_datetime(value)) is None
                or not window_start <= parsed < window_end
            )
        ]
        if outside:
            return (
                "baseline organ/prognostic values must be within [admission, admission + 24h): "
                + ", ".join(outside)
            )
    return None


def _assessment_references(model: ACLFAssessment):
    yield from model.decompensation_evidence_references
    for organ in model.organs:
        yield from organ.evidence_references
    for precipitant in model.precipitants:
        yield from precipitant.evidence_references
    yield from model.prognostic_inputs.evidence_references
    for criterion in type(model.eligibility).model_fields:
        yield from getattr(model.eligibility, criterion).evidence_references


def _retrieval_reference_error(
    model: BaseModel, retrieval_trace: list[dict[str, Any]]
) -> str | None:
    """Require every claimed record ID to have been retrieved for this run."""
    if not isinstance(model, ACLFAssessment):
        return None
    allowed = {
        str(source_id)
        for item in retrieval_trace
        for source_id in (item.get("source_ids") or [])
    }
    unsupported = sorted(
        {
            str(reference.source_id)
            for reference in _assessment_references(model)
            if reference.source_id is not None
            and reference.source_type != "other"
            and str(reference.source_id) not in allowed
        }
    )
    if unsupported:
        allowed_text = ", ".join(sorted(allowed))
        return (
            "evidence source_ids were not retrieved in this run: "
            + ", ".join(unsupported)
            + ". Use only these retrieved source_ids: "
            + allowed_text
        )
    return None


def _screen_reference_error(
    model: BaseModel, retrieval_trace: list[dict[str, Any]]
) -> str | None:
    if not isinstance(model, EpisodeScreen):
        return None
    allowed = {
        str(source_id)
        for item in retrieval_trace
        for source_id in (item.get("source_ids") or [])
    }
    references = list(model.evidence_references)
    for criterion in type(model.eligibility).model_fields:
        references.extend(getattr(model.eligibility, criterion).evidence_references)
    unsupported = sorted(
        {
            str(reference.source_id)
            for reference in references
            if reference.source_id is not None
            and reference.source_type != "other"
            and str(reference.source_id) not in allowed
        }
    )
    return (
        "screen evidence source_ids were not retrieved: " + ", ".join(unsupported)
        if unsupported
        else None
    )


def _screen_anchor_error(model: BaseModel, episode: dict[str, Any]) -> str | None:
    if not isinstance(model, EpisodeScreen):
        return None
    if model.visit_occurrence_id != int(episode["visit_occurrence_id"]):
        return "screen visit_occurrence_id must match the supplied visit"
    expected = (
        _iso_datetime(episode.get("start_datetime")),
        _iso_datetime(episode.get("end_datetime")),
    )
    observed = (
        _iso_datetime(model.episode_start_datetime),
        _iso_datetime(model.episode_end_datetime),
    )
    return "screen episode datetimes must match the supplied visit" if observed != expected else None


def _stable_seed(*parts: Any) -> int:
    key = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    return int(digest, 16) % (2**31)


def _format_evidence_context(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return "(No additional evidence was retrieved.)"
    sections = []
    for item in evidence:
        result = str(item.get("result", ""))
        if len(result) > 8000:
            result = result[:8000] + "... [truncated]"
        sections.append(
            f"[{item.get('tool')}({json.dumps(item.get('args', {}), default=str)})]\n{result}"
        )
    return "\n\n".join(sections)


class ACLFAgent:
    """Two-phase evidence retrieval followed by strict structured extraction."""

    def __init__(
        self,
        *,
        client: AsyncOpenAI,
        model: str,
        config: ACLFConfig,
    ) -> None:
        self._client = client
        self._model = model
        self._config = config

    async def _gather_evidence(
        self,
        rag: PatientRAG,
        max_rounds: int,
        seed: int,
        case_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        case_context = case_context or rag.case_context()
        extraction = rag.get_extraction()
        evidence: list[dict[str, Any]] = []
        for episode in (case_context.get("inpatient_episodes") or [])[:5]:
            visit_id = episode.get("visit_occurrence_id")
            start = _iso_datetime(episode.get("start_datetime"))
            if visit_id is None or start is None:
                continue
            end = start + timedelta(hours=24)
            arguments = {
                "concept": "aclf_core",
                "datetime_start": start.isoformat(sep=" "),
                "datetime_end": end.isoformat(sep=" "),
                "visit_occurrence_id": int(visit_id),
                "limit": 50,
            }
            try:
                core = await asyncio.to_thread(rag.query_labs, **arguments)
            except Exception as exc:
                logger.warning("Core-lab prefetch failed for visit %s: %s", visit_id, exc)
                continue
            evidence.append(
                {
                    "tool": "query_labs",
                    "args": arguments,
                    "result": json.dumps(core, default=str, ensure_ascii=False),
                    "prefetched": True,
                }
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": GATHER_SYSTEM},
            {
                "role": "user",
                "content": (
                    "=== VERIFIED CASE CONTEXT ===\n"
                    + json.dumps(case_context, indent=2, default=str)
                    + "\n\n=== PREFETCHED CORE LAB EVIDENCE ===\n"
                    + _format_evidence_context(evidence)
                    + "\n\n=== OPTIONAL PRIOR EXTRACTION ===\n"
                    + json.dumps(extraction, indent=2, default=str)[:12000]
                    + "\n\nGather the evidence needed for all six organ systems and precipitants."
                ),
            },
        ]
        for round_index in range(max_rounds):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    tools=TOOL_DEFS,
                    tool_choice="auto",
                    temperature=self._config.temperature,
                    top_p=self._config.top_p,
                    max_tokens=self._config.gather_max_tokens,
                    seed=seed + round_index,
                    extra_body={"reasoning_effort": self._config.reasoning_effort},
                )
                recorder = getattr(rag, "record_llm_usage", None)
                if recorder and response.usage is not None:
                    usage = (
                        response.usage.model_dump()
                        if hasattr(response.usage, "model_dump")
                        else dict(response.usage)
                    )
                    recorder({"phase": "gather", **usage})
            except Exception as exc:
                logger.warning("Gather call failed in round %d: %s", round_index + 1, exc)
                if "tool" in str(exc).lower() or "function" in str(exc).lower():
                    return evidence
                raise
            message = response.choices[0].message
            if not message.tool_calls:
                break
            messages.append(message.model_dump(exclude_none=True))
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                try:
                    result = await asyncio.to_thread(dispatch_tool, rag, name, arguments)
                except Exception as exc:
                    logger.warning("Tool %s failed: %s", name, exc)
                    result = json.dumps(
                        {"error": f"{name} unavailable: {type(exc).__name__}: {exc}"}
                    )
                evidence.append({"tool": name, "args": arguments, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result[:12000],
                    }
                )
        return evidence

    async def screen_episode(
        self,
        *,
        rag: PatientRAG,
        sample_id: str,
        episode: dict[str, Any],
    ) -> EpisodeScreen:
        """One-call eligibility screen used before expensive organ assessment."""
        start_date = str(episode.get("start_date") or episode.get("start_datetime"))[:10]
        end_date = str(episode.get("end_date") or episode.get("end_datetime"))[:10]
        visit_id = int(episode["visit_occurrence_id"])
        query = (
            "new worsening ascites hepatic encephalopathy gastrointestinal bleeding "
            "infection admission planned procedure transplant postoperative HIV HCC "
            "immunosuppression severe comorbidity"
        )
        calls = [
            ("search_notes", rag.search_notes, {"query": query, "top_k": 12, "date_start": start_date, "date_end": end_date}),
            ("query_conditions", rag.query_conditions, {"date_start": start_date, "date_end": end_date, "visit_occurrence_id": visit_id}),
            ("query_procedures", rag.query_procedures, {"date_start": start_date, "date_end": end_date, "visit_occurrence_id": visit_id}),
            ("query_medications", rag.query_medications, {"date_start": start_date, "date_end": end_date, "visit_occurrence_id": visit_id}),
        ]
        evidence: list[dict[str, Any]] = []
        for name, function, arguments in calls:
            try:
                result = await asyncio.to_thread(function, **arguments)
            except Exception as exc:
                logger.warning("Eligibility screen %s failed for visit %s: %s", name, visit_id, exc)
                result = {"error": f"{type(exc).__name__}: {exc}"}
            evidence.append(
                {
                    "tool": name,
                    "args": arguments,
                    "result": json.dumps(result, default=str, ensure_ascii=False),
                }
            )
        allowed_source_ids = sorted(
            {
                str(source_id)
                for item in rag.retrieval_trace
                for source_id in (item.get("source_ids") or [])
            }
        )
        prompt = (
            f"=== CANONICAL SAMPLE ID ===\n{sample_id}\n\n"
            "=== TARGET EPISODE ===\n"
            + json.dumps(episode, indent=2, default=str)
            + "\n\n=== SCREEN EVIDENCE ===\n"
            + _format_evidence_context(evidence)
            + "\n\n=== ALLOWED EVIDENCE SOURCE IDS ===\n"
            + json.dumps(allowed_source_ids)
        )
        screen = await self._validated_call(
            messages=[
                {"role": "system", "content": build_screen_system()},
                {"role": "user", "content": prompt},
            ],
            response_model=EpisodeScreen,
            json_schema=build_json_schema(EpisodeScreen),
            max_retries=min(2, self._config.max_retries),
            seed=_stable_seed(sample_id, visit_id, "screen"),
            usage_recorder=getattr(rag, "record_llm_usage", None),
            semantic_validator=lambda model: (
                _screen_anchor_error(model, episode)
                or _screen_reference_error(model, rag.retrieval_trace)
            ),
        )
        screen.sample_id = sample_id
        return screen

    async def assess(
        self,
        *,
        rag: PatientRAG,
        sample_id: str,
        target_episode: dict[str, Any] | None = None,
        timepoint: str = "admission_baseline",
        eligibility_screen: EpisodeScreen | None = None,
    ) -> ACLFAssessment:
        seed = _stable_seed(
            sample_id,
            target_episode and target_episode.get("visit_occurrence_id"),
            timepoint,
        )
        case_context = rag.case_context()
        if target_episode is not None:
            case_context = dict(case_context)
            case_context["inpatient_episodes"] = [target_episode]
        if eligibility_screen is not None:
            case_context = dict(case_context)
            case_context["eligibility_screen"] = eligibility_screen.model_dump(mode="json")
        evidence = await self._gather_evidence(
            rag,
            max_rounds=self._config.max_tool_rounds,
            seed=seed,
            case_context=case_context,
        )
        allowed_source_ids = sorted(
            {
                str(source_id)
                for item in rag.retrieval_trace
                for source_id in (item.get("source_ids") or [])
            }
        )
        prompt = (
            f"=== CANONICAL SAMPLE ID ===\n{sample_id}\n\n"
            "=== VERIFIED CASE CONTEXT ===\n"
            + json.dumps(case_context, indent=2, default=str)
            + "\n\n=== RETRIEVED EVIDENCE ===\n"
            + _format_evidence_context(evidence)
            + "\n\n=== ALLOWED EVIDENCE SOURCE IDS ===\n"
            + json.dumps(allowed_source_ids)
            + "\nEvery non-other evidence source_id must exactly match one ID above."
            + f"\n\nRequired assessment_timepoint: {timepoint}. "
            + (
                "Assess the one supplied target visit exactly. "
                if target_episode is not None
                else "Select the earliest chronologic supplied visit that meets eligibility; do not select by severity. "
            )
            + "Use the gathered evidence to distinguish genuine new/worsening acute decompensation "
            "from stable chronic disease, planned transplantation, and postoperative "
            "findings. Use only the admission-to-<24-hour window for prognostic inputs. "
            "Return all six organs in the canonical order."
        )
        assessment = await self._validated_call(
            messages=[
                {"role": "system", "content": build_assess_system()},
                {"role": "user", "content": prompt},
            ],
            response_model=ACLFAssessment,
            json_schema=build_json_schema(ACLFAssessment),
            max_retries=self._config.max_retries,
            seed=seed + 100,
            usage_recorder=getattr(rag, "record_llm_usage", None),
            semantic_validator=lambda model: (
                (
                    f"assessment_timepoint must be {timepoint}"
                    if getattr(model, "assessment_timepoint", None) != timepoint
                    else None
                )
                or _episode_anchor_error(model, case_context)
                or _retrieval_reference_error(model, rag.retrieval_trace)
            ),
        )
        assessment.sample_id = sample_id
        return assessment

    async def _validated_call(
        self,
        *,
        messages: list[dict[str, Any]],
        response_model: Type[BaseModel],
        json_schema: dict[str, Any] | None,
        max_retries: int,
        seed: int,
        usage_recorder: Callable[[dict[str, Any]], None] | None = None,
        semantic_validator: Callable[[BaseModel], str | None] | None = None,
    ) -> BaseModel:
        current = list(messages)
        last_error: Exception | None = None
        for attempt in range(max_retries):
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": current,
                "temperature": self._config.temperature,
                "top_p": self._config.top_p,
                "max_tokens": self._config.assess_max_tokens,
                "seed": seed + attempt,
                "extra_body": {"reasoning_effort": self._config.reasoning_effort},
                "response_format": (
                    {"type": "json_schema", "json_schema": json_schema}
                    if json_schema is not None
                    else {"type": "json_object"}
                ),
            }
            try:
                response = await self._client.chat.completions.create(**kwargs)
                if usage_recorder and response.usage is not None:
                    usage = (
                        response.usage.model_dump()
                        if hasattr(response.usage, "model_dump")
                        else dict(response.usage)
                    )
                    usage_recorder({"phase": "assess", **usage})
                content = response.choices[0].message.content or "{}"
                raw = json.loads(content)
                parsed = response_model.model_validate(raw)
                if semantic_validator:
                    semantic_error = semantic_validator(parsed)
                    if semantic_error:
                        raise ValueError(semantic_error)
                return parsed
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Structured output validation failed attempt %d/%d: %s",
                    attempt + 1,
                    max_retries,
                    str(exc)[:500],
                )
                current = list(messages) + [
                    {"role": "assistant", "content": content if "content" in locals() else "{}"},
                    {
                        "role": "system",
                        "content": (
                            "The previous JSON failed validation: "
                            + str(exc)[:1000]
                            + " Return a corrected JSON object only."
                        ),
                    },
                ]
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Structured LLM call failed attempt %d/%d: %s",
                    attempt + 1,
                    max_retries,
                    exc,
                )
        raise RuntimeError(
            f"All {max_retries} structured output attempts failed: {last_error}"
        )


__all__ = [
    "ACLFAgent",
    "_stable_seed",
    "_format_evidence_context",
    "_episode_anchor_error",
    "_retrieval_reference_error",
    "_screen_anchor_error",
    "_screen_reference_error",
]
