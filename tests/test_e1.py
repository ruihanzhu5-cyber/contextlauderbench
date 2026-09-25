import unittest

from context_launder_bench.adapters.langgraph_adapter import LangGraphAdapter
from context_launder_bench.model import Decision
from context_launder_bench.scenarios import golden_pairs, validate_pair


class E1IntegrationTests(unittest.TestCase):
    def test_four_pairs_through_native_graph(self):
        adapter = LangGraphAdapter()
        for attack, legal in golden_pairs():
            with self.subTest(family=attack.family):
                validate_pair(attack, legal)
                a, l = adapter.run(attack), adapter.run(legal)
                self.assertEqual(a.decision, Decision.DENY)
                self.assertEqual(l.decision, Decision.ALLOW)
                self.assertFalse(a.committed)
                self.assertTrue(l.committed)
                self.assertEqual(a.terminal_signature, l.terminal_signature)
                for result in (a, l):
                    self.assertIn("checkpoint", result.native_mapping)
                    kinds = [e.kind for e in result.events]
                    self.assertIn("ToolPrepare", kinds)
                    self.assertIn("PolicyDecision", kinds)
                    self.assertIn("ToolCommit" if result.committed else "ToolReject", kinds)

    def test_native_message_memory_join_mapping(self):
        adapter = LangGraphAdapter()
        pairs = golden_pairs()
        message = adapter.run(pairs[0][1])
        self.assertTrue(any(key.startswith("message-") for key in message.native_mapping))
        memory = adapter.run(pairs[2][1])
        self.assertIn("shared-state", memory.native_mapping)
        join = adapter.run(pairs[3][1])
        self.assertIn("join-state", join.native_mapping)

    def test_four_sanity_baselines_reported(self):
        import json
        import tempfile
        from pathlib import Path
        from context_launder_bench.benchmark import run_golden
        with tempfile.TemporaryDirectory() as directory:
            run_golden(directory, adapters=("langgraph",))
            rows = json.loads((Path(directory) / "baselines.json").read_text())
            self.assertEqual(len(rows), 8)
            for row in rows:
                self.assertEqual(set(row["admission"]), {
                    "D0_framework_default", "D1_tool_allowlist",
                    "D2_executor_capability", "D3_combined"})
                self.assertTrue(all(row["admission"].values()))


if __name__ == "__main__":
    unittest.main()
