from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .model import Scenario


@dataclass(frozen=True)
class ScriptedIntent:
    arguments: dict[str, Any]
    self_declared_metadata: dict[str, Any]


class AgentBackend(Protocol):
    def run(self, scenario: Scenario) -> ScriptedIntent: ...


class ScriptedBackend:
    def run(self, scenario: Scenario) -> ScriptedIntent:
        # Metadata is recorded as agent text; it never enters trusted runtime facts.
        return ScriptedIntent(dict(scenario.arguments), dict(scenario.metadata))
