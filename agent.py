"""Single-hepatologist ACLF agent with separate gather and assess phases."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date, timedelta
from typing import Any, Callable, Type

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from config import ACLFConfig
from instructions import GATHER_SYSTEM, build_assess_system
from rag import TOOL_DEFS, PatientRAG, dispatch_tool
from schema import ACLFAssessment, build_json_schema

logger = logging.getLogger(__name__)


def _iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _episode_anchor_error(
    model: BaseModel, case_context: dict[str, Any]
) -> str | None:
    """Reject cross-admission and out-of-window phenotype assembly."""
    if not isinstance(model, ACLFAssessment):
        return None
    episodes = case_context.get("inpatient_episodes") or []
    pairs = {
        (str(item.get("start_date"))[:10], str(item.get("end_date"))[:10])
        for item in episodes
        if item.get("start_date") and item.get("end_date")
    }
    chosen = (model.episode_start_date, model.episode_end_date)
    if pairs and chosen not in pairs:
        return (
            "episode_start_date and episode_end_date must exactly match one supplied "
            f"inpatient episode; got {chosen}, allowed={sorted(pairs)}"
        )
    start = _iso_date(model.episode_start_date)
    end = _iso_date(model.episode_end_date)
    assessed = _iso_date(model.assessment_date)
    if start and end and (assessed is None or not start <= assessed <= end):
        return "assessment_date must fall within the selected inpatient episode"
    if start:
        lower, upper = start - timedelta(days=7), start + timedelta(days=7)
        dated_fields = [
            (f"{organ.organ}.peak_value_date", organ.peak_value_date)
            for organ in model.organs
            if organ.peak_value_date
        ]
        dated_fields.extend(
            [("wbc_date", model.wbc_date), ("sodium_date", model.sodium_date)]
        )
        dated_fields.extend(
            (
                f"decompensation_evidence[{index}].event_date",
                reference.event_date,
            )
            for index, reference in enumerate(
                model.decompensation_evidence_references
            )
            if reference.event_date
        )
        outside = [
            f"{name}={value}"
            for name, value in dated_fields
            if (parsed := _iso_date(value)) is not None
            and not lower <= parsed <= upper
        ]
        if outside:
            return (
                "acute organ/prognostic values must be within +/-7 days of admission: "
                + ", ".join(outside)
            )
    return None


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
    ) -> list[dict[str, Any]]:
        case_context = rag.case_context()
        extraction = rag.get_extraction()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": GATHER_SYSTEM},
            {
                "role": "user",
                "content": (
                    "=== VERIFIED CASE CONTEXT ===\n"
                    + json.dumps(case_context, indent=2, default=str)
                    + "\n\n=== OPTIONAL PRIOR EXTRACTION ===\n"
                    + json.dumps(extraction, indent=2, default=str)[:12000]
                    + "\n\nGather the evidence needed for all six organ systems and precipitants."
                ),
            },
        ]
        evidence: list[dict[str, Any]] = []
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

    async def assess(self, *, rag: PatientRAG, sample_id: str) -> ACLFAssessment:
        seed = _stable_seed(sample_id, "aclf_assessment")
        case_context = rag.case_context()
        evidence = await self._gather_evidence(
            rag,
            max_rounds=self._config.max_tool_rounds,
            seed=seed,
        )
        prompt = (
            f"=== CANONICAL SAMPLE ID ===\n{sample_id}\n\n"
            "=== VERIFIED CASE CONTEXT ===\n"
            + json.dumps(case_context, indent=2, default=str)
            + "\n\n=== RETRIEVED EVIDENCE ===\n"
            + _format_evidence_context(evidence)
            + "\n\nAssess exactly one supplied inpatient episode. Use the gathered "
            "evidence to distinguish genuine new/worsening acute decompensation "
            "from stable chronic disease, planned transplantation, and postoperative "
            "findings. Return all six organs in the canonical order."
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
            semantic_validator=lambda model: _episode_anchor_error(model, case_context),
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
]
