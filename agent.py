"""Single-hepatologist ACLF agent with separate gather and assess phases."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Type

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from config import ACLFConfig
from instructions import GATHER_SYSTEM, build_assess_system
from rag import TOOL_DEFS, PatientRAG, dispatch_tool
from schema import ACLFAssessment, build_json_schema

logger = logging.getLogger(__name__)


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
            + "\n\nAssess the most severe documented acute decompensation episode. "
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
                return response_model.model_validate(raw)
            except (json.JSONDecodeError, ValidationError) as exc:
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


__all__ = ["ACLFAgent", "_stable_seed", "_format_evidence_context"]
