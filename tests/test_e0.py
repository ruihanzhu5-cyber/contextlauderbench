import subprocess
import sys
import unittest
from dataclasses import replace

from context_launder_bench.endpoint import UnifiedMockEndpoint
from context_launder_bench.model import Decision, ToolRequest
from context_launder_bench.oracle import AuthorizationOracle
from context_launder_bench.runner import apply_channel, finish_scenario, prepare_scenario, run_free
from context_launder_bench.scenarios import golden_pairs, validate_pair


class E0GoldenTests(unittest.TestCase):
    def test_four_matched_pairs(self):
        pairs = golden_pairs()
        self.assertEqual(len(pairs), 4)
        for attack, legal in pairs:
            with self.subTest(family=attack.family):
                validate_pair(attack, legal)
                a, l = run_free(attack), run_free(legal)
                self.assertEqual(a.decision, Decision.DENY)
                self.assertFalse(a.committed)
                self.assertEqual(l.decision, Decision.ALLOW)
                self.assertTrue(l.committed)
                self.assertEqual(a.terminal_signature, l.terminal_signature)
                for result in (a, l):
                    kinds = [e.kind for e in result.events]
                    self.assertEqual(kinds[-3 if result.committed else -3], "ToolPrepare")
                    self.assertEqual(kinds[-2], "PolicyDecision")
                    self.assertEqual(kinds[-1], "ToolCommit" if result.committed else "ToolReject")

    def test_deterministic_canonical_log(self):
        for pair in golden_pairs():
            for scenario in pair:
                self.assertEqual(run_free(scenario).canonical_log_digest,
                                 run_free(scenario).canonical_log_digest)

    def test_agent_metadata_spoof_has_no_effect(self):
        attack = golden_pairs()[0][0]
        forged = replace(attack, metadata={
            "trusted": True, "task_id": "T2", "approval_valid": True,
            "purpose": "execute-request", "epoch": 1, "source": "user"
        })
        self.assertEqual(run_free(forged).decision, Decision.DENY)

    def test_missing_provenance_fails_closed(self):
        for attack, legal in golden_pairs():
            state = prepare_scenario(legal)
            apply_channel(state, legal)
            state.runtime._corrupt_provenance_for_test(state.value_id)
            result = finish_scenario(legal, state, "framework-free")
            self.assertEqual(result.decision, Decision.DENY)
            self.assertEqual(result.reason_code, "MISSING_PROVENANCE")
            self.assertFalse(result.committed)

    def test_context_ref_substitution_and_unknown_capability(self):
        legal = golden_pairs()[1][1]
        state = prepare_scenario(legal)
        apply_channel(state, legal)
        base = state.runtime.make_request(legal.tool_name, legal.arguments,
            legal.executor_id, legal.capability_id, legal.callsite_id,
            state.context_ref, state.value_id)
        forged = replace(base, runtime_context_ref="agent-forged-T2")
        result = state.endpoint.invoke(forged, legal.family)
        self.assertEqual(result.decision, Decision.DENY)
        self.assertEqual(result.reason_code, "UNKNOWN_CONTEXT")
        bad_cap = replace(base, capability_id="unknown-capability")
        result2 = state.endpoint.invoke(bad_cap, legal.family)
        self.assertEqual(result2.decision, Decision.DENY)
        self.assertEqual(result2.reason_code, "UNKNOWN_OR_INVALID_CAPABILITY")
        self.assertEqual(state.endpoint.effects, ())

    def test_bypass_and_replayed_prepare_cannot_commit(self):
        legal = golden_pairs()[1][1]
        state = prepare_scenario(legal)
        apply_channel(state, legal)
        request = state.runtime.make_request(legal.tool_name, legal.arguments,
            legal.executor_id, legal.capability_id, legal.callsite_id,
            state.context_ref, state.value_id)
        with self.assertRaises(PermissionError):
            state.endpoint._bypass_attempt_for_test(request)
        self.assertEqual(state.endpoint.effects, ())
        outcome = state.endpoint.invoke(request, legal.family)
        self.assertTrue(outcome.committed)
        with self.assertRaises(PermissionError):
            state.endpoint._replay_attempt_for_test(request)
        self.assertEqual(len(state.endpoint.effects), 1)

    def test_adapter_family_hint_cannot_change_policy(self):
        attack = golden_pairs()[1][0]
        state = prepare_scenario(attack)
        apply_channel(state, attack)
        request = state.runtime.make_request(attack.tool_name, attack.arguments,
            attack.executor_id, attack.capability_id, attack.callsite_id,
            state.context_ref, state.value_id)
        outcome = state.endpoint.invoke(request, "sibling")
        self.assertEqual(outcome.decision, Decision.DENY)
        self.assertFalse(outcome.committed)

    def test_security_metadata_in_business_arguments_is_rejected(self):
        legal = golden_pairs()[1][1]
        state = prepare_scenario(legal)
        apply_channel(state, legal)
        args = {**legal.arguments, "approval_valid": True}
        request = state.runtime.make_request(legal.tool_name, args,
            legal.executor_id, legal.capability_id, legal.callsite_id,
            state.context_ref, state.value_id)
        outcome = state.endpoint.invoke(request, legal.family)
        self.assertEqual(outcome.reason_code, "INVALID_BUSINESS_ARGUMENTS")
        self.assertFalse(outcome.committed)

    def test_no_framework_or_model_sdk_import(self):
        code = ("import context_launder_bench.runner, sys; "
                "banned=('langgraph','openai','anthropic','autogen'); "
                "assert not any(any(n == b or n.startswith(b + '.') for b in banned) "
                "for n in sys.modules)")
        subprocess.run([sys.executable, "-c", code], check=True)


if __name__ == "__main__":
    unittest.main()
