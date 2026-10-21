"""Adversarial, zero-network tests of the new proof gate (not model QA)."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/literature-review/scripts/runtime"))
from litreview_core.hierarchical_proof import (  # noqa: E402
    DIMENSIONS, ProofError, RuntimeIdentity, payload_hash, seal_node, seal_plan, verify_proof,
    dependency_view_material, dependency_view_material_id,
    dependency_receipt, prepare_dependency_receipts, verify_dependency_closure,
)


def coverage(**items):
    return {dim: list(items.get(dim, [])) for dim in DIMENSIONS}


class ScientificViewGateTests(unittest.TestCase):
    """Synthetic attestations exercise mechanics only, never model quality."""
    def setUp(self):
        self.materials = {'original-a': b'Primary uncertain; subgroup adverse.\r\n',
            'original-b': b'Monetary cost not measured.\n', 'context': {'request': 'Compare supplied papers'},
            'leaf/a': {'claim_id': 'leaf/a', 'text': 'Uncertain estimate.', 'premise_claim_ids': []},
            'leaf/unrelated': {'claim_id': 'leaf/unrelated', 'text': 'Other qualified result.', 'premise_claim_ids': []},
            'leaf/b': {'claim_id': 'leaf/b', 'text': 'Cost not measured.', 'premise_claim_ids': []},
            'raw-duty': {'text': 'Original obligation remains independently certified at leaf.'},
            's/global': {'claim_id': 's/global', 'text': 'Estimate uncertain.', 'premise_claim_ids': ['leaf/a']},
            'line-global': {'id': 'line-global', 'text': 'Estimate uncertain.', 'claim_ids': ['s/global']},
            'cell-global': {'section_id': 's', 'claim_ids': ['global'], 'global_claim_ids': ['s/global']},
            'excluded': {'section_id': 's', 'definition': {'kind': 'premise_retention', 'premise_claim_id': 'leaf/b'},
                         'disposition': {'status': 'excluded', 'claim_ids': [], 'reason': 'Must still be independently assessed.'}}}
        self.child_cov = coverage(claims=['leaf/a', 'leaf/unrelated', 'leaf/b'], obligations=['raw-duty'])
        self.parent_cov = coverage(claims=['s/global'], lines=['line-global'], cells=['cell-global'], obligations=['excluded'])
        expected = {dim: self.child_cov[dim] + self.parent_cov[dim] for dim in DIMENSIONS}
        self.expected = {'source': expected, 'assembly': copy.deepcopy(expected)}
        self.requirements = {'claims': {'leaf/a': ['original-a'], 'leaf/unrelated': ['original-a'],
            'leaf/b': ['original-b'], 's/global': ['original-a']},
            'obligations': {'raw-duty': ['original-b'], 'excluded': ['original-b']}}
        self.views = {'cross': {'child': ['leaf/a', 'leaf/b']}}
        self.inputs = {'child': ['original-a', 'original-b', 'leaf/a', 'leaf/unrelated', 'leaf/b', 'raw-duty', 'context'],
            'cross': ['s/global', 'line-global', 'cell-global', 'excluded', 'leaf/a', 'leaf/b', 'context', dependency_view_material_id('cross')],
            'assembly': ['leaf/a', 'leaf/unrelated', 'leaf/b', 'raw-duty', 'context'],
            'root': ['s/global', 'line-global', 'cell-global', 'excluded', 'context']}
        self.kinds = {'child': 'source', 'cross': 'cross_group', 'assembly': 'assembly', 'root': 'root'}
        self.dependencies = {'child': [], 'cross': ['child'], 'assembly': ['child'], 'root': ['cross', 'assembly']}
        self.coverages = {'child': self.child_cov, 'cross': self.parent_cov, 'assembly': self.child_cov, 'root': self.parent_cov}
        self.build()

    def build(self, *, legacy=False, sync_view=True):
        if sync_view:
            self.materials[dependency_view_material_id('cross')] = dependency_view_material('cross', self.views['cross'])
        self.plan = seal_plan(self.materials, self.expected, ['writer'], ['root'],
            source_requirements=self.requirements, original_source_ids=['original-a', 'original-b'],
            node_ids=list(self.inputs), node_input_requirements=self.inputs,
            dependency_scientific_views=None if legacy else self.views)
        self.nodes, self.identities = {}, {'writer': RuntimeIdentity('writer', 'writer-context', 'writer', {})}
        for nid in ('child', *(('other',) if 'other' in self.inputs else ()), 'cross', 'assembly', 'root'):
            hashes = {mid: payload_hash(self.materials[mid]) for mid in self.inputs[nid]}
            deps = {dep: self.nodes[dep]['payload_hash'] for dep in self.dependencies[nid]}
            node = seal_node(nid, self.kinds[nid], 'exec-' + nid, hashes, deps, self.coverages[nid],
                             'passed', 'STRUCTURAL TEST ONLY; not a real scientific/model assessment.')
            self.nodes[nid] = node
            role = 'source_verifier' if self.kinds[nid] in ('source', 'cross_group') else 'assembly_auditor'
            self.identities['exec-' + nid] = RuntimeIdentity('exec-' + nid, 'ctx-' + nid, role,
                hashes, deps, {nid: node['payload_hash']}, task_call_id='test-task-' + nid)

    def verify(self):
        return verify_proof(self.plan, self.nodes, self.materials, self.identities)

    def reject(self, code):
        with self.assertRaises(ProofError) as caught:
            self.verify()
        self.assertEqual(caught.exception.code, code, caught.exception.as_dict())

    def test_selected_actual_claims_need_no_unrelated_child_raw_duties(self):
        self.assertNotIn('raw-duty', self.inputs['cross'])
        self.assertNotIn('leaf/unrelated', self.inputs['cross'])
        self.assertEqual(self.verify()['status'], 'passed')

    def test_legacy_absent_view_still_requires_all_child_science(self):
        self.build(legacy=True)
        self.reject('MISSING_SCIENTIFIC_PREMISES')

    def test_excluded_counterevidence_remains_required(self):
        self.views['cross']['child'] = ['leaf/a']
        self.build()
        self.reject('SCIENTIFIC_PREMISE_VIEW_MISMATCH')

    def test_actual_claim_premise_cannot_be_omitted(self):
        self.views['cross']['child'] = ['leaf/b']
        self.build()
        self.reject('SCIENTIFIC_PREMISE_VIEW_MISMATCH')

    def test_unrelated_claim_not_accepted_as_required_context(self):
        self.views['cross']['child'].append('leaf/unrelated')
        self.build()
        self.reject('SCIENTIFIC_PREMISE_VIEW_MISMATCH')

    def test_line_linked_actual_claim_must_be_delivered(self):
        self.materials['line-global']['claim_ids'] = ['leaf/unrelated']
        self.build()
        self.reject('MISSING_SCIENTIFIC_TARGET')

    def test_cell_linked_actual_claim_cannot_hide_in_metadata(self):
        self.materials['cell-global']['claim_ids'] = ['omitted']
        self.materials['cell-global']['global_claim_ids'] = ['s/omitted']
        self.build()
        self.reject('UNKNOWN_SCIENTIFIC_TARGET')

    def test_cell_global_and_local_target_links_must_agree(self):
        self.materials['cell-global']['global_claim_ids'] = ['leaf/a']
        self.build()
        self.reject('INVALID_SCIENTIFIC_TARGET')

    def test_target_claim_is_typed_and_not_a_prose_hint(self):
        self.materials['s/global'] = {'claim_id': 's/global', 'text': 'Premises are leaf/a and leaf/b'}
        self.build()
        self.reject('INVALID_SCIENTIFIC_TARGET')

    def test_missing_selected_scientific_binding_fails(self):
        self.inputs['cross'].remove('leaf/b')
        self.build()
        self.reject('MISSING_SCIENTIFIC_PREMISES')

    def test_selected_original_closure_cannot_borrow_unselected_paper(self):
        # Child certifies both papers, but parent selects only an A claim.
        self.materials['excluded']['definition']['premise_claim_id'] = 'leaf/a'
        self.requirements['obligations']['excluded'] = ['original-a']
        self.views['cross']['child'] = ['leaf/a']
        self.requirements['claims']['s/global'] = ['original-a', 'original-b']
        self.build()
        self.reject('MISSING_ORIGINAL_SOURCE')

    def test_declared_view_is_an_actual_runtime_input(self):
        self.inputs['cross'].remove(dependency_view_material_id('cross'))
        with self.assertRaises(ProofError) as caught:
            self.build()
        self.assertEqual(caught.exception.code, 'SCIENTIFIC_VIEW_NOT_BOUND')

    def test_rehashed_wrong_view_material_is_rejected(self):
        self.materials[dependency_view_material_id('cross')]['claims_by_dependency']['child'] = ['leaf/a']
        with self.assertRaises(ProofError) as caught:
            self.build(sync_view=False)
        self.assertEqual(caught.exception.code, 'SCIENTIFIC_VIEW_MATERIAL_MISMATCH')

    def test_failed_child_stays_failed_with_selected_view(self):
        node = self.nodes['child']['payload']
        self.nodes['child'] = seal_node(**{**node, 'status': 'unresolved'})
        self.identities['exec-child'] = replace(self.identities['exec-child'],
            output_hashes={'child': self.nodes['child']['payload_hash']})
        self.reject('SEMANTIC_REVIEW_FAILED')

    def test_selected_claim_requires_actual_child_coverage(self):
        self.add_other_source()
        self.views['cross'] = {'child': ['leaf/b'], 'other': ['leaf/a']}
        self.build()
        self.reject('UNCERTIFIED_SCIENTIFIC_PREMISE')

    def add_other_source(self):
        self.coverages['child']['claims'].remove('leaf/unrelated')
        self.inputs['other'] = ['leaf/unrelated', 'original-a']
        self.kinds['other'] = 'source'
        self.dependencies['other'] = []
        self.dependencies['cross'].append('other')
        self.coverages['other'] = coverage(claims=['leaf/unrelated'])

    def test_duplicate_claim_selection_across_edges_is_rejected(self):
        self.add_other_source()
        self.views['cross']['other'] = ['leaf/a']
        self.build()
        self.reject('DUPLICATE_SCIENTIFIC_PREMISE')

    def test_view_must_name_exact_actual_dependencies(self):
        self.add_other_source()
        self.build()
        self.reject('SCIENTIFIC_VIEW_DEPENDENCIES_MISMATCH')

    def test_view_on_direct_source_is_rejected(self):
        self.kinds['cross'] = 'source'
        self.build()
        self.reject('INVALID_SCIENTIFIC_VIEW')

    def test_view_cannot_have_an_empty_edge(self):
        self.views['cross']['child'] = []
        with self.assertRaises(ProofError) as caught:
            self.build()
        self.assertEqual(caught.exception.code, 'EMPTY_DECLARATION')

    def test_unsupported_view_version_fails_closed(self):
        self.plan['payload']['dependency_scientific_views']['schema'] = 'dependency-scientific-views/999'
        self.plan['payload_hash'] = payload_hash(self.plan['payload'])
        self.reject('UNSUPPORTED_SCIENTIFIC_VIEW')

    def test_assembly_cannot_claim_selected_source_edge_semantics(self):
        self.kinds['cross'] = 'assembly'
        self.build()
        self.reject('INVALID_SCIENTIFIC_VIEW')

    def test_scientific_view_snapshot_does_not_follow_mutable_caller(self):
        before = copy.deepcopy(self.plan)
        self.views['cross']['child'].clear()
        self.assertEqual(self.plan, before)
        self.assertEqual(self.verify()['status'], 'passed')


class HierarchicalProofTests(unittest.TestCase):
    def setUp(self):
        self.materials = {"src-a": b"English primary 0.8; adverse subgroup.\r\n",
                          "src-b": "English/German primary 0.7; cost unmeasured.\n".encode(),
                          "claim-a": {"text": "A uses English and reports an adverse subgroup."},
                          "claim-b": {"text": "B uses English/German and did not measure cost."},
                          "claim-global": {"text": "Both supplied studies use English."},
                          "line-a": {"text": "A adverse subgroup."}, "line-b": {"text": "B cost unknown."},
                          "line-global": {"text": "Both use English."},
                          "paper-a": {"documents": ["src-a"]}, "paper-b": {"documents": ["src-b"]},
                          "question-a": {"paper": "a", "question": "limitations"},
                          "question-b": {"paper": "b", "question": "limitations"},
                          "cell-a": {"paper": "a", "relation": "mixed"},
                          "cell-b": {"paper": "b", "relation": "unresolved_measurement"},
                          "obligation-a": {"text": "Preserve adverse subgroup."},
                          "obligation-b": {"text": "Do not infer zero cost."},
                          "context": {"request": "Compare supplied sources only."}}
        self.local = {}
        for suffix in ("a", "b"):
            self.local[suffix] = coverage(claims=["claim-" + suffix], lines=["line-" + suffix],
                papers=["paper-" + suffix], questions=["question-" + suffix],
                cells=["cell-" + suffix], obligations=["obligation-" + suffix])
        self.global_cov = coverage(claims=["claim-global"], lines=["line-global"])
        expected = {dim: self.local["a"][dim] + self.local["b"][dim] + self.global_cov[dim]
                    for dim in DIMENSIONS}
        self.expected = {"source": expected, "assembly": copy.deepcopy(expected)}
        self.requirements = {"claims": {"claim-a": ["src-a"], "claim-b": ["src-b"],
                                        "claim-global": ["src-a", "src-b"]},
                             "obligations": {"obligation-a": ["src-a"], "obligation-b": ["src-b"]}}
        self.plan = self.new_plan()
        self.nodes, self.identities = {}, {"writer": RuntimeIdentity("writer", "writer-real", "writer", {})}
        for suffix in ("a", "b"):
            mids = [item for units in self.local[suffix].values() for item in units]
            self.add_node("source-" + suffix, "source", self.local[suffix], mids + ["src-" + suffix])
        self.add_node("cross", "cross_group", self.global_cov,
                      self.cross_inputs(), ["source-a", "source-b"])
        for suffix in ("a", "b"):
            mids = [item for units in self.local[suffix].values() for item in units]
            self.add_node("assembly-" + suffix, "assembly", self.local[suffix], mids + ["context"], ["source-" + suffix])
        self.add_node("root", "root", self.global_cov, ["claim-global", "line-global", "context"],
                      ["cross", "assembly-a", "assembly-b"])

    def new_plan(self, **changes):
        planned_inputs = {}
        for suffix in ("a", "b"):
            mids = [item for units in self.local[suffix].values() for item in units]
            planned_inputs["source-" + suffix] = mids + ["src-" + suffix]
            planned_inputs["assembly-" + suffix] = mids + ["context"]
        planned_inputs["cross"] = self.cross_inputs()
        planned_inputs["root"] = ["claim-global", "line-global", "context"]
        values = dict(materials=self.materials, expected_coverage=self.expected,
                      writer_execution_ids=["writer"], roots=["root"], source_requirements=self.requirements,
                      original_source_ids=["src-a", "src-b"], node_ids=list(planned_inputs),
                      node_input_requirements=planned_inputs)
        values.update(changes)
        return seal_plan(**values)

    def cross_inputs(self):
        return ["claim-global", "line-global", "context", "claim-a", "claim-b",
                "cell-a", "cell-b", "obligation-a", "obligation-b"]

    def add_node(self, nid, kind, cov, mids, deps=()):
        inputs = {mid: payload_hash(self.materials[mid]) for mid in mids}
        dependencies = {dep: self.nodes[dep]["payload_hash"] for dep in deps}
        node = seal_node(nid, kind, "exec-" + nid, inputs, dependencies, cov,
                         "passed", "Independent review of the stated units against original-source proof.")
        self.nodes[nid] = node
        role = "source_verifier" if kind in {"source", "cross_group"} else "assembly_auditor"
        self.identities["exec-" + nid] = RuntimeIdentity("exec-" + nid, "context-" + nid, role,
            inputs, dependencies, {nid: node["payload_hash"]}, task_call_id="actual-task-" + nid,
            parent_context_id="coordinator-real")

    def reseal(self, nid, *, attest=True, **changes):
        old = self.nodes[nid]["payload"]
        args = dict(old)
        args.update(changes)
        self.nodes[nid] = seal_node(**args)
        identity = self.identities[args["execution_id"]]
        if attest:
            self.identities[args["execution_id"]] = replace(identity, input_hashes=args["inputs"],
                dependency_hashes=args["dependencies"], output_hashes={nid: self.nodes[nid]["payload_hash"]})
        return self.nodes[nid]

    def refresh_ancestors(self, changed):
        for nid in ("cross", "assembly-a", "assembly-b", "root"):
            deps = self.nodes[nid]["payload"]["dependencies"]
            if changed in deps:
                fresh = dict(deps, **{changed: self.nodes[changed]["payload_hash"]})
                self.reseal(nid, dependencies=fresh)
                self.refresh_ancestors(nid)

    def verify(self):
        return verify_proof(self.plan, self.nodes, self.materials, self.identities)

    def reject(self, code):
        with self.assertRaises(ProofError) as caught:
            self.verify()
        self.assertEqual(caught.exception.code, code, caught.exception.as_dict())

    def test_complete_hierarchy_accepts_and_counts_exactly(self):
        receipt = self.verify()
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["coverage_counts"]["source"]["claims"], 3)
        self.assertEqual(receipt["original_sources_verified"], ["src-a", "src-b"])
        self.assertIn("not human review", receipt["semantic_attestation"])

    def test_every_claim_requires_original_sources(self):
        req = copy.deepcopy(self.requirements)
        del req["claims"]["claim-global"]
        with self.assertRaises(ProofError) as caught:
            self.new_plan(source_requirements=req)
        self.assertEqual(caught.exception.code, "MISSING_SOURCE_REQUIREMENT")

    def test_final_claim_cannot_be_removed_only_from_source_phase(self):
        expected = copy.deepcopy(self.expected)
        expected["source"]["claims"].remove("claim-global")
        with self.assertRaises(ProofError) as caught:
            self.new_plan(expected_coverage=expected)
        self.assertEqual(caught.exception.code, "SOURCE_COVERAGE_MISMATCH")

    def test_summary_cannot_be_declared_original_source(self):
        req = copy.deepcopy(self.requirements)
        req["claims"]["claim-global"] = ["claim-a", "claim-b"]
        with self.assertRaises(ProofError) as caught:
            self.new_plan(source_requirements=req)
        self.assertEqual(caught.exception.code, "NOT_ORIGINAL_SOURCE")

    def test_source_crlf_bytes_are_not_normalized(self):
        self.materials["src-a"] = self.materials["src-a"].replace(b"\r\n", b"\n")
        self.reject("STALE_MATERIAL")

    def test_default_original_inventory_cannot_hide_an_unverified_source(self):
        self.materials["src-unread"] = b"Late counterevidence in another supplied source.\n"
        self.plan = self.new_plan(original_source_ids=None)
        self.assertIn("src-unread", self.plan["payload"]["original_source_ids"])
        self.reject("MISSING_ORIGINAL_SOURCE")

    def test_changed_claim_is_not_covered_by_old_proof(self):
        self.materials["claim-a"]["text"] = "All subgroups benefited."
        self.reject("STALE_MATERIAL")

    def test_changed_node_payload_is_detected_without_resealing(self):
        self.nodes["source-a"]["payload"]["reason"] = "Forged reason"
        self.reject("PAYLOAD_TAMPERED")

    def test_resealed_forged_pass_is_not_runtime_output(self):
        self.reseal("source-a", reason="Fabricated approval", attest=False)
        self.reject("UNATTESTED_OUTPUT")

    def test_unresolved_semantic_verdict_fails_without_forcing_pass(self):
        self.reseal("source-a", status="unresolved")
        self.reject("SEMANTIC_REVIEW_FAILED")

    def test_passed_with_issues_fails(self):
        self.reseal("source-a", issues=[{"message": "CI is wrong."}])
        self.reject("SEMANTIC_REVIEW_FAILED")

    def test_missing_original_source_even_with_trusted_pass_fails(self):
        inputs = dict(self.nodes["source-a"]["payload"]["inputs"])
        del inputs["src-a"]
        self.reseal("source-a", inputs=inputs)
        self.reject("NODE_INPUT_SET_MISMATCH")

    def test_original_source_is_required_even_if_bad_plan_omits_its_delivery(self):
        planned = copy.deepcopy(self.plan["payload"]["node_input_requirements"])
        planned["source-a"].remove("src-a")
        self.plan = self.new_plan(node_input_requirements=planned)
        inputs = dict(self.nodes["source-a"]["payload"]["inputs"])
        del inputs["src-a"]
        self.reseal("source-a", inputs=inputs)
        self.reject("MISSING_ORIGINAL_SOURCE")

    def test_claimed_but_undelivered_source_fails(self):
        identity = self.identities["exec-source-a"]
        inputs = dict(identity.input_hashes)
        del inputs["src-a"]
        self.identities[identity.execution_id] = replace(identity, input_hashes=inputs)
        self.reject("INPUT_NOT_DELIVERED")

    def test_cross_group_cannot_ignore_one_members_source_proof(self):
        deps = {"source-a": self.nodes["source-a"]["payload_hash"]}
        self.reseal("cross", dependencies=deps)
        self.reject("MISSING_ORIGINAL_SOURCE")

    def test_cross_group_cannot_use_an_assembly_summary_as_source(self):
        deps = {"assembly-a": self.nodes["assembly-a"]["payload_hash"]}
        self.reseal("cross", dependencies=deps)
        self.reject("INVALID_SOURCE_DEPENDENCY")

    def test_cross_group_proof_hashes_do_not_replace_actual_scientific_premises(self):
        inputs = {mid: digest for mid, digest in self.nodes["cross"]["payload"]["inputs"].items()
                  if mid in {"claim-global", "line-global", "context"}}
        self.reseal("cross", inputs=inputs)
        planned = copy.deepcopy(self.plan["payload"]["node_input_requirements"])
        planned["cross"] = list(inputs)
        self.plan = self.new_plan(node_input_requirements=planned)
        self.reject("MISSING_SCIENTIFIC_PREMISES")

    def test_unread_child_proof_fails(self):
        identity = self.identities["exec-cross"]
        self.identities[identity.execution_id] = replace(identity, dependency_hashes={})
        self.reject("DEPENDENCY_NOT_DELIVERED")

    def test_stale_child_digest_fails(self):
        self.reseal("cross", dependencies={"source-a": "0" * 64, "source-b": self.nodes["source-b"]["payload_hash"]})
        self.reject("STALE_DEPENDENCY")

    def test_actual_target_material_cannot_be_omitted(self):
        inputs = dict(self.nodes["source-a"]["payload"]["inputs"])
        del inputs["claim-a"]
        self.reseal("source-a", inputs=inputs)
        self.reject("NODE_INPUT_SET_MISMATCH")

    def test_required_context_cannot_be_silently_dropped(self):
        inputs = dict(self.nodes["root"]["payload"]["inputs"])
        del inputs["context"]
        self.reseal("root", inputs=inputs)
        self.reject("NODE_INPUT_SET_MISMATCH")

    def test_runtime_delivered_materials_cannot_be_hidden_from_node(self):
        identity = self.identities["exec-root"]
        inputs = dict(identity.input_hashes, **{"claim-a": payload_hash(self.materials["claim-a"])})
        self.identities[identity.execution_id] = replace(identity, input_hashes=inputs)
        self.reject("UNBOUND_RUNTIME_INPUT")

    def test_unknown_material_fails_even_if_runtime_echoes_it(self):
        inputs = dict(self.nodes["source-a"]["payload"]["inputs"], unknown="0" * 64)
        self.reseal("source-a", inputs=inputs)
        self.reject("UNKNOWN_MATERIAL")

    def test_missing_each_coverage_dimension_is_rejected(self):
        for dim in DIMENSIONS:
            with self.subTest(dimension=dim):
                self.setUp()
                cov = copy.deepcopy(self.nodes["assembly-a"]["payload"]["coverage"])
                cov[dim] = []
                self.reseal("assembly-a", coverage=cov)
                self.refresh_ancestors("assembly-a")
                self.reject("MISSING_COVERAGE")

    def test_duplicate_coverage_is_not_averaged_away(self):
        cov = copy.deepcopy(self.nodes["root"]["payload"]["coverage"])
        cov["claims"].append("claim-a")
        inputs = dict(self.nodes["root"]["payload"]["inputs"], **{"claim-a": payload_hash(self.materials["claim-a"])})
        self.reseal("root", coverage=cov, inputs=inputs)
        planned = copy.deepcopy(self.plan["payload"]["node_input_requirements"])
        planned["root"].append("claim-a")
        self.plan = self.new_plan(node_input_requirements=planned)
        self.reject("DUPLICATE_COVERAGE")

    def test_unknown_coverage_fails(self):
        cov = copy.deepcopy(self.nodes["source-a"]["payload"]["coverage"])
        cov["claims"].append("nonexistent-claim")
        self.reseal("source-a", coverage=cov)
        self.reject("UNKNOWN_COVERAGE")

    def test_unknown_dependency_fails(self):
        self.reseal("root", dependencies={"missing-node": "0" * 64})
        self.reject("MISSING_DEPENDENCY")

    def test_cycle_is_rejected_before_digest_checks(self):
        self.reseal("source-a", dependencies={"cross": "0" * 64})
        self.reject("GRAPH_CYCLE")

    def test_orphan_proof_is_rejected(self):
        self.add_node("orphan", "source", coverage(), ["claim-a", "src-a"])
        planned = copy.deepcopy(self.plan["payload"]["node_input_requirements"])
        planned["orphan"] = ["claim-a", "src-a"]
        self.plan = self.new_plan(node_ids=list(planned), node_input_requirements=planned)
        self.reject("ORPHAN_NODE")

    def test_unknown_node_is_rejected_even_when_attested(self):
        self.add_node("unexpected", "source", coverage(), ["claim-a", "src-a"])
        self.reject("UNKNOWN_NODE")

    def test_missing_planned_node_is_rejected(self):
        del self.nodes["assembly-a"]
        self.reject("MISSING_NODE")

    def test_duplicate_nodes_are_rejected(self):
        with self.assertRaises(ProofError) as caught:
            verify_proof(self.plan, list(self.nodes.values()) + [self.nodes["source-a"]], self.materials, self.identities)
        self.assertEqual(caught.exception.code, "DUPLICATE_NODE")

    def test_model_producer_dictionary_is_not_a_runtime_identity(self):
        self.identities["exec-source-a"] = {"context_id": "invented", "role": "source_verifier"}
        self.reject("UNTRUSTED_IDENTITY")

    def test_writer_context_alias_is_rejected(self):
        identity = self.identities["exec-source-a"]
        self.identities[identity.execution_id] = replace(identity, context_id="writer-real")
        self.reject("CONTEXT_ALIAS")

    def test_verifier_cannot_inherit_writer_conversation(self):
        identity = self.identities["exec-source-a"]
        self.identities[identity.execution_id] = replace(identity, ancestor_context_ids=("writer-real",))
        self.reject("WRITER_NOT_INDEPENDENT")

    def test_assembly_cannot_inherit_source_verifier_conversation(self):
        identity = self.identities["exec-root"]
        self.identities[identity.execution_id] = replace(identity, ancestor_context_ids=("context-source-a",))
        self.reject("ASSEMBLY_NOT_INDEPENDENT")

    def test_role_cannot_be_self_declared_by_node(self):
        identity = self.identities["exec-source-a"]
        self.identities[identity.execution_id] = replace(identity, role="writer")
        self.reject("ROLE_MISMATCH")

    def test_wrong_source_encoding_cannot_masquerade_as_raw_bytes(self):
        self.materials["src-a"] = self.materials["src-a"].decode()
        self.plan = self.new_plan()
        self.reject("ORIGINAL_SOURCE_BYTES_REQUIRED")

    def test_empty_reasons_and_unknown_error_fields_are_rejected(self):
        with self.assertRaises(ProofError) as caught:
            seal_node("bad", "source", "exec", {"target": "0" * 64}, {}, coverage(), "passed", " ")
        self.assertEqual(caught.exception.code, "EMPTY_REASON")
        node = self.nodes["source-a"]
        node["payload"]["errors"] = []
        node["payload_hash"] = payload_hash(node["payload"])
        self.reject("INVALID_NODE")

    def test_nonfinite_or_non_string_json_keys_are_not_hashable(self):
        for value in ({"x": float("nan")}, {1: "x"}):
            with self.subTest(value=repr(value)), self.assertRaises(ProofError):
                payload_hash(value)

    def test_plan_and_node_constructors_snapshot_mutable_input(self):
        cov = coverage(claims=["claim-a"])
        node = seal_node("n", "source", "e", {"claim-a": "0" * 64}, {}, cov, "passed", "Source checked.")
        cov["claims"].append("claim-b")
        self.assertEqual(node["payload"]["coverage"]["claims"], ["claim-a"])
        original = self.plan["payload_hash"]
        self.expected["source"]["papers"].append("fake")
        self.assertEqual(self.plan["payload_hash"], original)

    def test_json_roundtrip_is_portable_without_workspace_paths(self):
        receipt = verify_proof(json.loads(json.dumps(self.plan)), json.loads(json.dumps(self.nodes)),
                               self.materials, self.identities)
        self.assertEqual(receipt["status"], "passed")


class CompactDependencyReceiptTests(unittest.TestCase):
    """All attestations below are explicit structural fixtures, never model QA."""
    def setUp(self):
        self.h = HierarchicalProofTests()
        self.h.setUp()
        self.h.plan = self.h.new_plan(compact_dependency_nodes=['cross', 'assembly-a', 'assembly-b', 'root'])
        for nid, node in self.h.nodes.items():
            eid = node['payload']['execution_id']
            receipts = {dep: payload_hash(dependency_receipt(self.h.nodes[dep])) for dep in node['payload']['dependencies']}
            self.h.identities[eid] = replace(self.h.identities[eid], delivered_dependency_receipt_hashes=receipts)

    def prepare(self, roots=('cross',)):
        return prepare_dependency_receipts(self.h.plan, self.h.nodes, self.h.materials, self.h.identities, list(roots))

    def test_compact_gate_and_preflight_keep_original_scientific_contract(self):
        self.assertEqual(self.h.verify()['status'], 'passed')
        receipt = self.prepare()['cross']
        child = self.h.nodes['cross']
        for key in ('node_id', 'kind', 'status', 'reason', 'issues', 'coverage'):
            self.assertEqual(receipt[key], child['payload'][key])
        self.assertEqual(receipt['proof_payload_hash'], child['payload_hash'])
        self.assertNotIn('inputs', receipt)
        self.assertNotIn('dependencies', receipt)

    def test_partial_closure_is_not_review_publication_approval(self):
        result = verify_dependency_closure(self.h.plan, self.h.nodes, self.h.materials, self.h.identities, ['source-a'])
        self.assertEqual(result['status'], 'dependency_closure_validated')
        self.assertFalse(result['publication_verified'])
        self.assertEqual(set(result['node_hashes']), {'source-a'})

    def test_missing_complete_ancestry_is_rejected(self):
        del self.h.nodes['source-a']
        with self.assertRaises(ProofError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.code, 'MISSING_DEPENDENCY')

    def test_receipt_needs_actual_trusted_child_output(self):
        del self.h.identities['exec-source-a']
        with self.assertRaises(ProofError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.code, 'UNTRUSTED_IDENTITY')

    def test_receipt_checks_current_original_bytes(self):
        self.h.materials['src-a'] += b' late adverse result'
        with self.assertRaises(ProofError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.code, 'STALE_MATERIAL')

    def test_unresolved_child_cannot_be_projected_for_delivery(self):
        self.h.reseal('source-a', status='unresolved')
        with self.assertRaises(ProofError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.code, 'SEMANTIC_REVIEW_FAILED')

    def test_forged_passed_child_is_not_runtime_attestation(self):
        self.h.reseal('source-a', reason='Fake changed approval', attest=False)
        with self.assertRaises(ProofError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.code, 'UNATTESTED_OUTPUT')

    def test_compact_mode_cannot_omit_receipt_delivery_hash(self):
        self.h.identities['exec-cross'] = replace(self.h.identities['exec-cross'], delivered_dependency_receipt_hashes={})
        self.h.reject('DEPENDENCY_RECEIPT_NOT_DELIVERED')

    def test_any_receipt_field_change_is_rejected(self):
        for field, value in [('reason','Changed'), ('coverage',coverage()), ('status','unresolved'),
                             ('issues',[{'message':'Changed'}]), ('kind','assembly'),
                             ('proof_payload_hash','f'*64), ('schema','dependency-proof-receipt/999')]:
            with self.subTest(field=field):
                original = self.h.identities['exec-cross']
                receipt = dependency_receipt(self.h.nodes['source-a'])
                receipt[field] = value
                hashes = dict(original.delivered_dependency_receipt_hashes)
                hashes['source-a'] = payload_hash(receipt)
                self.h.identities['exec-cross'] = replace(original, delivered_dependency_receipt_hashes=hashes)
                self.h.reject('DEPENDENCY_RECEIPT_MISMATCH')
                self.h.identities['exec-cross'] = original

    def test_extra_receipt_or_wrong_child_pairing_is_rejected(self):
        original = self.h.identities['exec-cross']
        hashes = dict(original.delivered_dependency_receipt_hashes)
        hashes['unplanned'] = 'f'*64
        self.h.identities['exec-cross'] = replace(original, delivered_dependency_receipt_hashes=hashes)
        self.h.reject('DEPENDENCY_RECEIPT_NOT_DELIVERED')

    def test_legacy_plan_cannot_silently_claim_compact_delivery(self):
        self.h.plan = self.h.new_plan()
        self.h.reject('UNDECLARED_DEPENDENCY_RECEIPT')

    def test_preflight_keeps_assembly_source_independence(self):
        self.h.identities['exec-assembly-a'] = replace(self.h.identities['exec-assembly-a'],
            ancestor_context_ids=('context-source-a',))
        with self.assertRaises(ProofError) as caught:
            self.prepare(('assembly-a',))
        self.assertEqual(caught.exception.code, 'ASSEMBLY_NOT_INDEPENDENT')

    def test_preflight_does_not_replace_selected_scientific_materials(self):
        self.h.materials['claim-a']['text'] = 'Every subgroup benefits.'
        with self.assertRaises(ProofError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.code, 'STALE_MATERIAL')


if __name__ == "__main__":
    unittest.main()
