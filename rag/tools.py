"""OpenAI function definitions for the six internal ACLF tools."""

from __future__ import annotations

import json
from typing import Any

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": (
                "Search this patient's mapped clinical notes for hepatic "
                "encephalopathy grade, acute decompensation, precipitants, "
                "vasopressor/ventilation context, and clinical course."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Focused clinical query."},
                    "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                    "date_start": {"type": "string", "description": "Optional YYYY-MM-DD lower bound."},
                    "date_end": {"type": "string", "description": "Optional YYYY-MM-DD upper bound."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_labs",
            "description": (
                "Query timestamped structured labs. ACLF-relevant concepts include "
                "bilirubin, creatinine, INR, PaO2, FiO2, SpO2, WBC, sodium, albumin, and ammonia. "
                "Use concept='aclf_core' with a visit_occurrence_id and acute date "
                "window to retrieve compact verified representatives in one call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "concept": {
                        "type": "string",
                        "description": "Lab name or aclf_core for an all-core snapshot.",
                    },
                    "date_start": {"type": "string"},
                    "date_end": {"type": "string"},
                    "datetime_start": {
                        "type": "string",
                        "description": "Optional inclusive ISO datetime lower bound.",
                    },
                    "datetime_end": {
                        "type": "string",
                        "description": "Optional exclusive ISO datetime upper bound.",
                    },
                    "limit": {"type": "integer", "default": 50},
                    "visit_occurrence_id": {
                        "type": "integer",
                        "description": "Candidate inpatient visit ID used to prevent cross-episode mixing."
                    },
                },
                "required": ["concept"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_medications",
            "description": (
                "Query medications, including norepinephrine, vasopressin, "
                "terlipressin, lactulose, rifaximin, antibiotics, sedatives, "
                "nephrotoxins, and corticosteroids."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "concept": {"type": "string"},
                    "date_start": {"type": "string"},
                    "date_end": {"type": "string"},
                    "visit_occurrence_id": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_conditions",
            "description": "Query dated ICD diagnoses for cirrhosis, infection, AKI, bleeding, and other context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "icd_prefix": {"type": "string"},
                    "date_start": {"type": "string"},
                    "date_end": {"type": "string"},
                    "visit_occurrence_id": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_procedures",
            "description": (
                "Query dialysis/CRRT, mechanical ventilation, paracentesis, "
                "liver biopsy, imaging, and other dated procedures."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code_prefix": {"type": "string"},
                    "date_start": {"type": "string"},
                    "date_end": {"type": "string"},
                    "visit_occurrence_id": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_extraction",
            "description": "Return an optional pre-existing structured extraction; returns an empty object when unavailable.",
            "parameters": {
                "type": "object",
                "properties": {"block": {"type": "string"}},
                "required": [],
            },
        },
    },
]


def dispatch_tool(rag: Any, tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name == "search_notes":
        result = rag.search_notes(
            query=arguments["query"],
            top_k=arguments.get("top_k", 5),
            date_start=arguments.get("date_start"),
            date_end=arguments.get("date_end"),
            datetime_start=arguments.get("datetime_start"),
            datetime_end=arguments.get("datetime_end"),
        )
    elif tool_name == "query_labs":
        result = rag.query_labs(
            concept=arguments["concept"],
            date_start=arguments.get("date_start"),
            date_end=arguments.get("date_end"),
            limit=arguments.get("limit", 50),
            visit_occurrence_id=arguments.get("visit_occurrence_id"),
        )
    elif tool_name == "query_medications":
        result = rag.query_medications(
            concept=arguments.get("concept"),
            date_start=arguments.get("date_start"),
            date_end=arguments.get("date_end"),
            visit_occurrence_id=arguments.get("visit_occurrence_id"),
        )
    elif tool_name == "query_conditions":
        result = rag.query_conditions(
            icd_prefix=arguments.get("icd_prefix"),
            date_start=arguments.get("date_start"),
            date_end=arguments.get("date_end"),
            visit_occurrence_id=arguments.get("visit_occurrence_id"),
        )
    elif tool_name == "query_procedures":
        result = rag.query_procedures(
            code_prefix=arguments.get("code_prefix"),
            date_start=arguments.get("date_start"),
            date_end=arguments.get("date_end"),
            visit_occurrence_id=arguments.get("visit_occurrence_id"),
        )
    elif tool_name == "get_extraction":
        result = rag.get_extraction(block=arguments.get("block"))
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    return json.dumps(result, default=str, ensure_ascii=False)


__all__ = ["TOOL_DEFS", "dispatch_tool"]
