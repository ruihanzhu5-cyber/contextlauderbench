from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.request import Request, urlopen

from langchain_core.messages import BaseMessage

from ..backends import AgentInput, ToolAttempt, parse_tool_attempt
from ..model import canonical


@dataclass(frozen=True)
class DeepSeekConfig:
    model: str
    tools: tuple[Mapping[str, Any], ...]
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: float = 30.0


class ChatCompletionClient(Protocol):
    def complete(self, payload: Mapping[str, Any],
                 config: DeepSeekConfig) -> Mapping[str, Any]: ...


class DeepSeekHTTPClient:
    """Small standard-library transport; no request is made until run()."""

    def complete(self, payload: Mapping[str, Any],
                 config: DeepSeekConfig) -> Mapping[str, Any]:
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing {config.api_key_env}")
        url = config.base_url.rstrip("/") + "/chat/completions"
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=config.timeout_seconds) as response:
            return json.load(response)


def _native_json(value: Any) -> Any:
    if isinstance(value, BaseMessage):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _native_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported framework-native input: {type(value).__name__}")


class DeepSeekBackend:
    """DeepSeek tool-call adapter; it has no admission or ground-truth logic."""

    def __init__(self, config: DeepSeekConfig,
                 client: ChatCompletionClient | None = None):
        if not config.model or not config.tools:
            raise ValueError("DeepSeek model and tool schemas are required")
        self.config = config
        self.client = client or DeepSeekHTTPClient()

    def run(self, agent_input: AgentInput) -> ToolAttempt:
        native = _native_json(agent_input.native_input)
        payload = {
            "model": self.config.model,
            "messages": [{
                "role": "user",
                "content": (
                    f"Task:\n{agent_input.task_text}\n\n"
                    f"Framework input:\n{canonical(native)}"
                ),
            }],
            "tools": [dict(tool) for tool in self.config.tools],
            "tool_choice": "auto",
            "stream": False,
        }
        response = self.client.complete(payload, self.config)
        if not isinstance(response, Mapping):
            return ToolAttempt("parse_error", error="response_schema")
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            return ToolAttempt("parse_error", error="response_schema")
        message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
        if not isinstance(message, Mapping):
            return ToolAttempt("parse_error", error="response_schema")
        calls = message.get("tool_calls")
        if calls is None or calls == []:
            return ToolAttempt("no_attempt")
        if not isinstance(calls, list) or len(calls) != 1:
            return ToolAttempt("parse_error", error="multiple_tool_calls")
        call = calls[0]
        if not isinstance(call, Mapping) or call.get("type") != "function":
            return ToolAttempt("parse_error", error="invalid_tool_call")
        function = call.get("function")
        if not isinstance(function, Mapping):
            return ToolAttempt("parse_error", error="invalid_tool_call")
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            return ToolAttempt("parse_error", error="invalid_tool_call")
        try:
            decoded_arguments = json.loads(arguments)
        except (TypeError, ValueError):
            return ToolAttempt("parse_error", error="invalid_json")
        return parse_tool_attempt({
            "tool_name": name,
            "arguments": decoded_arguments,
        })
