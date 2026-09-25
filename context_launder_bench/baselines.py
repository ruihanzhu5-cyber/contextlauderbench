from __future__ import annotations

from .model import ToolRequest
from .runtime import TrustedRuntime


def evaluate_baselines(runtime: TrustedRuntime, request: ToolRequest) -> dict[str, bool]:
    """Admission gates only; the oracle remains mandatory for every commit."""
    context = runtime.context(request.runtime_context_ref)
    allowlist = bool(context and request.tool_name in context.allowed_sinks)
    capability = runtime.capability_valid(request)
    return {
        "D0_framework_default": True,
        "D1_tool_allowlist": allowlist,
        "D2_executor_capability": capability,
        "D3_combined": allowlist and capability,
    }
