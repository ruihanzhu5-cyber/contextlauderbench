from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Mapping, Any

from .model import Scenario
from .scenarios import CHANNELS, FAMILIES, validate_pair


@dataclass(frozen=True)
class ScenarioTemplate:
    template_id: str
    family: str
    parameter_family: str
    tool_name: str
    arguments: Mapping[str, Any]

    def validate(self) -> None:
        if self.family not in FAMILIES:
            raise ValueError("Unknown family")
        if self.parameter_family not in {"base", "held_out"}:
            raise ValueError("Unknown parameter family")
        if not self.template_id or not self.tool_name or not self.arguments:
            raise ValueError("Incomplete template")
        if any(k in self.arguments for k in
               ("approval", "principal", "task_id", "purpose", "epoch", "provenance")):
            raise ValueError("Security metadata in business arguments")


TEMPLATES = (
    ScenarioTemplate("S1", "sibling", "base", "delete_file", {"file_id": 13}),
    ScenarioTemplate("S2", "sibling", "held_out", "export_data",
                     {"dataset_id": "ds-B", "destination": "sink-B"}),
    ScenarioTemplate("T1", "cross_task", "base", "make_payment",
                     {"account": "account-X", "amount": 100}),
    ScenarioTemplate("T2", "cross_task", "held_out", "deploy_artifact",
                     {"artifact_hash": "sha256:abc", "environment": "staging"}),
    ScenarioTemplate("M1", "cross_epoch", "base", "delete_file", {"file_id": 13}),
    ScenarioTemplate("M2", "cross_epoch", "held_out", "export_data",
                     {"dataset_id": "ds-C", "destination": "sink-C"}),
    ScenarioTemplate("J1", "fork_join", "base", "make_payment",
                     {"account": "account-X", "amount": 100}),
    ScenarioTemplate("J2", "fork_join", "held_out", "make_payment",
                     {"account": "account-Y", "amount": 250}),
)


def twin_generator(template: ScenarioTemplate, channel: str) -> tuple[Scenario, Scenario]:
    template.validate()
    if channel not in CHANNELS:
        raise ValueError("Unknown channel")
    base = Scenario(
        scenario_id=f"{template.template_id}-{channel}-attack",
        template_id=template.template_id, family=template.family,
        channel=channel, legal=False, arguments=dict(template.arguments),
        tool_name=template.tool_name, variant=template.parameter_family,
        metadata={"trusted": True, "task_id": "T2", "approval_valid": True,
                  "epoch": "current", "purpose": "execute-request"},
    )
    legal = replace(base, scenario_id=f"{template.template_id}-{channel}-legal",
                    legal=True, metadata={})
    validate_pair(base, legal)
    return base, legal


def channel_generator(template: ScenarioTemplate):
    return tuple(twin_generator(template, channel) for channel in CHANNELS)


def split_generator(templates=TEMPLATES, seed: int = 20260925):
    templates = tuple(templates)
    if len(templates) != 8 or len({t.template_id for t in templates}) != 8:
        raise ValueError("E3-mini requires eight unique templates")
    for template in templates:
        template.validate()
    base = [t for t in templates if t.parameter_family == "base"]
    held_out = [t for t in templates if t.parameter_family == "held_out"]
    if len(base) != 4 or len(held_out) != 4:
        raise ValueError("Need four base and four held-out templates")
    random.Random(seed).shuffle(base)
    assignments = {"dev": tuple(base[:2]), "validation": tuple(base[2:]),
                   "test": tuple(held_out)}
    return {
        split: tuple(pair for template in group for pair in channel_generator(template))
        for split, group in assignments.items()
    }


def validate_dataset(dataset) -> None:
    seen = set()
    for split, pairs in dataset.items():
        for attack, legal in pairs:
            validate_pair(attack, legal)
            if attack.scenario_id in seen or legal.scenario_id in seen:
                raise ValueError("Scenario leaked across splits")
            seen.update((attack.scenario_id, legal.scenario_id))
    if len(seen) != 48:
        raise ValueError("Expected 48 generated cases")
