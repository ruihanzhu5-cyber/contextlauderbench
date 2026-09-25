"""Compatibility imports for the active D0–D3 admission policies.

The old report-only evaluate_baselines function was removed. Policies now decide
admission inside UnifiedMockEndpoint.
"""

from .policies import (
    AllowAllPolicy, ToolAllowlistPolicy, ExecutorCapabilityPolicy,
    CombinedPolicy, policy_from_id,
)
