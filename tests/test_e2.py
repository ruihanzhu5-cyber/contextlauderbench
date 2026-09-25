import json
import tempfile
import unittest

from context_launder_bench.adapters.langgraph_adapter import LangGraphAdapter
from context_launder_bench.analysis import export_boundaries
from context_launder_bench.model import DiscontinuityKind
from context_launder_bench.scenarios import flatten_pairs, golden_pairs


class E2BoundaryTests(unittest.TestCase):
    def test_endpoint_records_selected_policy_enforcement(self):
        scenario = golden_pairs()[0][0]
        expected = {
            "D0": set(),
            "D1": {"tool_allowlist"},
            "D2": {"executor_capability"},
            "D3": {"tool_allowlist", "executor_capability"},
        }
        for policy_id, enforced in expected.items():
            result = LangGraphAdapter().run(scenario, policy_id)
            records = {r.field_or_relation: r.kind for r in result.discontinuities
                       if r.boundary == "endpoint"}
            actual = {field for field in enforced
                      if records[field] is DiscontinuityKind.PRESERVED_AND_ENFORCED}
            self.assertEqual(actual, enforced)
            self.assertIs(records["source"],
                          DiscontinuityKind.PRESENT_BUT_UNENFORCED)
            self.assertIs(records["approval_binding"],
                          DiscontinuityKind.PRESENT_BUT_UNENFORCED)

    def test_five_boundaries_and_trace_evidence(self):
        results = [LangGraphAdapter().run(s) for s in flatten_pairs(golden_pairs())]
        boundaries = {r.boundary for result in results for r in result.discontinuities}
        self.assertTrue({"message", "shared-state", "memory", "task-switch",
                         "endpoint"}.issubset(boundaries))
        kinds = set(DiscontinuityKind)
        endpoint_records = [r for result in results for r in result.discontinuities
                            if r.boundary == "endpoint"]
        self.assertTrue(endpoint_records)
        self.assertTrue(all(r.kind is DiscontinuityKind.PRESENT_BUT_UNENFORCED
                            for r in endpoint_records))
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
