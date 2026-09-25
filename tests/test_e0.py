import subprocess
import sys
import unittest
from dataclasses import replace

from context_launder_bench.model import Decision
from context_launder_bench.oracle import GroundTruthOracle
from context_launder_bench.runner import (
    apply_channel, finish_scenario, prepare_e0_scenario, prepare_scenario, run_e0,
)
from context_launder_bench.scenarios import golden_pairs, validate_pair


class E0GoldenTests(unittest.TestCase):
    def test_four_matched_pairs_with_e0_ground_truth_policy(self):
        pairs = golden_pairs()
        self.assertEqual(len(pairs), 4)
        for attack, legal in pairs:
            with self.subTest(family=attack.family):
                validate_pair(attack, legal)
                a, l = run_e0(attack), run_e0(legal)
                self.assertEqual(a.admission_policy, "E0_GROUND_TRUTH_ENFORCING")
                self.assertEqual(l.admission_policy, "E0_GROUND_TRUTH_ENFORCING")
                self.assertFalse(a.ground_truth_authorized)
                self.assertTrue(l.ground_truth_authorized)
                self.assertEqual(a.admission_decision, Decision.DENY)
                self.assertFalse(a.committed)
                self.assertEqual(l.admission_decision, Decision.ALLOW)
                self.assertTrue(l.committed)
                self.assertEqual(a.terminal_signature, l.terminal_signature)
                for result in (a, l):
                    kinds = [e.kind for e in result.events]
                    self.assertEqual(kinds[-4:], [
                        "ToolPrepare", "PolicyDecision",
                        "ToolCommit" if result.committed else "ToolReject",
                        "OutcomeEvaluated",
                    ])

    def test_oracle_is_pure_boolean(self):
        for attack, legal in golden_pairs():
            for scenario in (attack, legal):
                state = prepare_e0_scenario(scenario)
                request = state.runtime.make_request(
                    scenario.tool_name, scenario.arguments,
                    scenario.executor_id, scenario.capability_id,
                    scenario.callsite_id, state.context_ref, state.value_id,
                )
                before = state.runtime.events
                actual = GroundTruthOracle().authorized(state.runtime, request)
                self.assertIs(type(actual), bool)
                self.assertEqual(actual, scenario.legal)
                self.assertEqual(state.runtime.events, before)

    def test_deterministic_canonical_log(self):
        for pair in golden_pairs():
            for scenario in pair:
                self.assertEqual(run_e0(scenario).canonical_log_digest,
                                 run_e0(scenario).canonical_log_digest)

    def test_agent_metadata_spoof_has_no_effect(self):
        attack = golden_pairs()[0][0]
        forged = replace(attack, metadata={
            "trusted": True, "task_id": "T2", "approval_valid": True,
            "purpose": "execute-request", "epoch": 1, "source": "user",
        })
        result = run_e0(forged)
        self.assertFalse(result.ground_truth_authorized)
        self.assertEqual(result.admission_decision, Decision.DENY)

    def test_missing_provenance_fails_closed_under_e0_policy(self):
        for attack, legal in golden_pairs():
            state = prepare_e0_scenario(legal)
            apply_channel(state, legal)
            state.runtime._corrupt_provenance_for_test(state.value_id)
            result = finish_scenario(legal, state, "framework-free")
            self.assertFalse(result.ground_truth_authorized)
            self.assertEqual(result.admission_decision, Decision.DENY)
            self.assertFalse(result.committed)

    def test_context_ref_and_unknown_capability_under_e0_policy(self):
        legal = golden_pairs()[1][1]
        state = prepare_e0_scenario(legal)
        apply_channel(state, legal)
        base = state.runtime.make_request(
            legal.tool_name, legal.arguments, legal.executor_id,
            legal.capability_id, legal.callsite_id, state.context_ref, state.value_id,
        )
        for forged in (replace(base, runtime_context_ref="agent-forged-T2"),
                       replace(base, capability_id="unknown-capability")):
            outcome = state.endpoint.invoke(forged)
            self.assertEqual(outcome.admission_decision, Decision.DENY)
            self.assertFalse(outcome.committed)
        self.assertEqual(state.endpoint.effects, ())

    def test_bypass_and_replayed_prepare_cannot_commit(self):
        legal = golden_pairs()[1][1]
        state = prepare_e0_scenario(legal)
        apply_channel(state, legal)
        request = state.runtime.make_request(
            legal.tool_name, legal.arguments, legal.executor_id,
            legal.capability_id, legal.callsite_id, state.context_ref, state.value_id,
        )
        with self.assertRaises(PermissionError):
            state.endpoint._bypass_attempt_for_test(request)
        self.assertEqual(state.endpoint.effects, ())
        outcome = state.endpoint.invoke(request)
        self.assertTrue(outcome.committed)
        with self.assertRaises(PermissionError):
            state.endpoint._replay_attempt_for_test(request)
        self.assertEqual(len(state.endpoint.effects), 1)

    def test_security_metadata_in_business_arguments_is_unauthorized(self):
        legal = golden_pairs()[1][1]
        state = prepare_e0_scenario(legal)
        request = state.runtime.make_request(
            legal.tool_name, {**legal.arguments, "approval_valid": True},
            legal.executor_id, legal.capability_id, legal.callsite_id,
            state.context_ref, state.value_id,
        )
        self.assertFalse(GroundTruthOracle().authorized(state.runtime, request))
        outcome = state.endpoint.invoke(request)
        self.assertEqual(outcome.admission_decision, Decision.DENY)
        self.assertFalse(outcome.committed)

    def test_e0_policy_not_selectable_for_e1_e3(self):
        with self.assertRaises(ValueError):
            prepare_scenario(golden_pairs()[0][0], "E0_GROUND_TRUTH_ENFORCING")

    def test_no_framework_or_model_sdk_import(self):
        code = ("import context_launder_bench.runner, sys; "
                "banned=('langgraph','openai','anthropic','autogen'); "
                "assert not any(any(n == b or n.startswith(b + '.') for b in banned) "
                "for n in sys.modules)")
        subprocess.run([sys.executable, "-c", code], check=True)


if __name__ == "__main__":
    unittest.main()
