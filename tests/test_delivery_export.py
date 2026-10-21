"""Offline byte-preservation and gate adversaries, never paid/model approvals."""
import copy
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/literature-review/scripts/runtime'))
import test_proof_planner as fixtures
from litreview_core import delivery_export
from litreview_core.delivery_export import DeliveryError, export_review, save_review_attempt
from litreview_core.hierarchical_proof import ProofError, RuntimeIdentity, seal_node, dependency_receipt, payload_hash


class DeliveryExportTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ProofPlannerTests()
        fixture.setUp()
        self.fixture = fixture
        bundle = fixture.compile()
        nodes, identities = {}, {}
        for eid in bundle['plan']['payload']['writer_execution_ids']:
            identities[eid] = RuntimeIdentity(eid, 'context-' + eid, 'writer', {})
        for nid, spec in bundle['node_specs'].items():
            deps = {dep: nodes[dep]['payload_hash'] for dep in spec['dependencies']}
            eid = 'offline-test-' + nid
            node = seal_node(nid, spec['kind'], eid, spec['inputs'], deps, spec['coverage'],
                'passed', 'Synthetic offline gate fixture, not an actual model approval.')
            nodes[nid] = node
            identities[eid] = RuntimeIdentity(eid, 'context-' + eid, spec['role'], spec['inputs'],
                                            deps, {nid: node['payload_hash']},
                delivered_dependency_receipt_hashes={dep:payload_hash(dependency_receipt(nodes[dep])) for dep in deps})
        self.result = {'bundle': bundle, 'nodes': nodes, 'identities': identities,
                       'records': fixture.records, 'sections': fixture.sections,
                       'gate': {'status': 'caller-supplied-untrusted-cache'}}
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / 'delivery'

    def test_fresh_gate_exact_review_and_every_file_hash(self):
        receipt = export_review(self.result, self.out)
        self.assertTrue(receipt['publication_verified'])
        self.assertEqual(receipt['gate']['status'], 'passed')
        raw = self.result['bundle']['materials']['delivery/render']['text'].encode('utf-8')
        self.assertEqual((self.out / 'review.md').read_bytes(), raw)
        manifest = json.loads((self.out / 'manifest.json').read_bytes())
        for path, entry in manifest['files'].items():
            actual = (self.out / path).read_bytes()
            self.assertEqual(sha256(actual).hexdigest(), entry['sha256'])
            self.assertEqual(len(actual), entry['size_bytes'])

    def test_original_crlf_sources_and_exact_span_offsets(self):
        export_review(self.result, self.out)
        index = json.loads((self.out / 'source-spans.json').read_bytes())
        for packet in self.fixture.packets:
            info = index['sources'][packet['paper_id']]
            raw = (self.out / info['path']).read_bytes()
            self.assertIn(b'\r\n', raw)
            self.assertEqual(raw, b''.join(p['text'].encode() for p in packet['parts']))
            for part in packet['parts']:
                span = index['parts'][packet['paper_id'] + '/' + part['part_id']]
                self.assertEqual(raw[span['start_byte']:span['end_byte']], part['text'].encode())
        for evidence in index['reader_evidence'].values():
            raw = (self.out / evidence['source_path']).read_bytes()
            self.assertEqual(sha256(raw[evidence['start_byte']:evidence['end_byte']]).hexdigest(),
                             evidence['quote_sha256'])

    def test_main_is_exact_root_projection_with_complete_line_mapping(self):
        export_review(self.result, self.out)
        bundle = self.result['bundle']
        text = ''.join(bundle['rendered_sections'][sid]['text'] + '\n\n' for sid in bundle['root_section_ids'])
        self.assertEqual((self.out / 'main-review.md').read_bytes(), text.encode())
        mapping = json.loads((self.out / 'main-review-lines.json').read_bytes())
        self.assertEqual(len(mapping['lines']), sum(bool(s.strip()) for s in text.splitlines()))
        for line in mapping['lines']:
            self.assertEqual(text[line['start_char']:line['end_char']], line['text'])

    def test_compared_cells_project_only_exact_reviewed_claims(self):
        export_review(self.result, self.out)
        rows = list(csv.DictReader(io.StringIO((self.out / 'comparison-cells.csv').read_text(encoding='utf-8'))))
        self.assertEqual(len(rows), len(self.fixture.comparison['cells']))
        by_local = {claim['local_id']: claim for claim in self.fixture.comparison['claims']}
        for row, cell in zip(rows, self.fixture.comparison['cells']):
            self.assertEqual(json.loads(row['paper_id_json']), cell['paper_id'])
            self.assertEqual(json.loads(row['dimension_json']), cell['dimension'])
            for mapped in json.loads(row['claims_json']):
                local = mapped['claim_id'].split('/')[-1]
                self.assertEqual(mapped['text'], by_local[local]['text'])
                self.assertEqual(mapped['source_refs'], by_local[local]['evidence_refs'])

    def test_missing_node_cannot_use_cached_pass_or_create_delivery(self):
        self.result['gate'] = {'status': 'passed', 'publication_verified': True}
        self.result['nodes'].pop(next(iter(self.result['nodes'])))
        with self.assertRaises(ProofError):
            export_review(self.result, self.out)
        self.assertFalse(self.out.exists())

    def test_readable_card_collection_preserves_exact_reviewed_bytes_and_offsets(self):
        export_review(self.result,self.out)
        text=(self.out/'evidence-cards.md').read_text(encoding='utf-8')
        index=json.loads((self.out/'evidence-cards-index.json').read_bytes())
        expected=[s for s in self.fixture.sections if s['kind']=='paper_card']
        self.assertEqual(len(index['cards']),len(expected))
        for item,section in zip(index['cards'],expected):
            original=self.result['bundle']['rendered_sections'][section['section_id']]['text']
            self.assertEqual(text[item['start_char']:item['end_char']],original)
            self.assertEqual(item['paper_id'],section['paper_ids'][0])
        readme=(self.out/'README.md').read_text(encoding='utf-8')
        for path in ('main-review.md','evidence-cards.md','comparison-table.md'):
            self.assertIn(']('+path+')',readme)

    def test_readable_comparison_table_keeps_cell_bindings_and_original_source_links(self):
        export_review(self.result,self.out)
        text=(self.out/'comparison-table.md').read_text(encoding='utf-8')
        mapping=json.loads((self.out/'comparison-table-map.json').read_bytes())
        self.assertEqual(len(mapping['cells']),len(self.fixture.comparison['cells']))
        expected={(c['paper_id'],c['dimension']):c['claim_ids'] for c in self.fixture.comparison['cells']}
        sid=self.fixture.comparison['section_id']
        for cell in mapping['cells']:
            self.assertEqual(cell['section_id'],sid)
            self.assertEqual(cell['claim_ids'],[sid+'/'+cid for cid in expected[(cell['paper_id'],cell['dimension'])]])
        sources=json.loads((self.out/'source-spans.json').read_bytes())
        for claim in self.fixture.comparison['claims']:
            self.assertIn(delivery_export.escape_markdown(claim['text']),text)
            for ref in claim['evidence_refs']:
                path=sources['parts'][ref]['source_path']
                self.assertIn(']('+path+')',text)
                self.assertTrue((self.out/path).is_file())

    def test_mutated_source_or_render_rejected_before_write(self):
        self.result['bundle']['materials']['original/paper-0'] += b'Changed original'
        with self.assertRaises(ProofError):
            export_review(self.result, self.out)
        self.assertFalse(self.out.exists())

    def test_failed_semantic_verdict_is_preserved_in_attempt(self):
        root_id = self.result['bundle']['root_node_id']
        old = self.result['nodes'][root_id]['payload']
        failed = seal_node(root_id, 'root', old['execution_id'], old['inputs'], old['dependencies'],
            old['coverage'], 'unresolved', 'Population overlap remains unresolved.',
            [{'unit_ids': ['review/scope'], 'description': 'Unknown population independence', 'correction': 'Inspect original cohorts'}])
        self.result['nodes'][root_id] = failed
        identity = self.result['identities'][old['execution_id']]
        self.result['identities'][old['execution_id']] = RuntimeIdentity(
            identity.execution_id, identity.context_id, identity.role, identity.input_hashes,
            identity.dependency_hashes, {root_id: failed['payload_hash']})
        with self.assertRaises(ProofError):
            export_review(self.result, self.out)
        saved = save_review_attempt(self.result, self.out)
        self.assertFalse(saved['publication_verified'])
        self.assertEqual(saved['gate']['error']['code'], 'SEMANTIC_REVIEW_FAILED')
        archived = json.loads((self.out / 'proof/nodes.json').read_bytes())
        self.assertEqual(archived[root_id]['payload']['status'], 'unresolved')
        self.assertFalse((self.out / 'review.md').exists())
        self.assertTrue((self.out / 'draft-review.md').exists())
        for name in ('evidence-cards.md','comparison-table.md'):
            self.assertFalse((self.out/name).exists())
            self.assertTrue((self.out/('draft-'+name)).exists())
        self.assertIn('未通過完整查核',(self.out/'README.md').read_text(encoding='utf-8'))

    def test_incomplete_preplan_attempt_is_saved_without_final_text(self):
        saved = save_review_attempt({'bundle': None, 'nodes': {}, 'identities': {},
                                     'records': [self.fixture.records[0]]}, self.out)
        self.assertFalse(saved['publication_verified'])
        self.assertEqual(saved['gate']['error']['code'], 'PROOF_NOT_COMPILED')
        self.assertTrue((self.out / 'partial-artifacts.json').is_file())
        self.assertFalse((self.out / 'review.md').exists())

    def test_corrupt_projection_still_archives_failed_bundle_and_raw_bytes(self):
        self.result['bundle']['materials']['delivery/render']['text'] += 'Unreviewed line'
        saved = save_review_attempt(self.result, self.out)
        self.assertFalse(saved['publication_verified'])
        self.assertTrue((self.out / 'projection-error.json').is_file())
        self.assertTrue((self.out / 'materials/index.json').is_file())
        self.assertFalse((self.out / 'draft-review.md').exists())

    def test_empty_partial_bundle_is_supported(self):
        saved = save_review_attempt({'bundle': {'materials': {}}}, self.out)
        self.assertEqual(saved['gate']['error']['code'], 'PROOF_BUNDLE_INCOMPLETE')
        self.assertFalse(saved['publication_verified'])

    def test_identity_json_is_rejected_as_runtime_trust(self):
        key = next(iter(self.result['identities']))
        self.result['identities'][key] = {'execution_id': key}
        with self.assertRaises(DeliveryError):
            export_review(self.result, self.out)
        self.assertFalse(self.out.exists())

    def test_existing_output_is_not_overwritten(self):
        self.out.mkdir()
        marker = self.out / 'raw.txt'
        marker.write_bytes(b'existing data')
        with self.assertRaises(FileExistsError):
            export_review(self.result, self.out)
        self.assertEqual(marker.read_bytes(), b'existing data')

    def test_snapshot_export_does_not_mutate_research_or_runtime_identity(self):
        before = copy.deepcopy({key: value for key, value in self.result.items() if key != 'identities'})
        runtime = self.result['identities'].copy()
        export_review(self.result, self.out)
        self.assertEqual(before, {key: value for key, value in self.result.items() if key != 'identities'})
        self.assertEqual(runtime, self.result['identities'])

    def test_written_identity_ledger_is_explicitly_unauthenticated(self):
        export_review(self.result, self.out)
        ledger = json.loads((self.out / 'proof/runtime-identities.json').read_bytes())
        self.assertIn('never automatically trusted', ledger['trust'])
        self.assertEqual(set(ledger['identities']), set(self.result['identities']))

    def test_write_failure_cannot_leave_success_manifest(self):
        original = Path.open
        def failing(path, *args, **kwargs):
            if path.name == 'review.md' and args and args[0] == 'xb':
                raise OSError('Synthetic offline write failure')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', failing):
            with self.assertRaises(OSError):
                export_review(self.result, self.out)
        self.assertFalse((self.out / 'manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
