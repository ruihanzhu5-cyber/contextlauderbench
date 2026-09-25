import json
import tempfile
import unittest

from context_launder_bench.adapters.langgraph_adapter import LangGraphAdapter
from context_launder_bench.analysis import export_boundaries
from context_launder_bench.model import DiscontinuityKind
from context_launder_bench.scenarios import flatten_pairs, golden_pairs


class E2BoundaryTests(unittest.TestCase):
    def test_five_boundaries_and_trace_evidence(self):
        results = [LangGraphAdapter().run(s) for s in flatten_pairs(golden_pairs())]
        boundaries = {r.boundary for result in results for r in result.discontinuities}
        self.assertTrue({"message", "shared-state", "memory", "task-switch",
                         "endpoint"}.issubset(boundaries))
        kinds = set(DiscontinuityKind)
        for result in results:
            event_ids = {e.event_id for e in result.events}
            for record in result.discontinuities:
                self.assertIn(record.kind, kinds)
                self.assertIn(record.first_event_id, event_ids)
                self.assertTrue(set(record.evidence_refs).issubset(event_ids))
        with tempfile.TemporaryDirectory() as directory:
            paths = export_boundaries(results, directory)
            self.assertTrue(all(p.exists() for p in paths))
            rows = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertEqual(len(rows), sum(len(r.discontinuities) for r in results))
            self.assertIn("Trace evidence", paths[2].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
