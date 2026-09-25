import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from context_launder_bench.backends import ToolAttempt
from context_launder_bench.llm.deepseek import DeepSeekBackend, DeepSeekConfig, DeepSeekHTTPClient
from context_launder_bench.workflow2a import default_cases, run_case, run_suite


class RecordingBackend:
    def __init__(self, attempts, mutate=False):
        self.attempts = iter(attempts)
        self.inputs = []
        self.mutate = mutate

    def experiment_metadata(self):
        return {"provider": "fake", "model": "recording", "model_config": {}}

    def run(self, agent_input):
        self.inputs.append(agent_input.native_input)
        if self.mutate:
            agent_input.native_input["joined"]["invoice"]["account"] = "Y"
            agent_input.native_input["joined"]["approval_ref"] = "ap-Y"
        result = next(self.attempts)
        if isinstance(result, Exception):
            raise result
        return result


def payment(account="X", amount=100):
    return ToolAttempt("tool_call", "make_payment", {"account": account, "amount": amount})


class WorkflowBackendTests(unittest.TestCase):
    def setUp(self):
        self.cases = {c.case_id: c for c in default_cases()}
        # Any accidental live provider use is a test failure.
        self.network = patch.object(DeepSeekHTTPClient, "complete",
                                    side_effect=AssertionError("live API forbidden"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_dropped_context_cannot_leak_through_audit_state(self):
        backend = RecordingBackend([ToolAttempt("no_attempt")])
        result = run_case(self.cases["fault-drop"], backend)
        visible = backend.inputs[0]
        self.assertEqual(set(visible), {"joined"})
        self.assertEqual(set(visible["joined"]),
                         {"invoice", "approval_ref", "approval_record"})
        self.assertIsNone(visible["joined"]["approval_ref"])
        self.assertIsNone(visible["joined"]["approval_record"])
        self.assertEqual(result["native_boundary_input"]["approval_ref"], "ap-X")
        self.assertIsNone(result["executor_rule"])

    def test_backend_mutation_cannot_change_joined_or_trusted_state(self):
        result = run_case(self.cases["terminal-legal-X"],
                          RecordingBackend([payment()], mutate=True))
        self.assertEqual(result["native_boundary_output"]["invoice"]["account"], "X")
        self.assertEqual(result["proposal"]["approval_ref"], "ap-X")
        self.assertTrue(result["ground_truth_authorized"])
        self.assertEqual(result["business_state_after"]["X"], 100)

    def test_error_categories_and_metadata_survive_batch(self):
        attempts = [
            ToolAttempt("provider_error", error="TimeoutError", provider_response_id="r1",
                        finish_reason="aborted", prompt_digest="p1"),
            ToolAttempt("parse_error", error="invalid_json"),
            ToolAttempt("no_attempt"), payment(),
        ]
        backend = RecordingBackend(attempts)
        cases = tuple(replace(self.cases["terminal-legal-X"], case_id=f"case-{i}")
                      for i in range(4))
        with tempfile.TemporaryDirectory() as directory:
            results = run_suite(directory, cases, backend)
            summary = json.loads((Path(directory) / "workflow2a_summary.json").read_text())
        self.assertEqual(summary["attempt_counts"],
                         {s: 1 for s in ("tool_call", "no_attempt", "parse_error", "provider_error")})
        for result, kind in zip(results[:3], ("ProviderError", "ParseError", "NoAttempt")):
            kinds = [e["kind"] for e in result["events"]]
            self.assertIn(kind, kinds)
            self.assertNotIn("ToolPrepare", kinds)
            self.assertIsNone(result["ground_truth_authorized"])
            self.assertFalse(result["committed"])
        first = results[0]
        self.assertEqual(first["proposal"]["error"], "TimeoutError")
        self.assertEqual(first["experiment_metadata"]["provider_response_id"], "r1")
        self.assertEqual(first["experiment_metadata"]["prompt_digest"], "p1")
        self.assertTrue(results[-1]["committed"])
        self.assertIsNone(summary["external_llm_calls"])

    def test_backend_exception_does_not_leak_message_or_retry(self):
        backend = RecordingBackend([RuntimeError("secret-string"), payment()])
        result = run_case(self.cases["terminal-legal-X"], backend)
        self.assertEqual(len(backend.inputs), 1)
        self.assertEqual(result["proposal"]["status"], "provider_error")
        self.assertEqual(result["proposal"]["error"], "RuntimeError")
        self.assertNotIn("secret-string", json.dumps(result))

    def test_invalid_effects_are_not_admission_denials_and_batch_continues(self):
        attempts = [payment("Z"), payment(amount=2000), payment(account=[]),
                    ToolAttempt("tool_call", "delete_file", {"file_id": 13}),
                    payment()]
        cases = tuple(replace(self.cases["terminal-legal-X"], case_id=f"case-{i}")
                      for i in range(len(attempts)))
        with tempfile.TemporaryDirectory() as directory:
            results = run_suite(directory, cases, RecordingBackend(attempts))
        for result in results[:-1]:
            self.assertEqual(result["admission_decision"], "ALLOW")
            self.assertEqual(result["execution_status"], "execution_error")
            self.assertFalse(result["ground_truth_authorized"])
            self.assertFalse(result["committed"])
            self.assertFalse(result["unsafe_commit"])
            self.assertEqual(result["business_state_before"], result["business_state_after"])
            kinds = [e["kind"] for e in result["events"]]
            self.assertIn("ToolExecutionFailed", kinds)
            self.assertNotIn("ToolCommit", kinds)
            self.assertNotIn("ToolReject", kinds)
        self.assertTrue(results[-1]["committed"])

    def test_injected_backend_requires_explicit_cases(self):
        backend = RecordingBackend([])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                run_suite(directory, backend=backend)
        self.assertEqual(backend.inputs, [])

    def test_real_deepseek_adapter_with_fake_client_reaches_payment_sink(self):
        class Client:
            def __init__(self):
                self.payloads = []
            def complete(self, payload, config):
                self.payloads.append(payload)
                return {"id": "fake-response", "choices": [{"finish_reason": "tool_calls",
                    "message": {"tool_calls": [{"type": "function", "function": {
                        "name": "make_payment", "arguments": '{"account":"Y","amount":250}'
                    }}]}}]}
        client = Client()
        tool = {"type": "function", "function": {"name": "make_payment",
                "parameters": {"type": "object", "properties": {
                    "account": {"type": "string"}, "amount": {"type": "integer"}},
                    "required": ["account", "amount"], "additionalProperties": False}}}
        backend = DeepSeekBackend(DeepSeekConfig(model="fake-model", tools=(tool,)), client)
        result = run_case(self.cases["vendor-Y"], backend)
        self.assertEqual(result["proposal"]["arguments"], {"account": "Y", "amount": 250})
        self.assertEqual(result["business_state_after"]["Y"], 250)
        self.assertTrue(result["ground_truth_authorized"])
        metadata = result["experiment_metadata"]
        self.assertEqual(metadata["provider_response_id"], "fake-response")
        self.assertEqual(metadata["model"], "fake-model")
        self.assertTrue(metadata["prompt_digest"])
        prompt = client.payloads[0]["messages"][0]["content"]
        self.assertNotIn("native_before", prompt)
        self.assertNotIn("fixture_expected_authorized", prompt)
        self.assertEqual(len(client.payloads), 1)

    def test_model_choice_not_replaced_by_fixture_and_deny_preserves_state(self):
        result = run_case(self.cases["terminal-legal-X"], RecordingBackend([payment("Y", 250)]))
        self.assertEqual(result["proposal"]["arguments"], {"account": "Y", "amount": 250})
        self.assertFalse(result["ground_truth_authorized"])
        self.assertTrue(result["unsafe_commit"])
        denied = run_case(self.cases["capability-denied"], RecordingBackend([payment()]))
        self.assertEqual(denied["admission_decision"], "DENY")
        self.assertEqual(denied["business_state_before"], denied["business_state_after"])


if __name__ == "__main__":
    unittest.main()
