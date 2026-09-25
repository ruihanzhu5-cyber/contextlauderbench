import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from context_launder_bench.benchmark import run_benchmark
from context_launder_bench.endpoint import UnifiedMockEndpoint
from context_launder_bench.generator import (
    TEMPLATES, split_generator, validate_dataset,
)
from context_launder_bench.policies import POLICY_IDS
from context_launder_bench.scenarios import CHANNELS, FAMILIES, validate_pair


class E3MiniTests(unittest.TestCase):
    def test_generator_and_split(self):
        self.assertEqual(len(TEMPLATES), 8)
        self.assertEqual({t.family for t in TEMPLATES}, set(FAMILIES))
        first = split_generator(seed=42)
        second = split_generator(seed=42)
        self.assertEqual(first, second)
        validate_dataset(first)
        self.assertEqual({k: len(v) for k, v in first.items()},
                         {"dev": 6, "validation": 6, "test": 12})
        self.assertTrue(all(a.variant == "held_out" for a, _ in first["test"]))
        self.assertEqual({a.channel for pairs in first.values()
                          for a, _ in pairs}, set(CHANNELS))
        for pairs in first.values():
            for attack, legal in pairs:
                validate_pair(attack, legal)

    def test_full_scripted_benchmark_uses_one_endpoint(self):
        original = UnifiedMockEndpoint.invoke
        calls = []
        def counted(endpoint, request):
            calls.append(request.tool_name)
            return original(endpoint, request)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(UnifiedMockEndpoint, "invoke", counted):
                results = run_benchmark(directory, seed=42)
            self.assertEqual(len(results), 384)
            self.assertEqual(len(calls), 384)
            summary = json.loads((Path(directory) / "summary.json").read_text())
            self.assertEqual(summary["unique_scenarios"], 48)
            self.assertEqual(summary["ground_truth_unauthorized"], 192)
            self.assertEqual(summary["ground_truth_authorized"], 192)
            self.assertEqual(summary["committed"], 384)
            self.assertEqual(summary["unsafe_commits"], 192)
            self.assertEqual(summary["total_runs"], 384)
            self.assertEqual(summary["tool_call_count"], 384)
            self.assertEqual(summary["no_attempt_count"], 0)
            self.assertEqual(summary["parse_error_count"], 0)
            self.assertEqual(summary["unsafe_commit_among_tool_attempts"], 0.5)
            self.assertEqual(set(summary["by_policy"]), set(POLICY_IDS))
            self.assertTrue(all(r.discontinuities for r in results))
            self.assertTrue(all(r.admission_policy in POLICY_IDS for r in results))
            self.assertTrue((Path(directory) / "boundary_matrix.md").exists())


if __name__ == "__main__":
    unittest.main()
