from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol
from urllib.request import Request, urlopen

from langchain_core.messages import BaseMessage

from ..backends import AgentInput, ToolAttempt, parse_tool_attempt
from ..model import canonical, digest


@dataclass(frozen=True)
class DeepSeekConfig:
    model: str
    tools: tuple[Mapping[str, Any], ...]
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: float = 30.0
    # Explicit experimental defaults. Thinking mode ignores temperature;
    # set temperature=None when enabling it.
    thinking: bool = False
    reasoning_effort: str = "none"
    temperature: float | None = 0.0
    top_p: float = 1.0
    max_tokens: int = 1024


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
        if config.thinking != (config.reasoning_effort != "none"):
            raise ValueError("thinking and reasoning_effort disagree")
        if config.reasoning_effort not in {"none", "low", "high", "max"}:
            raise ValueError("Unsupported reasoning_effort")
        if config.thinking and config.temperature is not None:
            raise ValueError("temperature has no effect in thinking mode; use None")
        if config.temperature is not None and not 0 <= config.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if not 0 < config.top_p <= 1 or config.max_tokens < 1:
            raise ValueError("Invalid top_p or max_tokens")
        self.config = config
        self.client = client or DeepSeekHTTPClient()

    def experiment_metadata(self) -> Mapping[str, Any]:
        return {
            "provider": "DeepSeek",
            "model": self.config.model,
            "model_config": {
                "thinking": self.config.thinking,
                "reasoning_effort": self.config.reasoning_effort,
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "max_tokens": self.config.max_tokens,
                "tool_choice": "auto",
                "tool_schema_digest": digest(self.config.tools),
                "base_url": self.config.base_url,
                "timeout_seconds": self.config.timeout_seconds,
            },
        }

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
            "thinking": {"type": "enabled" if self.config.thinking else "disabled"},
            "reasoning_effort": self.config.reasoning_effort,
            "top_p": self.config.top_p,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.temperature is not None:
            payload["temperature"] = self.config.temperature
        prompt_digest = digest(payload["messages"])
        response_id = None
        finish_reason = None

        def recorded(attempt: ToolAttempt) -> ToolAttempt:
            return replace(attempt, provider_response_id=response_id,
                           finish_reason=finish_reason,
                           prompt_digest=prompt_digest)

        try:
            response = self.client.complete(payload, self.config)
        except Exception as exc:
            # One failed provider request is one recorded run; no implicit retry.
            return recorded(ToolAttempt("provider_error",
                                        error=type(exc).__name__))
        if isinstance(response, Mapping):
            response_id = response.get("id") if isinstance(
                response.get("id"), str) else None
            choices_for_metadata = response.get("choices")
            if isinstance(choices_for_metadata, list) and choices_for_metadata:
                first = choices_for_metadata[0]
                if isinstance(first, Mapping) and isinstance(
                    first.get("finish_reason"), str
                ):
                    finish_reason = first["finish_reason"]
        if isinstance(response, Mapping) and response.get("error") is not None:
            return recorded(ToolAttempt("provider_error",
                                        error="provider_response_error"))
        if finish_reason in {"insufficient_system_resource", "aborted"}:
            return recorded(ToolAttempt("provider_error",
                                        error=finish_reason))
        if not isinstance(response, Mapping):
            return recorded(ToolAttempt("parse_error", error="response_schema"))
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            return recorded(ToolAttempt("parse_error", error="response_schema"))
        message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
        if not isinstance(message, Mapping):
            return recorded(ToolAttempt("parse_error", error="response_schema"))
        calls = message.get("tool_calls")
        if calls is None or calls == []:
            return recorded(ToolAttempt("no_attempt"))
        if not isinstance(calls, list) or len(calls) != 1:
            return recorded(ToolAttempt("parse_error", error="multiple_tool_calls"))
        call = calls[0]
        if not isinstance(call, Mapping) or call.get("type") != "function":
            return recorded(ToolAttempt("parse_error", error="invalid_tool_call"))
        function = call.get("function")
        if not isinstance(function, Mapping):
            return recorded(ToolAttempt("parse_error", error="invalid_tool_call"))
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            return recorded(ToolAttempt("parse_error", error="invalid_tool_call"))
        try:
            decoded_arguments = json.loads(arguments)
        except (TypeError, ValueError):
            return recorded(ToolAttempt("parse_error", error="invalid_json"))
        return recorded(parse_tool_attempt({
            "tool_name": name,
            "arguments": decoded_arguments,
        }))
