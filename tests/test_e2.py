import json
import tempfile
import unittest

from context_launder_bench.adapters.langgraph_adapter import LangGraphAdapter
from context_launder_bench.analysis import classify_result, export_boundaries
from context_launder_bench.model import DiscontinuityKind, RunResult
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
                          DiscontinuityKind.UNOBSERVED)
            self.assertIs(records["approval_binding"],
                          DiscontinuityKind.UNOBSERVED)
            self.assertIs(records["action_spec"],
                          DiscontinuityKind.PRESENT_BUT_UNENFORCED)

    def test_drop_and_unwitnessed_transform_need_value_evidence(self):
        from context_launder_bench.runtime import TrustedRuntime
        runtime = TrustedRuntime("e2-value", "sibling")
        context = runtime.begin_task("user-A", "T2", "main",
                                     "execute-request", 1, ["delete_file"])
        before = runtime.seed_value("original", "trusted_user", context)
        unrelated = runtime.seed_value("changed", "trusted_user", context)
        witnessed = runtime.derive((before.value_id,), "changed",
                                   "documented-transform", context)
        runtime.observe_boundary("synthetic", before.value_id, None,
                                 represented_fields=("source",))
        runtime.observe_boundary("synthetic", before.value_id,
                                 unrelated.value_id,
                                 represented_fields=("source",))
        runtime.observe_boundary("synthetic", before.value_id,
                                 witnessed.value_id,
                                 represented_fields=("source",))
        result = RunResult(
            "e2-value", "test", "D0", None, False, "NO_ATTEMPT", None,
            runtime.events, runtime.canonical_log_digest(),
            native_mapping={"unrelated": unrelated.value_id},
            attempt_status="no_attempt",
        )
        records = classify_result(result)
        lineages = [r.kind for r in records if r.field_or_relation == "business_value"]
        self.assertEqual(lineages, [
            DiscontinuityKind.DROPPED,
            DiscontinuityKind.TRANSFORMED_WITHOUT_WITNESS,
            DiscontinuityKind.PRESERVED,
        ])
        self.assertTrue(all(
            r.kind is DiscontinuityKind.UNOBSERVED
            for r in records if r.boundary == "synthetic"
            and r.field_or_relation == "source"
        ))

    def test_five_boundaries_and_trace_evidence(self):
        results = [LangGraphAdapter().run(s) for s in flatten_pairs(golden_pairs())]
        boundaries = {r.boundary for result in results for r in result.discontinuities}
        self.assertTrue({"message", "shared-state", "memory", "task-switch",
                         "endpoint"}.issubset(boundaries))
        kinds = set(DiscontinuityKind)
        endpoint_records = [r for result in results for r in result.discontinuities
                            if r.boundary == "endpoint"]
        self.assertTrue(endpoint_records)
        self.assertTrue(any(r.kind is DiscontinuityKind.UNOBSERVED
                            for r in endpoint_records))
        self.assertTrue(all(r.affects_authorization is None
                            for result in results
                            for r in result.discontinuities))
        self.assertTrue(all(r.authorization_relevant
                            for r in endpoint_records
                            if r.field_or_relation == "approval_binding"))
        self.assertTrue(all(not r.authorization_relevant
                            for r in endpoint_records
                            if r.field_or_relation == "business_value"))
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
            markdown = paths[2].read_text(encoding="utf-8")
            table = [line for line in markdown.splitlines() if line.startswith("|")]
            self.assertGreater(len(table), 2)
            self.assertIn("Business value", table[0])
            self.assertIn("Action spec", table[0])
            widths = [len(line.strip("|").split("|")) for line in table]
            self.assertTrue(all(width == widths[0] for width in widths), widths)


    def test_missing_evidence_is_unobserved_not_confirmed_loss(self):
        from context_launder_bench.runtime import TrustedRuntime
        runtime = TrustedRuntime("e2-unknown", "sibling")
        runtime.observe_boundary(
            "unknown", "missing-before", None,
            represented_fields=("approval_binding",),
            enforced_fields=("approval_binding",),
        )
        result = RunResult(
            "e2-unknown", "test", "D0", None, False, "NO_ATTEMPT", None,
            runtime.events, runtime.canonical_log_digest(),
            attempt_status="no_attempt",
        )
        records = {r.field_or_relation: r for r in classify_result(result)}
        self.assertIs(records["approval_binding"].kind,
                      DiscontinuityKind.UNOBSERVED)
        self.assertIs(records["business_value"].kind,
                      DiscontinuityKind.UNOBSERVED)
        self.assertIsNone(records["approval_binding"].affects_authorization)
        self.assertTrue(records["approval_binding"].authorization_relevant)


if __name__ == "__main__":
    unittest.main()
