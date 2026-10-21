"""Offline native draft-wire roundtrip and complete diagnostic adversaries."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/literature-review/scripts/runtime'))
import test_proof_planner as planner_fixture
from litreview_core.draft_wire import project_draft_packet, restore_draft_packet
from litreview_core.draft_worker import draft_worker
from litreview_core.review_artifacts import DraftInventoryError, draft_packet, inference_packet, validate_draft
from litreview_core.task_store import TaskStore, canonical


class DraftWireTests(unittest.TestCase):
    def setUp(self):
        fixture = planner_fixture.ProofPlannerTests()
        fixture.setUp()
        self.fixture = fixture
        self.direct = draft_packet('paper_card', [fixture.packets[0]], [fixture.records[0]], fixture.questions)
        self.inference = inference_packet([fixture.comparison], fixture.packets, fixture.records, fixture.questions)

    def test_fulltext_and_metadata_roundtrip_canonical_exact(self):
        for packet in (self.direct, self.inference):
            before = copy.deepcopy(packet)
            wire = project_draft_packet(packet)
            restored = restore_draft_packet(json.loads(json.dumps(wire, ensure_ascii=False)))
            self.assertEqual(canonical(packet), canonical(restored))
            self.assertEqual(packet, before)
            self.assertEqual(wire['canonical_sha256'], sha256(canonical(packet)).hexdigest())
        self.assertIn('\r\n', next(iter(restore_draft_packet(project_draft_packet(self.direct))['sources'].values()))['text'])

    def test_paper_hash_is_not_repeated_for_every_part(self):
        wire = project_draft_packet(self.direct)
        version = self.direct['sources']['paper-0/p0001']['source_sha256']
        self.assertEqual(canonical(wire['source_encoding']).decode().count(version), 1)
        self.assertLess(len(canonical(wire)), len(canonical(self.direct)))

    def test_synthesis_source_inventory_is_exact_premise_and_obligation_union(self):
        expected = {ref for c in self.fixture.comparison['claims'] for ref in c['evidence_refs']}
        expected.update(ref for o in self.inference['obligations'] for ref in o['source_refs'])
        self.assertEqual(set(self.inference['sources']), expected)
        self.assertNotIn('paper-0/p0001', self.inference['sources'])
        self.assertNotIn('text', next(iter(self.inference['sources'].values())))
        # Full original source packets/reader records have not been changed.
        self.assertEqual(len(self.fixture.packets[0]['parts']), 3)
        self.assertEqual(len(self.fixture.records[0]['observations']), 3)

    def test_synthesis_uses_direct_claims_while_leaf_counterevidence_remains_intact(self):
        comparison = copy.deepcopy(self.fixture.comparison)
        for claim in comparison['claims']:
            claim['evidence_refs'] = [ref for ref in claim['evidence_refs'] if ref.endswith('p0002')]
        packet = inference_packet([comparison], self.fixture.packets, self.fixture.records, self.fixture.questions)
        for obligation in packet['obligations']:
            self.assertTrue(set(obligation['source_refs']) <= set(packet['sources']))
        self.assertNotIn('paper-0/p0003', packet['sources'])
        self.assertEqual(len(packet['obligations']), len(comparison['claims']))
        self.assertTrue(all(o['kind'] == 'premise_retention' for o in packet['obligations']))
        leaf = draft_packet('comparison', self.fixture.packets, self.fixture.records, self.fixture.questions)
        self.assertIn('paper-0/p0003', leaf['sources'])
        self.assertTrue(any('paper-0/p0003' in o['source_refs'] for o in leaf['obligations']))
        # This synthetic mutated premise has no scientific approval. Planner
        # must still replay its original leaf evidence and reject tampering.

    def test_unknown_source_reference_is_rejected(self):
        comparison = copy.deepcopy(self.fixture.comparison)
        comparison['claims'][0]['evidence_refs'].append('missing/p0001')
        with self.assertRaises(ValueError):
            inference_packet([comparison], self.fixture.packets, self.fixture.records, self.fixture.questions)

    def test_tampered_value_or_hash_fails_restore(self):
        for mutation in ('row', 'hash', 'premise'):
            wire = project_draft_packet(self.inference)
            if mutation == 'row':
                wire['source_encoding']['tables'][0]['rows'][0][-1] = 'tampered-value'
            elif mutation == 'hash':
                wire['canonical_sha256'] = '0' * 64
            else:
                wire['packet']['premises'][0]['claims'][0]['text'] = 'Changed science'
            with self.assertRaises(ValueError):
                restore_draft_packet(wire)

    def test_duplicate_or_malformed_rows_are_rejected(self):
        for mutation in ('duplicate', 'index', 'columns'):
            wire = project_draft_packet(self.direct)
            table = wire['source_encoding']['tables'][0]
            if mutation == 'duplicate':
                table['rows'].append(table['rows'][0])
            elif mutation == 'index':
                table['rows'][0][0] = 99999
            else:
                table['columns'].append(table['columns'][-1])
            with self.assertRaises(ValueError):
                restore_draft_packet(wire)

    def test_extra_source_fields_preserved_losslessly(self):
        packet = copy.deepcopy(self.direct)
        packet['sources']['paper-0/p0001']['future_extra'] = {'units': '機械測試', 'values': [1, None, False]}
        self.assertEqual(restore_draft_packet(project_draft_packet(packet)), packet)

    def test_empty_claims_exposes_all_three_inventory_gaps_together(self):
        packet = draft_packet('comparison', self.fixture.packets, self.fixture.records, self.fixture.questions,
                              dimensions=['effect', 'conditions'])
        with self.assertRaises(DraftInventoryError) as caught:
            validate_draft(packet, {'claims': [], 'retention': [], 'cells': []}, execution_id='writer')
        details = caught.exception.details
        self.assertEqual(set(details['questions']['missing']), {'effect', 'conditions'})
        self.assertEqual(set(details['retention']['missing']), {o['id'] for o in packet['obligations']})
        self.assertEqual(len(details['cells']['missing']), 4)
        self.assertTrue(details['schema_errors'])

    def test_unknown_duplicate_and_reference_gaps_are_all_reported(self):
        packet = draft_packet('comparison', self.fixture.packets, self.fixture.records, self.fixture.questions,
                              dimensions=['effect', 'conditions'])
        claim = copy.deepcopy(self.fixture.comparison['claims'][0])
        claim['question_ids'] = ['foreign-question']
        data = {'claims': [claim], 'retention': [{'obligation_id': 'foreign-obligation', 'status': 'included',
                    'claim_ids': ['missing-claim'], 'reason': 'No fake fill.'}] * 2,
                'cells': [{'paper_id': 'foreign-paper', 'dimension': 'foreign-dimension', 'claim_ids': ['missing-claim']}]}
        with self.assertRaises(DraftInventoryError) as caught:
            validate_draft(packet, data, execution_id='writer')
        info = caught.exception.details
        self.assertEqual(info['questions']['unknown'], ['foreign-question'])
        self.assertEqual(info['retention']['duplicates'], ['foreign-obligation'])
        self.assertEqual(info['cells']['unknown'], [('foreign-paper', 'foreign-dimension')])
        self.assertTrue(info['unknown_claim_references'])

    def test_real_worker_sends_only_projection_but_accepts_exact_canonical_packet(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TaskStore(temp)
            ticket = store.create('writer', self.direct)
            identity = SimpleNamespace(role='writer', context_id='actual-writer')
            worker = draft_worker(store, identity, ticket)
            self.assertEqual(worker.inputs['draft-packet.json']['schema'], 'review-draft-wire/1')
            from litreview_core.draft_submission_wire import alias_obligations
            aliased,aliases=alias_obligations(self.direct)
            self.assertEqual(restore_draft_packet(worker.inputs['draft-packet.json']), aliased)
            value = {key: self.fixture.cards[0][key] for key in ('claims', 'retention', 'cells')}
            inverse={original:alias for alias,original in aliases.items()}
            value['retention_groups']=[{'obligation_ids':[inverse[r['obligation_id']]],
                'status':r['status'],'claim_ids':r['claim_ids'],'reason':r['reason']} for r in value.pop('retention')]
            receipt = worker.accept({'data':value}, identity)
            section = store.get(receipt['output_hash'])
            self.assertEqual(section['packet_sha256'], sha256(canonical(self.direct)).hexdigest())
            self.assertEqual(section['verification_status'], 'unverified')

    def test_typed_tool_schema_reports_all_missing_inventories_before_min_length_error(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TaskStore(temp)
            ticket = store.create('writer', self.direct)
            worker = draft_worker(store, SimpleNamespace(role='writer', context_id='actual-writer'), ticket)
            with self.assertRaises(ValueError) as caught:
                worker.accept({'data': {'claims': [], 'retention_groups': [], 'cells': []}},
                              SimpleNamespace(context_id='actual-writer'))
            self.assertIn('questions', str(caught.exception))
            self.assertIn('retention', str(caught.exception))
            self.assertIn('schema_errors', str(caught.exception))
            self.assertEqual(store.status()[0]['status'], 'running')


if __name__ == '__main__':
    unittest.main()
