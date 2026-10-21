"""Offline tests for reasoning controls; no model endpoint is allowed."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("reasoning_controls", ROOT / "scripts/benchmark_reasoning_controls.py")
controls = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = controls
SPEC.loader.exec_module(controls)

from litreview_core.record_review import RecordReviewFailure, restore_record, validate_record_review
from litreview_core.task_store import canonical
from langchain_core.messages import AIMessage, ToolMessage
from test_native_agent import ScriptedModel


ORIGINAL_SENTENCES = {
    "s04": ["The study uses a randomized crossover experiment with balanced query order.",
        "The aggregate comparison estimates an intervention-minus-baseline difference of +0.019 in answer F1, with a ninety-five percent confidence interval from -0.006 to +0.044.",
        "The interval includes zero, so this analysis does not establish a clear aggregate improvement."],
    "s03": ["The study uses a cluster-randomized controlled experiment.",
        "Monetary cost was not measured in either condition.", "The study did not measure energy consumption."],
    "s02": ["The study uses a observational before-and-after comparison.",
        "The aggregate comparison estimates an intervention-minus-baseline difference of +0.048 in nDCG@10, with a ninety-five percent confidence interval from +0.012 to +0.084.",
        "The nonrandom design permits residual confounding, so the observed association does not establish that the intervention caused the difference."],
    "s07": ["The study uses a observational interrupted time-series study.",
        "The aggregate comparison estimates an intervention-minus-baseline difference of -0.062 in stale-answer rate, with a ninety-five percent confidence interval from -0.089 to -0.035.",
        "The unexpected finding was the persistence of a burst of uncached requests immediately after invalidation despite the addition of dependency-specific warm-up queues.",
        "Monetary cost was not measured in either condition."],
    "s08": ["The study uses a randomized query-pair controlled experiment.",
        "The aggregate comparison estimates an intervention-minus-baseline difference of +0.047 in Recall@5, with a ninety-five percent confidence interval from +0.018 to +0.076.",
        "The prespecified subgroup consists of adversarial near-synonym queries.",
        "The subgroup contrast was -0.039, with a ninety-five percent confidence interval from -0.074 to -0.004.",
        "The subgroup interval excludes zero in the adverse direction, providing explicit evidence of worse subgroup performance.",
        "The unexpected finding was the persistence of mapping a near-synonym to a semantically adjacent but wrong concept despite the addition of explicit negative concept constraints.",
        "The study did not measure downstream clinical utility."],
}


def judgment(case, *, oracle=True, wrong_target=False):
    value = {"verdicts": [{"finding_id": row["local_id"], "status": "supported", "reason": "Local scripted fixture judgment."}
                           for row in case.record["findings"]],
             "checked_part_ids": [row["part_id"] for row in case.source["parts"]],
             "question_ids": [row["id"] for row in case.source["questions"]],
             "omission_check": "passed", "omission_reason": "Local scripted fixture checks all source blocks.", "issues": []}
    expected = case.expected
    if oracle and expected["expected_status"] != "passed":
        if expected["target_finding_id"]:
            selected = value["verdicts"][0]["finding_id"] if wrong_target else expected["target_finding_id"]
            next(row for row in value["verdicts"] if row["finding_id"] == selected)["status"] = "contradicted"
        else:
            value["omission_check"] = "needs_revision"
            value["issues"] = [{"kind": "important_omission", "finding_ids": [],
                "part_ids": [case.source["parts"][0]["part_id"] if wrong_target else expected["omitted_part_id"]],
                "description": "The specified source block has an important missing qualification.",
                "required_correction": "Retain the original persistent-failure qualification."}]
    return value


def validated(case, value):
    try:
        return validate_record_review(case.source, case.record, value, execution_id="offline-independent-verifier")
    except RecordReviewFailure as exc:
        return exc.review


class ReasoningControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="reasoning-controls-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "original-sources"
        self.sources.mkdir()
        for study, statements in ORIGINAL_SENTENCES.items():
            (self.sources / (study + ".md")).write_text("# SYNTHETIC ORIGINAL FIXTURE\n\n" + "\n\n".join(statements) + "\n", encoding="utf-8")
        (self.sources / "gold.json").write_text("DO NOT READ HOST GOLD", encoding="utf-8")
        self.cases = controls.build_cases(self.sources)
        self.network_attempts = []

        def blocked(*args, **kwargs):
            self.network_attempts.append(True)
            raise AssertionError("Network forbidden in reasoning control tests")
        self.addCleanup(patch.stopall)
        patch.object(socket, "create_connection", blocked).start()
        import httpx
        patch.object(httpx.Client, "send", blocked).start()
        patch.object(httpx.AsyncClient, "send", blocked).start()

    def test_counts_and_host_expected_never_enter_inputs(self):
        self.assertEqual(len(self.cases), 7)
        self.assertEqual(len(controls.build_cases(self.sources, paired_positives=True)), 12)
        for case in self.cases:
            isolated = replace(case, expected={**case.expected, "host_secret": "EXPECTED_LABEL_SENTINEL"})
            model_input = canonical(isolated.assigned_inputs()).decode()
            self.assertNotIn("EXPECTED_LABEL_SENTINEL", model_input)
            self.assertNotIn("expected_status", model_input)
            self.assertNotIn(case.expected["kind"], model_input)
            self.assertEqual(case.workload_hash, isolated.workload_hash)
            self.assertTrue(case.record["execution_id"].startswith("host-control-fixture-author-"))
            self.assertEqual(case.record["verification_status"], "unverified")

    def test_all_source_spans_and_record_projection_roundtrip(self):
        for case in self.cases:
            raw = Path(case.provenance["source_path"]).read_bytes()
            for span in case.provenance["original_fragments"]:
                selected = raw[span["start_byte"]:span["end_byte"]]
                self.assertEqual(controls.sha256(selected).hexdigest(), span["quote_sha256"])
                self.assertIn(selected.decode(), "".join(part["text"] for part in case.source["parts"]))
            self.assertEqual(canonical(restore_record(case.source, case.assigned_inputs()["record.json"])), canonical(case.record))

    def test_only_original_markdown_is_read(self):
        original = Path.read_bytes
        touched = []

        def read(path):
            touched.append(path)
            return original(path)
        with patch.object(Path, "read_bytes", read):
            controls.build_cases(self.sources)
        self.assertTrue(touched)
        self.assertTrue(all(path.suffix == ".md" for path in touched))

    def test_targeted_false_claims_and_omissions_detected(self):
        for case in self.cases:
            review = validated(case, judgment(case))
            self.assertTrue(controls.grade_review(case, review)["correct"])
            if case.expected["expected_status"] != "passed":
                all_supported = validated(case, judgment(case, oracle=False))
                self.assertFalse(controls.grade_review(case, all_supported)["correct"])
                wrong = validated(case, judgment(case, wrong_target=True))
                self.assertFalse(controls.grade_review(case, wrong)["correct"], "Unrelated rejection cannot pass the target control")
        self.assertFalse(controls.grade_review(self.cases[0], None)["completed_judgment"])

    def test_actual_provider_reasoning_and_missing_cost_are_not_hidden(self):
        result = controls.transport_metrics({"events": [
            {"response_id": "v1", "provider": "fixture-provider", "usage": {"cost": 0,
                "completion_tokens_details": {"reasoning_tokens": 17499}}},
            {"response_id": "unmatched-timeout", "usage": None},
        ]}, [{"event": "model_response", "response_id": "v1", "role": "verifier", "metadata": {"finish_reason": "error"}}])
        self.assertEqual(result["verifier"]["reported_reasoning_tokens"], 17499)
        self.assertEqual(result["verifier"]["recorded_cost_usd"], 0)
        self.assertEqual(result["all_roles"]["responses_missing_cost"], 1)
        self.assertEqual(result["transport_events_without_role_match"], 1)
        self.assertEqual(result["verifier_finish_reasons"], {"error": 1})

    def test_same_profile_native_mock_orchestration_and_reasoning_toggle(self):
        model_settings, parent_counter = [], [0]
        cases_by_execution = {case.record["execution_id"]: case for case in self.cases}

        def coordinator_script(messages, role):
            parent_counter[0] += 1
            latest = messages[-1]
            if isinstance(latest, ToolMessage) and latest.name == "ready_tasks":
                ready = json.loads(latest.content)["ready"]
                if ready:
                    return AIMessage(content="", response_metadata={"id": f"offline-coordinator-{parent_counter[0]}"},
                        tool_calls=[{"name": "task", "args": row, "id": f"offline-task-{parent_counter[0]}-{index}"} for index, row in enumerate(ready)])
                return AIMessage(content="All independent scripted judgments are recorded.")
            return AIMessage(content="", tool_calls=[{"name": "ready_tasks", "args": {}, "id": f"offline-ready-{parent_counter[0]}"}])

        def verifier_script(messages, role):
            text = str(messages[-1].content)
            self.assertNotIn("expected_status", text)
            self.assertNotIn("gold.json", text)
            encoded = re.search(r"<assigned_input path='/inputs/record.json'>\n(.*?)\n</assigned_input>", text, re.S).group(1)
            projection = json.loads(encoded)
            case = cases_by_execution[projection["record"]["execution_id"]]
            # Oracle output is explicitly a local mock; no Qwen quality is
            # inferred from this integration test.
            return AIMessage(content="", response_metadata={"id": "offline-verifier-" + case.case_id},
                tool_calls=[{"name": "submit_result", "args": {"data": json.dumps(judgment(case))},
                             "id": "offline-submit-" + case.case_id}])

        def model_factory(**settings):
            model_settings.append(settings)
            worker = settings.get("force_submit", False)
            return ScriptedModel(role="verifier" if worker else "coordinator",
                script=verifier_script if worker else coordinator_script,
                profile={"tool_calling": True, "max_input_tokens": 200000, "max_output_tokens": 16384})

        class OfflineCounter:
            identity = {"method": "local fixture estimate, not measured provider tokens"}
            def __call__(self, payload):
                return len(json.dumps(payload, default=str)) // 4 + 100

        args = SimpleNamespace(workers=3, deadline=30, tokenizer=None, seed=17, provider=None, skills_root=ROOT / "skills")
        for enabled in (True, False):
            parent_counter[0] = 0
            arm = asyncio.run(controls.run_arm(args, self.cases, self.root / ("enabled" if enabled else "disabled"),
                reasoning_enabled=enabled, repetition=0, model_factory=model_factory, counter=OfflineCounter()))
            self.assertTrue(arm["passed"])
            self.assertEqual(arm["negative_detection"], {"correct": 6, "total": 6})
            self.assertEqual(arm["positive_acceptance"], {"correct": 1, "total": 1})
            self.assertFalse(arm["publication_verified"])
            self.assertFalse(arm["expected_labels_delivered_to_models"])
            self.assertEqual(len(arm["tasks"]), 7)
            self.assertEqual(sum(row["status"] == "failed" for row in arm["tasks"]), 6)
        workers = [row for row in model_settings if row.get("force_submit")]
        coordinators = [row for row in model_settings if not row.get("force_submit")]
        self.assertEqual(len(workers), 14)
        self.assertEqual({row["reasoning_enabled"] for row in workers}, {True, False})
        self.assertTrue(all(row["reasoning_enabled"] for row in coordinators))
        self.assertTrue(all(row["profile"] == "verifier" and row["max_tokens"] == 16384 for row in workers))
        self.assertTrue(all("reasoning_max_tokens" not in row for row in workers if not row["reasoning_enabled"]))
        self.assertEqual(self.network_attempts, [])


if __name__ == "__main__":
    unittest.main()
