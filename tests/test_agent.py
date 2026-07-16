from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent import ACLFAgent, _episode_anchor_error, _retrieval_reference_error
from config import ACLFConfig
from tests.test_schema import valid_payload


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none=True):
        result = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return result


class FakeCompletions:
    def __init__(self, messages):
        self.responses = list(messages)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        message = self.responses.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


class FakeRAG:
    pid = 1030000000000001
    retrieval_trace = [
        {"source_ids": ["1001", "1002"]},
    ]

    def case_context(self):
        return {
            "inpatient_episodes": [
                {
                    "visit_occurrence_id": 10,
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-05",
                    "start_datetime": "2026-01-01 01:00:00",
                    "end_datetime": "2026-01-05 10:00:00",
                }
            ],
            "note_provenance": {"n_notes_found": 1},
        }

    def get_extraction(self, block=None):
        return {}

    def query_labs(self, **kwargs):
        return [{"concept_name": "Creatinine", "value": 1.0, "unit": "mg/dL"}]


@pytest.mark.asyncio
async def test_agent_uses_separate_gather_and_assess_calls(monkeypatch):
    tool_call = SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="query_labs", arguments=json.dumps({"concept": "creatinine"})),
    )
    completions = FakeCompletions(
        [
            FakeMessage(tool_calls=[tool_call]),
            FakeMessage(content="Evidence gathering complete."),
            FakeMessage(content=json.dumps(valid_payload())),
        ]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr("agent.build_assess_system", lambda: "assessment system")
    agent = ACLFAgent(
        client=client,
        model="gpt-oss:120b",
        config=ACLFConfig(max_tool_rounds=2),
    )
    result = await agent.assess(rag=FakeRAG(), sample_id=str(FakeRAG.pid))
    assert result.sample_id == str(FakeRAG.pid)
    assert len(completions.calls) == 3
    assert "tools" in completions.calls[0]
    assert "response_format" not in completions.calls[0]
    assert completions.calls[-1]["response_format"]["type"] == "json_schema"
    assert "PREFETCHED CORE LAB EVIDENCE" in completions.calls[0]["messages"][1]["content"]
    assert "aclf_core" in completions.calls[0]["messages"][1]["content"]
    assert "ALLOWED EVIDENCE SOURCE IDS" in completions.calls[-1]["messages"][1]["content"]
    assert '"1001"' in completions.calls[-1]["messages"][1]["content"]


@pytest.mark.asyncio
async def test_episode_screen_uses_one_structured_call(monkeypatch):
    payload = valid_payload()
    screen_payload = {
        "sample_id": payload["sample_id"],
        "visit_occurrence_id": payload["visit_occurrence_id"],
        "episode_start_datetime": payload["episode_start_datetime"],
        "episode_end_datetime": payload["episode_end_datetime"],
        "eligibility": payload["eligibility"],
        "decompensation_type": ["ascites"],
        "evidence_references": payload["decompensation_evidence_references"],
        "summary": "New ascites required hospital admission.",
    }
    completions = FakeCompletions([FakeMessage(content=json.dumps(screen_payload))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr("agent.build_screen_system", lambda: "screen system")
    agent = ACLFAgent(client=client, model="gpt-oss:120b", config=ACLFConfig())

    class ScreenRAG(FakeRAG):
        def search_notes(self, **kwargs):
            return []

        def query_conditions(self, **kwargs):
            return []

        def query_procedures(self, **kwargs):
            return []

        def query_medications(self, **kwargs):
            return []

    episode = ScreenRAG().case_context()["inpatient_episodes"][0]
    result = await agent.screen_episode(
        rag=ScreenRAG(), sample_id=str(FakeRAG.pid), episode=episode
    )
    assert result.visit_occurrence_id == 10
    assert len(completions.calls) == 1
    assert "tools" not in completions.calls[0]


def test_episode_anchor_rejects_cross_admission_merge():
    payload = valid_payload()
    payload["episode_end_datetime"] = "2026-02-05 10:00:00"
    from schema import ACLFAssessment

    assessment = ACLFAssessment.model_validate(payload)
    error = _episode_anchor_error(
        assessment,
        {
            "inpatient_episodes": [
                {
                    "visit_occurrence_id": 10,
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-05",
                    "start_datetime": "2026-01-01 01:00:00",
                    "end_datetime": "2026-01-05 10:00:00",
                }
            ]
        },
    )
    assert error and "must match" in error


def test_episode_anchor_accepts_equivalent_iso_datetime_format():
    from schema import ACLFAssessment

    assessment = ACLFAssessment.model_validate(valid_payload())
    error = _episode_anchor_error(
        assessment,
        {
            "inpatient_episodes": [
                {
                    "visit_occurrence_id": 10,
                    "start_datetime": "2026-01-01T01:00:00",
                    "end_datetime": "2026-01-05T10:00:00",
                }
            ]
        },
    )
    assert error is None


def test_episode_anchor_accepts_conservatively_nulled_24h_boundary_value():
    from schema import ACLFAssessment

    payload = valid_payload()
    payload["organs"][0]["peak_value_datetime"] = "2026-01-02 01:00:00"
    assessment = ACLFAssessment.model_validate(payload)
    context = FakeRAG().case_context()
    error = _episode_anchor_error(assessment, context)
    assert assessment.organs[0].clif_score is None
    assert assessment.organs[0].peak_value is None
    assert error is None


def test_unretrieved_evidence_id_is_rejected():
    from schema import ACLFAssessment

    assessment = ACLFAssessment.model_validate(valid_payload())
    assert _retrieval_reference_error(assessment, [{"source_ids": ["1001"]}])
