"""Offline compiler/coverage adversaries; no semantic model approval is claimed."""
import copy
from hashlib import sha256
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/literature-review/scripts/runtime"))
from litreview_core.hierarchical_proof import (DIMENSIONS, ProofError, RuntimeIdentity, payload_hash,
    seal_node, verify_proof, dependency_receipt)
from litreview_core import proof_planner
from litreview_core.proof_planner import PlanningError, node_payload, plan_review
from litreview_core.review_artifacts import draft_packet, inference_packet, render_section, validate_draft
from litreview_core.scientific_records import FIELDS, source_packet, validate_reader


class ProofPlannerTests(unittest.TestCase):
    def setUp(self):
        self.questions = [{"id": "effect", "text": "What effect and counterevidence are reported?"},
                          {"id": "conditions", "text": "Which conditions limit interpretation?"}]
        self.packets, self.records, self.cards = [], [], []
        for index, lang in enumerate(("English", "English and German")):
            pid = "paper-" + str(index)
            raw = ("# Fictional " + lang + " collection\r\n\r\n"
                   "Primary contrast +0.010, CI [-0.020,+0.040], includes zero.\r\n\r\n"
                   "Failure persists after the safeguard; monetary cost was not measured.\r\n").encode()
            packet = source_packet(pid, raw, self.questions)
            result_part, limit_part = packet["parts"][1]["part_id"], packet["parts"][2]["part_id"]
            findings = [
                {"local_id": "f-result", "field": "results", "text": "The contrast is uncertain.",
                 "attribution": "author_result", "evidence": [{"part_id": result_part, "quote": None}], "obligations": ["null_result"]},
                {"local_id": "f-limit", "field": "limitations", "text": "Failure persists and cost is unmeasured.",
                 "attribution": "author_limitation", "evidence": [{"part_id": limit_part, "quote": None}], "obligations": ["persistent_failure", "missing_measurement"]}]
            reader = {"observations": [{"part_id": p["part_id"], "note": "Records " + p["text"].strip()} for p in packet["parts"]],
                      "findings": findings,
                      "fields": [{"field": field, "status": "extracted" if field in {"results", "limitations"} else "unresolved",
                                  "reason": "Bounded test record; original source still needs independent review."} for field in FIELDS],
                      "questions": [{"question_id": q["id"], "status": "addressed", "reason": "Source-linked pattern and limitation.",
                                     "support": ["f-result"], "counterevidence": ["f-limit"]} for q in self.questions]}
            record = validate_reader(packet, reader, execution_id="reader-" + pid)
            packet_for_card = draft_packet("paper_card", [packet], [record], self.questions)
            claims = [self.claim("result", "The reported contrast is uncertain.", [pid], [pid + "/" + result_part], ["effect"]),
                      self.claim("limit", "Failure persists and monetary cost was not measured.", [pid], [pid + "/" + limit_part], ["conditions"])]
            value = {"claims": claims, "retention": [self.retention(o, "result" if o["kind"] == "null_result" else "limit") for o in packet_for_card["obligations"]], "cells": []}
            card = validate_draft(packet_for_card, value, execution_id="writer-card-" + pid)
            self.packets.append(packet)
            self.records.append(record)
            self.cards.append(card)
        self.comparison = self.make_comparison(self.cards)
        self.synthesis = self.make_synthesis(self.comparison)
        self.sections = self.cards + [self.comparison, self.synthesis]

    @staticmethod
    def claim(cid, text, papers, refs, questions, premises=()):
        return {"local_id": cid, "text": text, "evidence_refs": refs, "question_ids": questions,
                "attribution": "source_finding", "scope": "individual" if len(papers) == 1 else "corpus",
                "population_paper_ids": papers, "premise_claim_ids": list(premises)}

    @staticmethod
    def retention(obligation, cid):
        return {"obligation_id": obligation["id"], "status": "included", "claim_ids": [cid],
                "reason": "The actual claim retains this qualification; independent review still required."}

    def make_comparison(self, premises):
        packet = draft_packet("comparison", self.packets, self.records, self.questions,
                              dimensions=["effect", "conditions"], premises=premises)
        claims = []
        for i, source in enumerate(self.packets):
            refs = [source["paper_id"] + "/" + p["part_id"] for p in source["parts"][1:]]
            prior = [p["section_id"] + "/" + c["local_id"] for p in premises if p["paper_ids"] == [source["paper_id"]] for c in p["claims"]]
            claims.append(self.claim("comparison-" + str(i), "Uncertain contrast, persistent failure, and unmeasured cost.",
                [source["paper_id"]], refs, ["effect", "conditions"], prior))
        value = {"claims": claims, "retention": [self.retention(o, "comparison-" + str(next(i for i,p in enumerate(self.packets) if o["id"].startswith(p["paper_id"] + ":")))) for o in packet["obligations"]],
                 "cells": [{"paper_id": p["paper_id"], "dimension": d, "claim_ids": ["comparison-" + str(i)]}
                           for i,p in enumerate(self.packets) for d in ("effect", "conditions")]}
        return validate_draft(packet, value, execution_id="writer-comparison")

    def make_synthesis(self, comparison):
        packet = inference_packet([comparison], self.packets, self.records, self.questions)
        refs = sorted({r for c in comparison["claims"] for r in c["evidence_refs"]})
        claim = self.claim("global", "The two supplied studies retain uncertainty, persistent failures and unknown costs.",
            [p["paper_id"] for p in self.packets], refs, ["effect", "conditions"],
            [comparison["section_id"] + "/" + c["local_id"] for c in comparison["claims"]])
        claim["attribution"] = "analyst_inference"
        return validate_draft(packet, {"claims": [claim], "retention": [self.retention(o, "global") for o in packet["obligations"]],
            "cells": []}, execution_id="writer-synthesis")

    def make_premise_comparison(self):
        packet = inference_packet(self.cards, self.packets, self.records, self.questions,
                                  kind="comparison", dimensions=["effect", "conditions"])
        claims = copy.deepcopy(self.comparison['claims'])
        by_premise = {prior: claim['local_id'] for claim in claims for prior in claim['premise_claim_ids']}
        value = {'claims': claims,
            'retention': [self.retention(o, by_premise[o['premise_claim_id']]) for o in packet['obligations']],
            'cells': copy.deepcopy(self.comparison['cells'])}
        return validate_draft(packet, value, execution_id='writer-derived-comparison')

    def test_derived_comparison_reconstructs_actual_card_premise_packet(self):
        comparison = self.make_premise_comparison()
        self.sections = self.cards + [comparison, self.make_synthesis(comparison)]
        bundle = self.compile()
        source = bundle['node_specs']['src_' + comparison['section_id']]
        self.assertEqual(source['kind'], 'cross_group')
        self.assertEqual(set(source['dependencies']), {'src_' + c['section_id'] for c in self.cards})
        self.assertFalse(any(mid.startswith('original/') for mid in source['input_ids']))
        self.assertEqual(len(comparison['obligations']), sum(len(c['claims']) for c in self.cards))
        self.assertTrue(all(o['kind'] == 'premise_retention' for o in comparison['obligations']))
        own_units = [bundle['materials'][mid] for mid in source['input_ids']
                     if isinstance(bundle['materials'][mid], dict)
                     and bundle['materials'][mid].get('section_id') == comparison['section_id']]
        self.assertFalse(any(v.get('definition', {}).get('kind') == 'full_source_review' for v in own_units))

    def test_legacy_comparison_without_premises_stays_direct_source(self):
        comparison = self.make_comparison([])
        self.sections = self.cards + [comparison, self.make_synthesis(comparison)]
        bundle = self.compile()
        source = bundle['node_specs']['src_' + comparison['section_id']]
        self.assertEqual(source['kind'], 'source')
        self.assertEqual(source['dependencies'], [])
        self.assertTrue(any(mid.startswith('original/') for mid in source['input_ids']))

    def test_derived_comparison_cannot_omit_actual_premise_obligation(self):
        comparison = self.make_premise_comparison()
        comparison['obligations'].pop()
        comparison['retention'].pop()
        self.sections = self.cards + [comparison, self.make_synthesis(comparison)]
        self.reject('SECTION_RECONSTRUCTION_MISMATCH')

    def compile(self, **kwargs):
        return plan_review(self.sections, self.packets, self.records, **kwargs)

    def reject(self, code=None, **kwargs):
        with self.assertRaises(PlanningError) as caught:
            self.compile(**kwargs)
        if code:
            self.assertEqual(caught.exception.code, code, caught.exception.as_dict())
        return caught.exception

    def test_actual_artifact_inventories_and_pending_only_tasks(self):
        bundle = self.compile()
        expected = bundle["plan"]["payload"]["expected_coverage"]["source"]
        self.assertEqual(len(expected["claims"]), sum(len(s["claims"]) for s in self.sections))
        actual_lines = sum(sum(bool(x.strip()) for x in render_section(s)["text"].splitlines()) for s in self.sections)
        self.assertEqual(len(expected["lines"]), actual_lines)
        self.assertEqual(len(expected["cells"]), 4)
        self.assertEqual(len(expected["obligations"]), sum(len(s["retention"]) for s in self.sections) + len(self.packets))
        self.assertEqual(bundle["paper_ids"], ["paper-0", "paper-1"])
        self.assertGreaterEqual(len(bundle["node_specs"]), 9)
        self.assertTrue(all(spec["state"] == "pending" and "status" not in spec for spec in bundle["node_specs"].values()))

    def test_every_actual_nonempty_global_line_has_exact_mapping(self):
        rendered = self.compile()["materials"]["delivery/render"]
        self.assertEqual(sum(bool(x.strip()) for x in rendered["text"].splitlines()), len(rendered["lines"]))
        for line in rendered["lines"]:
            self.assertEqual(rendered["text"][line["start_char"]:line["end_char"]], line["text"])

    def test_scope_units_are_namespaced_per_section(self):
        expected = self.compile()["plan"]["payload"]["expected_coverage"]["source"]
        for dimension in ("papers", "questions", "obligations"):
            self.assertEqual(len(expected[dimension]), len(set(expected[dimension])))
        self.assertEqual(len(expected["papers"]), 6)
        self.assertEqual(len(expected["questions"]), 8)

    def test_original_crlf_and_full_bytes_reconstruct_exactly(self):
        bundle = self.compile()
        for packet in self.packets:
            mid = "original/" + packet["paper_id"]
            raw = bundle["materials"][mid]
            self.assertIsInstance(raw, bytes)
            self.assertIn(b"\r\n", raw)
            self.assertEqual(sha256(raw).hexdigest(), packet["source_sha256"])

    def test_source_leaves_get_originals_but_global_context_does_not(self):
        bundle = self.compile()
        for spec in bundle["node_specs"].values():
            originals = [mid for mid in spec["inputs"] if isinstance(bundle["materials"][mid], bytes)]
            if spec["kind"] == "source":
                self.assertTrue(originals)
            else:
                self.assertFalse(originals)
        source = bundle["node_specs"]["src_" + self.synthesis["section_id"]]
        self.assertEqual(source["kind"], "cross_group")
        self.assertEqual(source["dependencies"], ["src_" + self.comparison["section_id"]])
        for cid in render_section(self.comparison)["claims"]:
            self.assertTrue(any(cid in bundle["materials"][mid].get("claim_id", "") for mid in source["inputs"] if isinstance(bundle["materials"][mid], dict)))

    def test_missing_actual_claim_cannot_shrink_coverage(self):
        self.sections[0]["claims"].pop()
        self.reject("SECTION_RECONSTRUCTION_MISMATCH")

    def test_hidden_or_omitted_rendered_line_is_rejected(self):
        original = proof_planner.render_section
        def broken(section):
            result = original(section)
            result["text"] += "\nUndeclared scientific heading or assertion.\n"
            return result
        with patch.object(proof_planner, "render_section", broken):
            self.reject("SECTION_RECONSTRUCTION_MISMATCH")

    def test_missing_source_part_is_not_accepted_as_complete(self):
        self.packets[0]["parts"].pop(1)
        self.reject("SOURCE_OFFSET_MISMATCH")

    def test_source_offset_or_digest_tampering_is_rejected(self):
        self.packets[0]["parts"][0]["text"] = "Tampered source"
        self.reject("SOURCE_OFFSET_MISMATCH")

    def test_missing_provided_paper_is_rejected(self):
        self.packets.pop()
        self.reject("DUPLICATE_OR_UNKNOWN_RECORD")

    def test_reader_obligations_are_rederived_not_section_self_declarations(self):
        self.records[0]["obligations"].pop()
        self.reject("READER_RECORD_MISMATCH")

    def test_section_cannot_drop_retention_and_its_definition_together(self):
        self.sections[0]["retention"].pop()
        self.sections[0]["obligations"].pop()
        self.reject("SECTION_RECONSTRUCTION_MISMATCH")

    def test_missing_reader_observation_is_rejected(self):
        self.records[0]["observations"].pop()
        self.reject("READER_RECORD_MISMATCH")

    def test_missing_reader_record_is_rejected(self):
        self.records.pop()
        self.reject("MISSING_READER_RECORD")

    def test_comparison_missing_actual_cell_is_rejected(self):
        self.sections[2]["cells"].pop()
        self.reject("SECTION_RECONSTRUCTION_MISMATCH")

    def test_all_papers_require_cards_even_if_other_sections_represent_them(self):
        comparison = self.make_comparison([])
        synthesis = self.make_synthesis(comparison)
        self.sections = [self.cards[0], comparison, synthesis]
        self.reject("MISSING_OR_DUPLICATE_PAPER_CARD")

    def test_final_root_scope_cannot_hide_a_provided_paper(self):
        self.reject("INCOMPLETE_ROOT_SCOPE", root_section_ids=[self.cards[0]["section_id"]])

    def test_unknown_or_forward_premise_is_rejected(self):
        self.sections[-1]["premise_section_ids"] = ["nonexistent-section"]
        self.reject("UNKNOWN_OR_FORWARD_PREMISE")

    def test_self_reference_is_rejected(self):
        self.sections[-1]["premise_section_ids"] = [self.sections[-1]["section_id"]]
        self.reject("SELF_PREMISE")

    def test_changed_dependency_cannot_reuse_old_section_binding(self):
        self.sections[-1]["premise_section_ids"] = [self.cards[0]["section_id"], self.cards[1]["section_id"]]
        self.reject("SECTION_RECONSTRUCTION_MISMATCH")

    def test_new_source_detail_cannot_be_smuggled_through_old_premises(self):
        self.sections[-1]["claims"][0]["evidence_refs"].append("paper-0/" + self.packets[0]["parts"][0]["part_id"])
        self.reject("SECTION_RECONSTRUCTION_MISMATCH")

    def test_duplicate_section_and_source_membership_are_rejected(self):
        self.sections.append(self.sections[0])
        self.reject("DUPLICATE_INVENTORY")

    def test_bounded_diagnostics_block_instead_of_truncating(self):
        before = copy.deepcopy(self.packets)
        error = self.reject("OVERSIZED_PROOF_NODE", max_input_tokens=400)
        self.assertTrue(error.details["nodes"])
        self.assertEqual(self.packets, before)

    def test_counter_is_explicit_and_not_called_provider_usage(self):
        bundle = self.compile(token_counter=lambda text: len(text.encode("utf-8")))
        for spec in bundle["node_specs"].values():
            self.assertIn("not_wire_usage", spec["budget"]["counting_method"])
            self.assertTrue(spec["budget"]["complete_runtime_wire_admission_required"])

    def test_payload_preserves_material_hashes_and_requires_all_dependencies(self):
        bundle = self.compile()
        nid = "src_" + self.cards[0]["section_id"]
        payload = node_payload(bundle, nid)
        for mid, digest in payload["material_hashes"].items():
            original = bundle["materials"][mid]
            delivered = payload["materials"][mid]
            self.assertEqual(payload_hash(delivered.encode("utf-8") if isinstance(original, bytes) else delivered), digest)
        with self.assertRaises(PlanningError):
            node_payload(bundle, bundle["root_node_id"], {"unknown": {"payload_hash": "0" * 64}})

    def test_compiled_specs_can_feed_gate_with_explicit_test_attestations(self):
        # These synthetic identities only exercise the structural gate. They
        # are never persisted or presented as actual model-produced approvals.
        bundle = self.compile()
        identities, nodes = {}, {}
        for writer in bundle["plan"]["payload"]["writer_execution_ids"]:
            identities[writer] = RuntimeIdentity(writer, "ctx-" + writer, "writer", {})
        for nid, spec in bundle["node_specs"].items():
            deps = {dep: nodes[dep]["payload_hash"] for dep in spec["dependencies"]}
            execution = "test-" + nid
            node = seal_node(nid, spec["kind"], execution, spec["inputs"], deps, spec["coverage"],
                             "passed", "Synthetic offline structural test attestation; not actual model review.")
            nodes[nid] = node
            identities[execution] = RuntimeIdentity(execution, "ctx-" + execution, spec["role"], spec["inputs"], deps, {nid: node["payload_hash"]},
                delivered_dependency_receipt_hashes={dep: payload_hash(dependency_receipt(nodes[dep])) for dep in deps})
        receipt = verify_proof(bundle["plan"], nodes, bundle["materials"], identities)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["coverage_counts"]["source"]["claims"], 7)

    @staticmethod
    def structural_attestations(bundle):
        identities, nodes = {}, {}
        for eid in bundle['plan']['payload']['writer_execution_ids']:
            identities[eid] = RuntimeIdentity(eid, 'ctx-' + eid, 'writer', {})
        for nid, spec in bundle['node_specs'].items():
            deps = {dep: nodes[dep]['payload_hash'] for dep in spec['dependencies']}
            eid = 'offline-' + nid
            node = seal_node(nid, spec['kind'], eid, spec['inputs'], deps, spec['coverage'],
                'passed', 'Synthetic offline gate test only; no real scientific approval.')
            nodes[nid] = node
            identities[eid] = RuntimeIdentity(eid, 'ctx-' + eid, spec['role'], spec['inputs'], deps,
                                             {nid: node['payload_hash']},
                delivered_dependency_receipt_hashes={dep: payload_hash(dependency_receipt(nodes[dep])) for dep in deps}
                    if nid in bundle['plan']['payload'].get('dependency_delivery', {}).get('node_ids', []) else {})
        return nodes, identities

    def test_true_shards_partition_all_six_dimensions_and_pass_unchanged_gate(self):
        bundle = self.compile(max_input_tokens=28000)
        self.assertGreater(len(bundle['node_specs']), 9)
        self.assertTrue(all(spec['budget']['input_tokens'] <= 28000 for spec in bundle['node_specs'].values()))
        for phase, kinds in [('source', ('source', 'cross_group')), ('assembly', ('assembly', 'root'))]:
            for dim in DIMENSIONS:
                actual = [unit for spec in bundle['node_specs'].values() if spec['kind'] in kinds for unit in spec['coverage'][dim]]
                expected = bundle['plan']['payload']['expected_coverage'][phase][dim]
                self.assertEqual(set(actual), set(expected))
                self.assertEqual(len(actual), len(set(actual)))
        nodes, identities = self.structural_attestations(bundle)
        self.assertEqual(verify_proof(bundle['plan'], nodes, bundle['materials'], identities)['status'], 'passed')

    def test_single_line_binds_exact_line_context_without_whole_render(self):
        bundle = self.compile(max_input_tokens=28000)
        bindings = bundle['plan']['payload']['coverage_bindings']['lines']
        for line, mids in bindings.items():
            self.assertTrue(any(mid.startswith('line/') for mid in mids))
            self.assertTrue(any(mid.startswith('context/') for mid in mids))
            self.assertFalse(any(mid.startswith('render/') for mid in mids))
        for spec in bundle['node_specs'].values():
            self.assertFalse(any(mid.startswith('render/') for mid in spec['input_ids']))
            for mid in spec['input_ids']:
                if mid.startswith('context/'):
                    ctx = bundle['materials'][mid]
                    self.assertIn('render_text_sha256', ctx)
                    self.assertIn('actual_heading', ctx)
                    self.assertNotIn('source_catalog', ctx)

    def test_complete_source_omission_review_is_mandatory_host_derived(self):
        bundle = self.compile(max_input_tokens=28000)
        full_reviews = [(unit, value) for unit, value in bundle['materials'].items()
                        if isinstance(value, dict) and value.get('definition', {}).get('kind') == 'full_source_review']
        self.assertEqual(len(full_reviews), len(self.packets))
        for unit, value in full_reviews:
            definition = value['definition']
            pid = definition['paper_id']
            original = next(p for p in self.packets if p['paper_id'] == pid)
            self.assertEqual(definition['part_ids'], [p['part_id'] for p in original['parts']])
            self.assertEqual(definition['source_sha256'], original['source_sha256'])
            source = next(s for s in bundle['node_specs'].values()
                          if s['kind'] == 'source' and unit in s['coverage']['obligations'])
            self.assertIn('original/' + pid, source['input_ids'])
            self.assertIn('reader/' + pid, source['input_ids'])
            self.assertIn('section/' + value['section_id'], source['input_ids'])
            self.assertEqual(source['review_mode'], 'complete_original_omission_review_and_assigned_units')
            self.assertEqual(source['coverage']['claims'], [])
            self.assertEqual(source['coverage']['obligations'], [unit])

    def test_removing_full_source_review_cannot_pass_as_local_support(self):
        bundle = self.compile(max_input_tokens=28000)
        unit = next(mid for mid, value in bundle['materials'].items()
                    if isinstance(value, dict) and value.get('definition', {}).get('kind') == 'full_source_review')
        owner = next(s for s in bundle['node_specs'].values() if s['kind'] == 'source' and unit in s['coverage']['obligations'])
        owner['coverage']['obligations'].remove(unit)
        nodes, identities = self.structural_attestations(bundle)
        with self.assertRaises(ProofError):
            verify_proof(bundle['plan'], nodes, bundle['materials'], identities)

    def test_selected_child_claim_context_still_required_by_cross_group(self):
        bundle = self.compile(max_input_tokens=30000)
        parent = next(s for s in bundle['node_specs'].values() if s['kind'] == 'cross_group')
        child = bundle['node_specs'][parent['dependencies'][0]]
        unit = child['coverage']['obligations'][0]
        mid = bundle['plan']['payload']['coverage_bindings']['obligations'][unit][0]
        self.assertIn(mid, parent['input_ids'])
        parent['input_ids'].remove(mid)
        del parent['inputs'][mid]
        payload = bundle['plan']['payload']
        payload['node_input_requirements'][parent['node_id']].remove(mid)
        bundle['plan']['payload_hash'] = payload_hash(payload)
        nodes, identities = self.structural_attestations(bundle)
        with self.assertRaises(ProofError) as caught:
            verify_proof(bundle['plan'], nodes, bundle['materials'], identities)
        self.assertEqual(caught.exception.code, 'MISSING_SCIENTIFIC_PREMISES')

    def test_view_binds_selected_claims_and_omits_unrelated_leaf_raw_duties(self):
        comparison = self.make_premise_comparison()
        self.sections = self.cards + [comparison, self.make_synthesis(comparison)]
        bundle = self.compile()
        parent = bundle['node_specs']['src_' + comparison['section_id']]
        declared = bundle['plan']['payload']['dependency_scientific_views']
        self.assertEqual(declared['schema'], 'dependency-scientific-views/1')
        self.assertEqual(declared['nodes'][parent['node_id']], parent['scientific_view'])
        view_mid = 'dependency-view/' + parent['node_id']
        self.assertIn(view_mid, parent['input_ids'])
        skipped = []
        for dep, claims in parent['scientific_view'].items():
            for cid in claims:
                self.assertTrue(set(bundle['plan']['payload']['coverage_bindings']['claims'][cid]) <= set(parent['input_ids']))
            for unit in bundle['node_specs'][dep]['coverage']['obligations']:
                for mid in bundle['plan']['payload']['coverage_bindings']['obligations'][unit]:
                    if isinstance(bundle['materials'][mid], dict) and 'definition' in bundle['materials'][mid]:
                        self.assertNotIn(mid, parent['input_ids'])
                        skipped.append(mid)
        self.assertTrue(skipped)
        nodes, identities = self.structural_attestations(bundle)
        self.assertEqual(verify_proof(bundle['plan'], nodes, bundle['materials'], identities)['status'], 'passed')

    def test_budget_counter_receives_current_deterministic_worker_views(self):
        observed = []
        def counter(text):
            import json
            packet = json.loads(text)
            observed.append(packet)
            return len(text.encode('utf-8'))
        self.compile(token_counter=counter)
        self.assertTrue(observed)
        self.assertTrue(all(p.get('responsibility_encoding') == 'proof-unit-aliases/1' and
                            p.get('citation_view', {}).get('schema') == 'proof-citation-view/1' for p in observed))

    def test_integration_joins_roll_up_all_fragments_without_double_coverage(self):
        bundle = self.compile(max_input_tokens=28000)
        joins = [s for s in bundle['node_specs'].values() if s['node_id'].startswith('join_')]
        self.assertTrue(joins)
        for spec in joins:
            self.assertEqual(spec['kind'], 'assembly')
            self.assertFalse(any(spec['coverage'].values()))
            self.assertGreaterEqual(len(spec['dependencies']), 2)
            self.assertTrue(any(mid.startswith('line/') for mid in spec['input_ids']))
        root = bundle['node_specs'][bundle['root_node_id']]
        self.assertFalse(any(spec.startswith('section/') or '/obligation/' in spec for spec in root['input_ids']))
        self.assertFalse(any(root['coverage'].values()))

    def test_oversized_indivisible_claim_or_source_audit_requests_writing_split(self):
        error = self.reject('OVERSIZED_PROOF_NODE', max_input_tokens=5000)
        self.assertTrue(error.details['split_writing_required'])
        self.assertTrue(error.details['minimum_atomic_package'])

    def test_source_granularity_also_bounds_downstream_material_and_verdict_fan_in(self):
        bundle = self.compile(max_scientific_units=2)
        for spec in bundle['node_specs'].values():
            if spec['kind'] in ('source', 'cross_group'):
                self.assertLessEqual(sum(len(spec['coverage'][dim]) for dim in ('claims', 'obligations', 'cells')), 2)
            self.assertLessEqual(len(spec['coverage']['claims']) + len(spec['coverage']['obligations']), 2)
        nodes, identities = self.structural_attestations(bundle)
        self.assertEqual(verify_proof(bundle['plan'], nodes, bundle['materials'], identities)['status'], 'passed')

    def test_invalid_scientific_granularity_is_rejected(self):
        for value in (0, 129, True):
            self.reject('INVALID_BUDGET', max_scientific_units=value)

    def test_explicit_128_units_is_configurable_without_changing_context_cap(self):
        bundle = self.compile(max_scientific_units=128)
        self.assertEqual(bundle['max_scientific_units'], 128)
        self.assertTrue(all(s['budget']['input_tokens'] <= 120000 for s in bundle['node_specs'].values()))

    def test_full_source_merge_is_default_off_and_strictly_boolean(self):
        default = self.compile()
        explicit = self.compile(merge_full_source=False)
        self.assertFalse(default['merge_full_source'])
        self.assertEqual(default, explicit)
        for value in (None, 1, 'true'):
            self.reject('INVALID_PACKING_OPTION', merge_full_source=value)

    def test_opt_in_merge_keeps_all_originals_duties_and_independent_assembly(self):
        baseline = self.compile()
        merged = self.compile(merge_full_source=True)
        self.assertLess(len(merged['node_specs']), len(baseline['node_specs']))
        self.assertEqual(merged['plan']['payload']['expected_coverage'], baseline['plan']['payload']['expected_coverage'])
        for card in self.cards:
            sid, pid = card['section_id'], card['paper_ids'][0]
            source = [s for s in merged['node_specs'].values() if s['section_id'] == sid and s['kind'] == 'source']
            assembly = [s for s in merged['node_specs'].values() if s['section_id'] == sid and s['kind'] == 'assembly']
            self.assertEqual(len(source), 1)
            self.assertEqual(len(assembly), 1)
            self.assertEqual(source[0]['coverage'], assembly[0]['coverage'])
            self.assertEqual(assembly[0]['dependencies'], [source[0]['node_id']])
            self.assertEqual(source[0]['role'], 'verifier')
            self.assertEqual(assembly[0]['role'], 'assembly-auditor')
            self.assertIn('original/'+pid, source[0]['inputs'])
            self.assertIn('reader/'+pid, source[0]['inputs'])
            self.assertIn('section/'+sid, source[0]['inputs'])
            self.assertEqual(merged['materials']['original/'+pid], baseline['materials']['original/'+pid])
            full = [uid for uid in source[0]['coverage']['obligations']
                    if merged['materials'][uid]['definition']['kind'] == 'full_source_review']
            self.assertEqual(len(full), 1)
            self.assertEqual(len(source[0]['coverage']['claims']), len(card['claims']))
        for phase, kinds in [('source', ('source','cross_group')), ('assembly', ('assembly','root'))]:
            for dim in DIMENSIONS:
                actual = [uid for s in merged['node_specs'].values() if s['kind'] in kinds for uid in s['coverage'][dim]]
                self.assertEqual(len(actual), len(set(actual)))
                self.assertEqual(set(actual), set(merged['plan']['payload']['expected_coverage'][phase][dim]))
        nodes, identities = self.structural_attestations(merged)
        self.assertEqual(verify_proof(merged['plan'], nodes, merged['materials'], identities)['status'], 'passed')

    def test_source_fit_but_paired_assembly_oversize_preserves_original_partition(self):
        import json
        oversized_merges = []
        def count(text):
            task = json.loads(text)
            full = any(isinstance(v,dict) and v.get('definition',{}).get('kind') == 'full_source_review'
                       for v in task['materials'].values())
            if task['kind'] == 'assembly' and task['coverage']['claims'] and full:
                oversized_merges.append(task['node_id'])
                return 120001
            return len(text.encode('utf-8'))
        original = self.compile(token_counter=count)
        merged = self.compile(token_counter=count,merge_full_source=True)
        self.assertTrue(oversized_merges)
        self.assertEqual(merged['node_specs'], original['node_specs'])
        self.assertEqual(merged['plan'], original['plan'])

    def test_merge_never_exceeds_explicit_unit_or_input_limits(self):
        baseline = self.compile(max_scientific_units=2)
        merged = self.compile(max_scientific_units=2,merge_full_source=True)
        self.assertEqual(merged['node_specs'],baseline['node_specs'])
        error = self.reject('OVERSIZED_PROOF_NODE',merge_full_source=True,max_input_tokens=5000)
        self.assertTrue(error.details['split_writing_required'])

    def test_merged_negative_is_not_approved_or_replaced_by_other_positive_nodes(self):
        bundle = self.compile(merge_full_source=True)
        nodes, identities = self.structural_attestations(bundle)
        nid = next(n for n,s in bundle['node_specs'].items() if s['kind']=='source' and s['coverage']['claims'])
        old = nodes[nid]
        args = old['payload']
        negative = seal_node(nid,args['kind'],args['execution_id'],args['inputs'],args['dependencies'],args['coverage'],
                             'needs_revision','Actual negative must fail; synthetic gate adversary only.')
        nodes[nid] = negative
        old_identity=identities[args['execution_id']]
        identities[args['execution_id']]=RuntimeIdentity(args['execution_id'],old_identity.context_id,
            old_identity.role,args['inputs'],args['dependencies'],{nid:negative['payload_hash']},
            delivered_dependency_receipt_hashes=old_identity.delivered_dependency_receipt_hashes)
        with self.assertRaises(ProofError) as caught:
            verify_proof(bundle['plan'],nodes,bundle['materials'],identities)
        self.assertEqual(caught.exception.code,'SEMANTIC_REVIEW_FAILED')


if __name__ == "__main__":
    unittest.main()
