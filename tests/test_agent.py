from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent import ACLFAgent, _episode_anchor_error
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

    def case_context(self):
        return {
            "inpatient_episodes": [
                {"start_date": "2026-01-01", "end_date": "2026-01-05"}
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


def test_episode_anchor_rejects_cross_admission_merge():
    payload = valid_payload()
    payload["episode_end_date"] = "2026-02-05"
    from schema import ACLFAssessment

    assessment = ACLFAssessment.model_validate(payload)
    error = _episode_anchor_error(
        assessment,
        {"inpatient_episodes": [{"start_date": "2026-01-01", "end_date": "2026-01-05"}]},
    )
    assert error and "exactly match" in error
