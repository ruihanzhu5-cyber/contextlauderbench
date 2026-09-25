import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from context_launder_bench.adapters.langgraph_adapter import LangGraphAdapter
from context_launder_bench.benchmark import run_golden
from context_launder_bench.model import Decision
from context_launder_bench.oracle import GroundTruthOracle
from context_launder_bench.policies import POLICY_IDS
from context_launder_bench.runner import prepare_scenario
from context_launder_bench.scenarios import golden_pairs, validate_pair


class E1IntegrationTests(unittest.TestCase):
    def test_four_pairs_under_each_active_policy(self):
        adapter = LangGraphAdapter()
        for attack, legal in golden_pairs():
            validate_pair(attack, legal)
            for policy_id in POLICY_IDS:
                with self.subTest(family=attack.family, policy=policy_id):
                    a, l = adapter.run(attack, policy_id), adapter.run(legal, policy_id)
                    self.assertEqual(a.admission_policy, policy_id)
                    self.assertEqual(l.admission_policy, policy_id)
                    self.assertFalse(a.ground_truth_authorized)
                    self.assertTrue(l.ground_truth_authorized)
                    self.assertEqual(a.admission_decision, Decision.ALLOW)
                    self.assertEqual(l.admission_decision, Decision.ALLOW)
                    self.assertTrue(a.committed)
                    self.assertTrue(l.committed)
                    self.assertTrue(a.unsafe_commit)
                    self.assertFalse(l.unsafe_commit)
                    self.assertEqual(a.terminal_signature, l.terminal_signature)
                    for result in (a, l):
                        self.assertIn("checkpoint", result.native_mapping)
                        kinds = [e.kind for e in result.events]
                        self.assertIn("ToolPrepare", kinds)
                        self.assertIn("PolicyDecision", kinds)
                        self.assertIn("ToolCommit", kinds)
                        self.assertLess(kinds.index("ToolCommit"),
                                        kinds.index("OutcomeEvaluated"))
                        outcome_event = next(e for e in result.events
                                             if e.kind == "OutcomeEvaluated")
                        self.assertEqual(dict(outcome_event.data)["unsafe_commit"],
                                         result.unsafe_commit)

    def test_native_message_memory_join_mapping(self):
        adapter = LangGraphAdapter()
        pairs = golden_pairs()
        self.assertTrue(any(key.startswith("message-") for key in
                            adapter.run(pairs[0][1]).native_mapping))
        self.assertIn("shared-state", adapter.run(pairs[2][1]).native_mapping)
        self.assertIn("join-state", adapter.run(pairs[3][1]).native_mapping)

    def test_fork_join_values_are_created_by_graph_branches(self):
        attack, legal = golden_pairs()[3]
        for channel in ("DIRECT_OR_MESSAGE", "SHARED_STATE_OR_MEMORY",
                        "SPLIT_TRANSFORM_JOIN"):
            with self.subTest(channel=channel):
                a = LangGraphAdapter().run(replace(attack, channel=channel))
                l = LangGraphAdapter().run(replace(legal, channel=channel))
                self.assertEqual(a.terminal_signature, l.terminal_signature)
                self.assertFalse(a.ground_truth_authorized)
                self.assertTrue(l.ground_truth_authorized)
                self.assertTrue(a.committed)
                self.assertTrue(l.committed)
                mapping = l.native_mapping
                self.assertEqual(
                    {"branch-A", "branch-B", "join-state"} & set(mapping),
                    {"branch-A", "branch-B", "join-state"},
                )
                events = [event.as_dict() for event in l.events]
                derives = [event for event in events if event["kind"] == "Derive"]
                by_transform = {
                    event["data"]["transform_id"]: event["data"]
                    for event in derives
                }
                self.assertEqual(
                    by_transform["langgraph-branch-A"]["input_ids"],
                    by_transform["langgraph-branch-B"]["input_ids"],
                )
                join = next(event for event in events if event["kind"] == "Join")
                self.assertEqual(
                    tuple(join["data"]["input_ids"]),
                    (mapping["branch-A"], mapping["branch-B"]),
                )
                self.assertEqual(join["data"]["output_id"],
                                 mapping["join-state"])

    def test_policy_gates_are_live_and_independent_of_ground_truth(self):
        legal = golden_pairs()[1][1]
        for policy_id in POLICY_IDS:
            state = prepare_scenario(legal, policy_id)
            request = state.runtime.make_request(
                legal.tool_name, legal.arguments, legal.executor_id,
                "unknown-capability", legal.callsite_id,
                state.context_ref, state.value_id,
            )
            self.assertFalse(GroundTruthOracle().authorized(state.runtime, request))
            outcome = state.endpoint.invoke(request)
            expected = Decision.ALLOW if policy_id in ("D0", "D1") else Decision.DENY
            self.assertEqual(outcome.admission_decision, expected)
            self.assertEqual(outcome.committed, expected is Decision.ALLOW)
        for policy_id in ("D1", "D3"):
            state = prepare_scenario(legal, policy_id)
            request = state.runtime.make_request(
                "read_secret", {"secret_id": "s1"}, legal.executor_id,
                legal.capability_id, legal.callsite_id,
                state.context_ref, state.value_id,
            )
            self.assertEqual(state.endpoint.invoke(request).admission_decision,
                             Decision.DENY)

    def test_endpoint_never_calls_oracle_for_d0_d3(self):
        from unittest.mock import patch
        legal = golden_pairs()[1][1]
        for policy_id in POLICY_IDS:
            state = prepare_scenario(legal, policy_id)
            request = state.runtime.make_request(
                legal.tool_name, legal.arguments, legal.executor_id,
                legal.capability_id, legal.callsite_id,
                state.context_ref, state.value_id,
            )
            with patch.object(GroundTruthOracle, "authorized",
                              side_effect=AssertionError("oracle used as admission gate")):
                outcome = state.endpoint.invoke(request)
            self.assertTrue(outcome.committed)

    def test_e1_trace_export_contains_required_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            results = run_golden(directory, adapters=("langgraph",))
            self.assertEqual(len(results), 32)
            rows = json.loads((Path(directory) / "baselines.json").read_text())
            self.assertEqual(len(rows), 32)
            expected = {"ground_truth_authorized", "admission_policy",
                        "admission_decision", "committed", "unsafe_commit"}
            self.assertTrue(all(expected.issubset(row) for row in rows))
            self.assertEqual({row["admission_policy"] for row in rows},
                             set(POLICY_IDS))
            self.assertEqual(sum(row["unsafe_commit"] for row in rows), 16)
            self.assertTrue((Path(directory) / "admission_traces.csv").exists())

    def test_e0_policy_cannot_enter_langgraph(self):
        with self.assertRaises(ValueError):
            LangGraphAdapter().run(golden_pairs()[0][0],
                                   "E0_GROUND_TRUTH_ENFORCING")


if __name__ == "__main__":
    unittest.main()
