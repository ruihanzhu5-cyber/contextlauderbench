import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace

from context_launder_bench.adapters.langgraph_adapter import LangGraphAdapter
from context_launder_bench.backends import AgentInput, ModelBackend, ScriptedBackend
from context_launder_bench.benchmark import run_model_cases
from context_launder_bench.model import digest
from context_launder_bench.llm.deepseek import DeepSeekBackend, DeepSeekConfig
from context_launder_bench.scenarios import golden_pairs


TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "delete_file",
        "description": "Delete a file by ID",
        "parameters": {
            "type": "object",
            "properties": {"file_id": {"type": "integer"}},
            "required": ["file_id"],
        },
    },
}


class FakeChatClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, payload, config):
        self.calls.append((payload, config))
        return self.response


def response_with_calls(calls):
    return {"id": "response-1", "choices": [
        {"finish_reason": "tool_calls" if calls else "stop",
         "message": {"tool_calls": calls}}]}


def tool_call(arguments):
    return [{
        "id": "call-1", "type": "function",
        "function": {"name": "delete_file", "arguments": arguments},
    }]


class EchoModel:
    def generate_tool_call(self, task, native_input):
        return {"tool_name": "delete_file", "arguments": {"file_id": native_input["id"]}}


class LLMAdapterTests(unittest.TestCase):
    def test_scripted_and_generic_model_share_agent_input_signature(self):
        scenario = golden_pairs()[0][1]
        agent_input = AgentInput("delete file", {"id": 21})
        scripted = ScriptedBackend(scenario).run(agent_input)
        modeled = ModelBackend(EchoModel()).run(agent_input)
        self.assertEqual(scripted.arguments, {"file_id": 13})
        self.assertEqual(modeled.arguments, {"file_id": 21})

    def test_deepseek_fake_client_receives_native_input_and_tool_schema(self):
        scenario = replace(golden_pairs()[0][1],
                           task_text="Delete the requested file")
        client = FakeChatClient(response_with_calls(
            tool_call('{"file_id":13}')))
        backend = DeepSeekBackend(
            DeepSeekConfig(model="deepseek-flash", tools=(TOOL_SCHEMA,)),
            client,
        )
        result = LangGraphAdapter().run(
            scenario, backend=backend,
            upstream_output={"target_file_id": 13},
        )
        self.assertEqual(result.tool_name, "delete_file")
        self.assertEqual(result.tool_arguments, {"file_id": 13})
        self.assertTrue(result.committed)
        payload, config = client.calls[0]
        self.assertEqual(payload["model"], config.model)
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(payload["tools"][0]["function"]["name"], "delete_file")
        self.assertIn("Delete the requested file", payload["messages"][0]["content"])
        self.assertIn("target_file_id", payload["messages"][0]["content"])
        self.assertIn("\"type\":\"human\"", payload["messages"][0]["content"])
        self.assertNotIn("authorized_action_spec", payload["messages"][0]["content"])

    def test_explicit_deepseek_experiment_parameters_reach_client(self):
        agent_input = AgentInput("Delete file", {"target_file_id": 13})
        for config, expected_thinking in (
            (DeepSeekConfig(model="selected-by-caller", tools=(TOOL_SCHEMA,),
                            thinking=False, reasoning_effort="none",
                            temperature=0.2, top_p=1.0, max_tokens=512),
             "disabled"),
            (DeepSeekConfig(model="selected-by-caller", tools=(TOOL_SCHEMA,),
                            thinking=True, reasoning_effort="low",
                            temperature=None, top_p=0.98, max_tokens=2048),
             "enabled"),
        ):
            with self.subTest(thinking=expected_thinking):
                client = FakeChatClient(response_with_calls([]))
                DeepSeekBackend(config, client).run(agent_input)
                payload = client.calls[0][0]
                self.assertEqual(payload["model"], "selected-by-caller")
                self.assertEqual(payload["thinking"], {"type": expected_thinking})
                self.assertEqual(payload["reasoning_effort"],
                                 config.reasoning_effort)
                self.assertEqual(payload["top_p"], config.top_p)
                self.assertEqual(payload["max_tokens"], config.max_tokens)
                self.assertEqual(payload.get("temperature"), config.temperature)

        with self.assertRaises(ValueError):
            DeepSeekBackend(DeepSeekConfig(
                model="selected-by-caller", tools=(TOOL_SCHEMA,),
                thinking=True, reasoning_effort="high", temperature=0.0,
            ))

    def test_model_report_records_reproducible_metadata_without_prompt(self):
        scenario = replace(golden_pairs()[0][1],
                           task_text="Delete the requested file")
        upstream = {"target_file_id": 13}
        client = FakeChatClient(response_with_calls(tool_call('{"file_id":13}')))
        backend = DeepSeekBackend(DeepSeekConfig(
            model="selected-by-caller", tools=(TOOL_SCHEMA,),
            temperature=0.2, max_tokens=512,
        ), client)
        with tempfile.TemporaryDirectory() as directory:
            results = run_model_cases([(scenario, upstream)], backend, directory)
            row = json.loads((Path(directory) / "results.json").read_text())[0]
        metadata = row["experiment_metadata"]
        self.assertEqual(metadata["provider"], "DeepSeek")
        self.assertEqual(metadata["model"], "selected-by-caller")
        self.assertEqual(metadata["model_config"]["temperature"], 0.2)
        self.assertEqual(metadata["model_config"]["max_tokens"], 512)
        self.assertEqual(metadata["model_config"]["timeout_seconds"], 30.0)
        self.assertEqual(metadata["model_config"]["base_url"],
                         "https://api.deepseek.com")
        self.assertEqual(metadata["framework"], "LangGraph")
        self.assertEqual(metadata["scenario_id"], scenario.scenario_id)
        self.assertEqual(metadata["upstream_input_digest"], digest(upstream))
        self.assertEqual(metadata["task_digest"], digest(scenario.task_text))
        self.assertEqual(metadata["provider_response_id"], "response-1")
        self.assertEqual(metadata["finish_reason"], "tool_calls")
        self.assertEqual(metadata["prompt_digest"],
                         digest(client.calls[0][0]["messages"]))
        self.assertNotIn(scenario.task_text, json.dumps(metadata))
        self.assertTrue(results[0].committed)

    def test_provider_error_is_reported_and_batch_continues(self):
        class SequenceClient:
            def __init__(self):
                self.responses = iter((
                    TimeoutError("temporary outage"),
                    {"error": {"code": "unavailable"}},
                    response_with_calls([]),
                    response_with_calls(tool_call("{bad json")),
                    response_with_calls(tool_call('{"file_id":13}')),
                ))

            def complete(self, payload, config):
                response = next(self.responses)
                if isinstance(response, Exception):
                    raise response
                return response

        scenario = replace(golden_pairs()[0][1],
                           task_text="Delete the requested file")
        backend = DeepSeekBackend(DeepSeekConfig(
            model="selected-by-caller", tools=(TOOL_SCHEMA,),
        ), SequenceClient())
        with tempfile.TemporaryDirectory() as directory:
            results = run_model_cases(
                [(scenario, {"target_file_id": 13})] * 5,
                backend, directory,
            )
            summary = json.loads((Path(directory) / "summary.json").read_text())
        self.assertEqual([r.attempt_status for r in results], [
            "provider_error", "provider_error", "no_attempt",
            "parse_error", "tool_call",
        ])
        self.assertEqual(summary["total_runs"], 5)
        self.assertEqual(summary["provider_error_count"], 2)
        self.assertEqual(summary["provider_error_rate"], 0.4)
        self.assertEqual(summary["no_attempt_count"], 1)
        self.assertEqual(summary["parse_error_count"], 1)
        self.assertEqual(summary["tool_call_count"], 1)
        self.assertEqual(summary["committed_count"], 1)
        for result in results[:2]:
            self.assertIsNone(result.admission_decision)
            self.assertIsNone(result.ground_truth_authorized)
            self.assertFalse(result.committed)
            self.assertFalse(any(event.kind == "ToolPrepare"
                                 for event in result.events))

    def test_deepseek_statuses_are_not_filled_from_fixture(self):
        scenario = replace(golden_pairs()[0][1], task_text="Delete a file")
        responses = (
            (response_with_calls([]), "no_attempt"),
            (response_with_calls(tool_call("{bad json")), "parse_error"),
            (response_with_calls(tool_call('{"file_id":13}') * 2), "parse_error"),
        )
        for response, expected in responses:
            with self.subTest(expected=expected):
                client = FakeChatClient(response)
                backend = DeepSeekBackend(
                    DeepSeekConfig(model="deepseek-flash", tools=(TOOL_SCHEMA,)),
                    client,
                )
                result = LangGraphAdapter().run(
                    scenario, backend=backend,
                    upstream_output={"target_file_id": 13},
                )
                self.assertEqual(result.attempt_status, expected)
                self.assertFalse(result.committed)
                self.assertIsNone(result.admission_decision)
                self.assertIsNone(result.tool_arguments)
                self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
