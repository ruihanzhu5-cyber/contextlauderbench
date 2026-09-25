import json
import unittest
from dataclasses import replace

from context_launder_bench.adapters.langgraph_adapter import LangGraphAdapter
from context_launder_bench.backends import AgentInput, ModelBackend, ScriptedBackend
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
    return {"choices": [{"message": {"tool_calls": calls}}]}


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
