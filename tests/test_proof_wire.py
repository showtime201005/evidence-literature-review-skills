"""Offline exact-wire invariants. No model or scientific approval is simulated."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"skills/literature-review/scripts/runtime"))
sys.path.insert(0, str(ROOT/"tests"))

from litreview_core.proof_wire import (SCHEMA, project_proof_task, restore_proof_task,
                                     restore_submission_ids, proof_wire_stats)
from litreview_core.proof_planner import node_payload
from litreview_core.task_store import canonical
import test_proof_planner as planner_fixtures


class ProofWireTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        def forbidden(*args, **kwargs):
            raise AssertionError("Network/model API forbidden in proof-wire tests")
        patch.object(socket, "create_connection", forbidden).start()
        self.claim = "section_"+"ab"*32+"/claim-result"
        self.obligation = "section_"+"cd"*32+"/obligation/persistent-failure"
        self.prose = "The confidence interval includes zero, monetary cost was not measured, and failure persists after mitigation."
        line = self.prose+" [source fictional-paper/p0002]"
        raw = ("SYNTHETIC ONLY\r\n\r\nPrimary contrast +0.010, CI [-0.020,+0.040]. "
               "Cost was not measured. Failure remained after the safeguard.\r\n")
        common = {"claim_id": self.claim, "text": self.prose, "evidence_refs": ["fictional-paper/p0002"]}
        self.packet = {"schema": "hierarchical-proof-task/1", "node_id": "node_"+"ef"*32,
            "kind": "cross_group", "coverage": {"claims": [self.claim], "lines": ["line_"+"ba"*32],
                "papers": ["fictional-paper"], "questions": ["q-effect"], "cells": [], "obligations": [self.obligation]},
            "material_hashes": {"claim/"+self.claim: "11"*32, "render/section": "22"*32, "original/paper": sha256(raw.encode()).hexdigest()},
            "materials": {"claim/"+self.claim: common, "section/section": {"claims": [copy.deepcopy(common)],
                "obligations": [{"id": self.obligation, "reason": self.prose}], "null": None, "zero": 0, "measured": False},
                "render/section": {"schema": "review-section-render/1", "text": "## Synthetic\n\n"+line+"\n\n",
                    "lines": [{"id": "line_"+"ba"*32, "start_char": 14, "end_char": 14+len(line),
                               "text": line, "claim_ids": [self.claim]}]},
                "original/paper": raw},
            "required_dependency_ids": ["child_"+"ca"*32],
            "dependency_proofs": {"child_"+"ca"*32: {"payload": {"node_id": "child_"+"ca"*32,
                "status": "needs_revision", "reason": "An actual approval is absent in this structural fixture.", "issues": [self.obligation]}}}}

    def test_every_canonical_value_and_original_utf8_bytes_roundtrip(self):
        before = canonical(self.packet)
        wire = project_proof_task(self.packet)
        restored = restore_proof_task(wire)
        self.assertEqual(canonical(restored), before)
        self.assertEqual(canonical(self.packet), before, "Projection must not mutate canonical data")
        self.assertEqual(restored["materials"]["original/paper"].encode(), self.packet["materials"]["original/paper"].encode())
        self.assertEqual(wire["schema"], SCHEMA)
        self.assertEqual(wire["canonical_sha256"], sha256(before).hexdigest())
        self.assertEqual(restored["dependency_proofs"], self.packet["dependency_proofs"])
        self.assertEqual(next(iter(restored["dependency_proofs"].values()))["payload"]["status"], "needs_revision")
        self.assertEqual(restored["coverage"], self.packet["coverage"])
        self.assertEqual(restored["materials"]["section/section"]["measured"], False)
        self.assertIsNone(restored["materials"]["section/section"]["null"])

    def test_whole_scientific_prose_once_render_concat_and_complexity_are_reported(self):
        wire = project_proof_task(self.packet)
        self.assertEqual(sum(value == self.prose for value in wire["dictionary"].values()), 1)
        self.assertEqual(json.dumps(wire, ensure_ascii=False).count(self.prose), 1)
        stats = proof_wire_stats(wire)
        self.assertGreater(stats["references"], 0)
        self.assertGreater(stats["concatenations"], 0)
        self.assertGreaterEqual(stats["maximum_reference_chain"], 2)
        self.assertFalse(stats["model_readability_and_semantic_quality_measured"])
        self.assertGreaterEqual(stats["max_concatenation_pieces"], 2)
        self.assertIsInstance(stats["wire_json_bytes"], int)

    def test_json_literals_control_tags_ids_and_duplicate_values_do_not_collide(self):
        self.packet["materials"].update({"@0": "@123", "@@escaped": "@@literal",
            "control": {"$concat": ["plain original", "@0"]},
            "literal": {"$literal": {"$concat": ["original", None, False, 0, 0.0]}},
            "ordering": [1, True, "1", None, False, 0, 0.0, -0.0]})
        restored = restore_proof_task(project_proof_task(self.packet))
        self.assertEqual(canonical(restored), canonical(self.packet))
        self.assertEqual(restored["materials"]["@0"], "@123")
        self.assertIs(type(restored["materials"]["ordering"][0]), int)
        self.assertIs(type(restored["materials"]["ordering"][1]), bool)

    def test_repeated_structures_compact_without_changing_premises_or_obligations(self):
        body = copy.deepcopy(self.packet["materials"]["section/section"])
        for index in range(100):
            self.packet["materials"]["duplicate-material/"+str(index)] = copy.deepcopy(body)
        wire = project_proof_task(self.packet)
        self.assertLess(len(canonical(wire)), len(canonical(self.packet))*.5)
        self.assertEqual(restore_proof_task(wire), self.packet)

    def test_restore_submitted_unit_ids_only_preserves_negative_scientific_prose(self):
        wire = project_proof_task(self.packet)
        alias = next(key for key, value in wire["dictionary"].items() if value == self.claim)
        obligation_alias = next(key for key, value in wire["dictionary"].items() if value == self.obligation)
        reason = "Actual negative review retains literal "+alias+" in its authored prose."
        submission = {"checked": {"claims": [alias], "obligations": [obligation_alias]},
            "verdicts": [{"unit_id": alias, "verdict": "needs_revision", "reason": reason}],
            "status": "needs_revision", "reason": reason,
            "issues": [{"unit_ids": [obligation_alias, alias], "description": reason, "correction": reason}]}
        restored = restore_submission_ids(submission, wire)
        self.assertEqual(restored["checked"]["claims"], [self.claim])
        self.assertEqual(restored["verdicts"][0]["unit_id"], self.claim)
        self.assertEqual(restored["issues"][0]["unit_ids"], [self.obligation, self.claim])
        self.assertEqual(restored["reason"], reason)
        self.assertEqual(restored["status"], "needs_revision")
        self.assertEqual(restored["verdicts"][0]["reason"], reason)
        self.assertEqual(submission["verdicts"][0]["unit_id"], alias)

    def test_wire_corruption_missing_reference_cycles_and_hidden_extras_rejected(self):
        wire = project_proof_task(self.packet)
        variants = []
        value = copy.deepcopy(wire)
        value["canonical_sha256"] = "0"*64
        variants.append(value)
        value = copy.deepcopy(wire)
        value["task"] = "@9999999"
        variants.append(value)
        value = copy.deepcopy(wire)
        ref = next(iter(value["dictionary"]))
        value["dictionary"][ref] = ref
        variants.append(value)
        value = copy.deepcopy(wire)
        value["dictionary"]["@9999999"] = "UNREFERENCED_EXTRA_PROMPT"
        variants.append(value)
        value = copy.deepcopy(wire)
        value["guide"]["review"] = "Wrongly treat approval as premises"
        variants.append(value)
        value = copy.deepcopy(wire)
        ref = next(key for key, item in value["dictionary"].items() if item == self.prose)
        value["dictionary"][ref] += " Changed the scientific fact."
        variants.append(value)
        for variant in variants:
            with self.subTest(variant=variants.index(variant)), self.assertRaises(ValueError):
                restore_proof_task(variant)
        with self.assertRaisesRegex(ValueError, "budget"):
            restore_proof_task(wire, max_expanded_bytes=1)

    def test_invalid_submission_shape_or_non_string_alias_rejected(self):
        wire = project_proof_task(self.packet)
        valid = {"checked": {"claims": [self.claim]}, "verdicts": [], "issues": []}
        variants = [{**valid, "checked": {"claims": "@0"}}, {**valid, "checked": {"claims": [42]}},
                    {**valid, "verdicts": [False]}, {**valid, "issues": [{"unit_ids": "@0"}]}]
        for variant in variants:
            with self.assertRaises(ValueError):
                restore_submission_ids(variant, wire)

    def test_deterministic_canonical_encoding_not_mapping_insertion_order(self):
        reversed_packet = dict(reversed(list(self.packet.items())))
        self.assertEqual(canonical(project_proof_task(reversed_packet)), canonical(project_proof_task(self.packet)))

    def test_actual_native_planner_packets_each_restore_every_scientific_material(self):
        fixture = planner_fixtures.ProofPlannerTests()
        fixture.setUp()
        bundle = fixture.compile()
        for node_id in bundle["node_specs"]:
            with self.subTest(node=node_id):
                packet = node_payload(bundle, node_id)
                wire = project_proof_task(packet)
                restored = restore_proof_task(wire)
                self.assertEqual(canonical(restored), canonical(packet))
                self.assertEqual(restored["materials"], packet["materials"])
                self.assertEqual(restored["coverage"], packet["coverage"])
                self.assertEqual(restored["material_hashes"], packet["material_hashes"])
                self.assertEqual(restored["required_dependency_ids"], packet["required_dependency_ids"])


if __name__ == "__main__":
    unittest.main()
