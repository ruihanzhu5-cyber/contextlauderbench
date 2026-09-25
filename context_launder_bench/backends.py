from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from .model import Scenario


@dataclass(frozen=True)
class AgentInput:
    task_text: str
    native_input: Any


@dataclass(frozen=True)
class ToolAttempt:
    status: str
    tool_name: str | None = None
    arguments: Mapping[str, Any] | None = None
    self_declared_metadata: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None


class AgentBackend(Protocol):
    def run(self, agent_input: AgentInput) -> ToolAttempt: ...


class ScriptedBackend:
    """Deterministic fixture with the same run signature as model backends."""

    def __init__(self, scenario: Scenario):
        self.scenario = scenario

    def run(self, agent_input: AgentInput) -> ToolAttempt:
        return ToolAttempt(
            "tool_call", self.scenario.tool_name,
            dict(self.scenario.arguments), dict(self.scenario.metadata),
        )


class ToolCallModel(Protocol):
    def generate_tool_call(self, task: str, native_input: Any) -> str | Mapping[str, Any] | None: ...


def parse_tool_attempt(raw: str | Mapping[str, Any] | None) -> ToolAttempt:
    if raw is None or raw == "":
        return ToolAttempt("no_attempt")
    try:
        decoded = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return ToolAttempt("parse_error", error="invalid_json")
    if not isinstance(decoded, Mapping):
        return ToolAttempt("parse_error", error="expected_object")
    if decoded.get("type") == "no_attempt":
        return (ToolAttempt("no_attempt") if set(decoded) == {"type"}
                else ToolAttempt("parse_error", error="unexpected_fields"))
    if decoded.get("type", "tool_call") != "tool_call":
        return ToolAttempt("parse_error", error="unknown_response_type")
    if set(decoded) - {"type", "tool_name", "arguments"}:
        return ToolAttempt("parse_error", error="unexpected_fields")
    tool_name = decoded.get("tool_name")
    arguments = decoded.get("arguments")
    if (not isinstance(tool_name, str) or not tool_name
            or not isinstance(arguments, Mapping)
            or any(not isinstance(key, str) for key in arguments)):
        return ToolAttempt("parse_error", error="invalid_tool_call")
    try:
        json.dumps(dict(arguments))
    except (TypeError, ValueError):
        return ToolAttempt("parse_error", error="non_json_arguments")
    return ToolAttempt("tool_call", tool_name, dict(arguments))


class ModelBackend:
    """Generic model adapter. The model sees task and native framework input."""

    def __init__(self, model: ToolCallModel):
        self.model = model

    def run(self, agent_input: AgentInput) -> ToolAttempt:
        raw = self.model.generate_tool_call(
            agent_input.task_text, agent_input.native_input)
        return parse_tool_attempt(raw)
