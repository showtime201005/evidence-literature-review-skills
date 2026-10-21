"""Offline fixture consistency, not semantic approval or a model benchmark.

Set BENCHMARK_TOKENIZER_JSON to a local Qwen tokenizer.json to also measure all
100 raw manuscripts.  No network access, model weights, or API is required.
"""
import ast
from collections import Counter
from decimal import Decimal
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/generate_benchmark100.py"
_spec = importlib.util.spec_from_file_location("synthetic_benchmark100", SCRIPT)
benchmark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(benchmark)


class Benchmark100Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="litreview-benchmark100-offline-")
        cls.temp_path = Path(cls.temporary.name).resolve()
        cls.out = cls.temp_path / "fixture"
        cls.counter, cls.tokenizer_identity = None, None
        if os.environ.get("BENCHMARK_TOKENIZER_JSON"):
            cls.counter, cls.tokenizer_identity = benchmark.load_counter(Path(os.environ["BENCHMARK_TOKENIZER_JSON"]))
        cls.summary = benchmark.generate_dataset(cls.out, counter=cls.counter, tokenizer_identity=cls.tokenizer_identity)
        cls.gold = json.loads((cls.out / "gold.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((cls.out / "corpus-manifest.json").read_text(encoding="utf-8"))
        cls.studies = cls.gold["studies"]
        cls.text = {s["id"]: (cls.out / s["source_path"]).read_text(encoding="utf-8") for s in cls.studies}

    @classmethod
    def tearDownClass(cls):
        # Only the explicitly created, owned test directory is removed.
        assert cls.temp_path.parent == Path(tempfile.gettempdir()).resolve()
        assert cls.temp_path.name.startswith("litreview-benchmark100-offline-")
        assert Path(cls.temporary.name).resolve() == cls.temp_path
        cls.temporary.cleanup()

    def test_100_distinct_logical_papers_and_source_hashes(self):
        documents = self.manifest["documents"]
        self.assertEqual(len(documents), 100)
        self.assertEqual(len({d["paper_id"] for d in documents}), 100)
        self.assertEqual(len(list((self.out / "papers").glob("*.md"))), 100)
        self.assertEqual(len({s["source_sha256"] for s in self.studies}), 100)

    def test_manifest_contains_only_relative_original_markdown_paths(self):
        for row in self.manifest["documents"]:
            path = Path(row["path"])
            self.assertFalse(path.is_absolute())
            self.assertNotIn("..", path.parts)
            self.assertEqual(path.suffix, ".md")
            self.assertEqual((self.out / "papers" / path).resolve().parent, (self.out / "papers").resolve())
            self.assertTrue((self.out / "papers" / path).is_file())

    def test_source_bytes_match_all_recorded_hashes(self):
        summary = {row["paper_id"]: row for row in self.summary["documents"]}
        for s in self.studies:
            data = (self.out / s["source_path"]).read_bytes()
            digest = sha256(data).hexdigest()
            self.assertEqual(digest, s["source_sha256"])
            self.assertEqual(digest, summary[s["paper_id"]]["sha256"])
            self.assertEqual(len(data), summary[s["paper_id"]]["utf8_bytes"])
            self.assertNotIn(b"\r", data)

    def test_exactly_ten_sequential_page_markers(self):
        for s in self.studies:
            pages = re.findall(r"^## Page (\d{2}) of 10 — ", self.text[s["id"]], re.M)
            self.assertEqual(pages, ["%02d" % i for i in range(1, 11)])

    def test_genuine_parameter_variation_exceeds_ten_repeated_studies(self):
        signatures = {(s["domain"], s["mechanism"], s["design"], tuple(s["languages"]),
                       s["primary"]["baseline"], s["primary"]["difference"], s["update"]) for s in self.studies}
        self.assertEqual(len(signatures), 100)
        self.assertEqual(len({s["domain"] for s in self.studies}), 20)
        self.assertEqual(len({s["metric"] for s in self.studies}), 10)
        self.assertGreaterEqual(len({s["design"] for s in self.studies}), 8)
        self.assertGreaterEqual(len({(s["primary"]["baseline"], s["primary"]["difference"]) for s in self.studies}), 90)

    def test_all_families_have_beneficial_null_and_adverse_patterns(self):
        for family in range(5):
            rows = [s for s in self.studies if s["family"] == family]
            self.assertEqual(len(rows), 20)
            self.assertEqual({s["primary"]["interpretation"] for s in rows}, {"benefit", "uncertain", "adverse"})
        self.assertEqual(self.gold["outcome_counts"], dict(Counter(s["primary"]["interpretation"] for s in self.studies)))

    def test_contrast_means_and_intervals_are_decimal_consistent(self):
        for s in self.studies:
            for row in (s["primary"], s["subgroup"]):
                baseline, newer, difference = (Decimal(row[key]) for key in ("baseline", "intervention", "difference"))
                low, high = Decimal(row["ci_low"]), Decimal(row["ci_high"])
                self.assertEqual(newer - baseline, difference)
                self.assertLessEqual(low, difference)
                self.assertGreaterEqual(high, difference)
                self.assertGreaterEqual(min(baseline, newer), 0)
                self.assertLessEqual(max(baseline, newer), 1)
                self.assertEqual(row["interpretation"], benchmark.interval_kind(row["ci_low"], row["ci_high"], s["direction"]))

    def test_source_table_values_match_oracle_and_caption_units(self):
        for s in self.studies:
            text = self.text[s["id"]]
            self.assertIn("Table 1. Primary and prespecified subgroup outcomes for " + s["dataset"] + " using " + s["metric"], text)
            self.assertIn("Table 1 notes. Difference is intervention minus baseline", text)
            self.assertIn(s["direction"] + " is better.", text)
            for label, row in (("All eligible questions", s["primary"]), (s["subgroup_name"], s["subgroup"])):
                expected = ("| " + label + " | {baseline} | {intervention} | {difference} | [{ci_low}, {ci_high}] |").format(**row)
                self.assertIn(expected, text)
            self.assertIn("| Monetary cost, USD/query |", text)
            self.assertIn("Table 2 notes.", text)

    def test_ci_interpretation_never_turns_adverse_into_beneficial(self):
        for s in self.studies:
            sentence = benchmark._interpretation(s["primary"], s["direction"], "primary")
            if s["primary"]["interpretation"] == "adverse":
                self.assertIn("adverse direction", sentence)
                self.assertNotIn("favorable direction", sentence)
            elif s["primary"]["interpretation"] == "uncertain":
                self.assertIn("includes zero", sentence)
            self.assertIn(sentence, self.text[s["id"]])

    def test_subgroup_counterevidence_is_not_replaced_by_aggregate(self):
        self.assertEqual({s["subgroup"]["interpretation"] for s in self.studies}, {"uncertain", "adverse"})
        self.assertTrue(any(s["primary"]["interpretation"] == "benefit" and s["subgroup"]["interpretation"] == "adverse" for s in self.studies))
        for s in self.studies:
            self.assertIn(benchmark._interpretation(s["subgroup"], s["direction"], "subgroup"), self.text[s["id"]])

    def test_randomized_and_observational_designs_have_correct_causal_boundaries(self):
        self.assertEqual({s["randomized"] for s in self.studies}, {False, True})
        for s in self.studies:
            text = self.text[s["id"]]
            self.assertIn("The study uses a " + s["design"], text)
            if s["randomized"]:
                self.assertIn("Assignment supports a narrow causal interpretation", text)
            else:
                self.assertIn("Exposure was not randomly assigned", text)
                self.assertIn("residual confounding", text)

    def test_cost_unknown_partial_positive_and_measured_zero_are_distinct(self):
        self.assertEqual({s["cost_status"] for s in self.studies}, {"not_measured", "partially_reported", "reported"})
        zeros = []
        for s in self.studies:
            base, newer = s["cost_baseline"], s["cost_intervention"]
            text = self.text[s["id"]]
            source_row = "| Monetary cost, USD/query | " + (base or "not measured") + " | " + (newer or "not measured") + " |"
            self.assertIn(source_row, text)
            if None in (base, newer):
                self.assertIsNone(s["cost_difference"])
            else:
                self.assertEqual(Decimal(newer) - Decimal(base), Decimal(s["cost_difference"]))
            if s["cost_status"] == "not_measured":
                self.assertIn("unknown, not zero", text)
            if s["cost_status"] == "partially_reported":
                self.assertIn("intervention cost was not measured", text)
            if base == "0.000":
                zeros.append(s["id"])
                self.assertEqual(s["cost_status"], "reported")
                self.assertIn("explicitly recorded fictional waived request charge", text)
        self.assertGreaterEqual(len(zeros), 5)

    def test_twenty_explicit_shared_pairs_leave_eighty_data_groups(self):
        groups = Counter(s["study_group_id"] for s in self.studies)
        self.assertEqual(len(groups), 80)
        self.assertEqual(Counter(groups.values()), {1: 60, 2: 20})
        by_id = {s["id"]: s for s in self.studies}
        for s in self.studies:
            self.assertIn(s["study_group_id"], self.text[s["id"]])
            if s["paired_study_id"]:
                partner = by_id[s["paired_study_id"]]
                self.assertEqual(partner["study_group_id"], s["study_group_id"])
                self.assertEqual(partner["paired_study_id"], s["id"])
                self.assertEqual(partner["queries"], s["queries"])
                self.assertEqual(partner["documents"], s["documents"])
                self.assertNotEqual(partner["mechanism"], s["mechanism"])
                self.assertIn("do not turn that panel into independent evidence", self.text[s["id"]])

    def test_language_configuration_difference_does_not_imply_disjoint_languages(self):
        first, bilingual = self.studies[0], self.studies[20]
        self.assertNotEqual(first["languages"], bilingual["languages"])
        self.assertEqual(set(first["languages"]) & set(bilingual["languages"]), {"English"})
        self.assertFalse(self.gold["universal_controls"]["no_studies_share_a_language"])

    def test_named_updates_languages_and_missing_outcomes_are_in_source(self):
        for s in self.studies:
            text = self.text[s["id"]]
            for value in (s["language"], s["update"], s["missing"], s["release"], s["confound"]):
                self.assertIn(value, text)
            self.assertIn("The study did not measure " + s["missing"], text)

    def test_persistence_is_explicit_and_last_four_add_a_late_qualitative_failure(self):
        late = []
        for s in self.studies:
            text = self.text[s["id"]]
            self.assertIn("The unexpected finding was the persistence of " + s["failure"], text)
            if s["late_failure"]:
                late.append(s["id"])
                page10 = text.index("## Page 10 of 10")
                self.assertGreater(text.index(s["late_failure"]), page10)
                self.assertNotIn(s["late_failure"], text[:page10])
                self.assertEqual(text.count(s["late_failure"]), 1)
                self.assertIn("no separately measured failure frequency", text[page10:])
        self.assertEqual(late, ["S097", "S098", "S099", "S100"])

    def test_gold_is_host_only_and_never_in_corpus_papers(self):
        self.assertTrue(self.gold["host_only"])
        self.assertTrue(self.gold["do_not_send_to_models"])
        self.assertFalse((self.out / "papers/gold.json").exists())
        self.assertEqual({p.suffix for p in (self.out / "papers").iterdir()}, {".md"})
        for text in self.text.values():
            for forbidden in ("universal_controls", "do_not_send_to_models", "expected_data_group_count", "gold.json"):
                self.assertNotIn(forbidden, text)

    def test_all_sources_disclose_synthetic_template_and_no_real_publication(self):
        self.assertIn("Template-based", self.summary["limitations"][0])
        for text in self.text.values():
            self.assertIn("SYNTHETIC BENCHMARK MANUSCRIPT", text)
            self.assertIn("No real authors, publication date, DOI", text)
            self.assertIn("corpus-only policy", text)
            self.assertIn("does not allow external browsing", text)

    def test_existing_output_is_never_overwritten(self):
        before = {p.relative_to(self.out).as_posix(): sha256(p.read_bytes()).hexdigest() for p in self.out.rglob("*") if p.is_file()}
        with self.assertRaises(FileExistsError):
            benchmark.generate_dataset(self.out)
        after = {p.relative_to(self.out).as_posix(): sha256(p.read_bytes()).hexdigest() for p in self.out.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_seed_is_deterministic_and_changes_scientific_parameters(self):
        same = benchmark.build_studies(benchmark.DEFAULT_SEED)
        self.assertEqual([{k: v for k, v in row.items() if k not in {"source_path", "source_sha256"}} for row in self.studies], same)
        changed = benchmark.build_studies(benchmark.DEFAULT_SEED + 1)
        self.assertNotEqual(same[0]["primary"], changed[0]["primary"])
        self.assertEqual([s["id"] for s in same], [s["id"] for s in changed])

    def test_optional_actual_raw_qwen_token_bounds(self):
        if self.counter is None:
            self.skipTest("Set BENCHMARK_TOKENIZER_JSON for actual local Qwen token measurement")
        self.assertTrue(self.summary["token_lengths_measured"])
        self.assertIn("not wire usage", self.summary["tokenizer"]["method"])
        for row in self.summary["documents"]:
            text = (self.out / row["path"]).read_text(encoding="utf-8")
            count = type(self).counter(text)
            self.assertEqual(count, row["raw_qwen_tokens"])
            self.assertGreaterEqual(count, 6500)
            self.assertLessEqual(count, 9000)

    def test_without_tokenizer_does_not_claim_measured_tokens(self):
        text, count = benchmark.make_paper(self.studies[0])
        self.assertIsNone(count)
        self.assertGreaterEqual(len(text.split()), 5350)

    def test_no_runtime_import_of_private_generator_or_desktop_paths(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        self.assertFalse(any("generate_synthetic_benchmark" in name or "qwen_token_counter" in name for name in imported))


if __name__ == "__main__":
    unittest.main()
