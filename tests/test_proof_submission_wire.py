import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'skills/literature-review/scripts/runtime'))
from litreview_core.hierarchical_proof import DIMENSIONS
from litreview_core.proof_submission_wire import alias_proof_packet, decode_proof_submission


class ProofSubmissionWireTests(unittest.TestCase):
    def setUp(self):
        self.coverage = {dim: [] for dim in DIMENSIONS}
        self.coverage.update(claims=['section/claim'], obligations=['paper/finding/obligation'], lines=['line/1'])
        self.packet = {'coverage': self.coverage, 'material_hashes': {'source': 'sha'},
                       'materials': {'source': 'u1 is literal source text'},
                       'dependency_proofs': {'dep': {'reason': 'Literal section/claim'}}}

    def test_materials_hashes_and_original_packet_unchanged(self):
        original = copy.deepcopy(self.packet)
        wire, aliases = alias_proof_packet(self.packet)
        self.assertEqual(original, self.packet)
        for field in ('materials', 'material_hashes', 'dependency_proofs'):
            self.assertEqual(wire[field], original[field])
        self.assertEqual(set(aliases.values()), {'section/claim', 'paper/finding/obligation', 'line/1'})
        self.assertEqual(wire['responsibility_encoding'], 'proof-unit-aliases/1')

    def test_full_submission_roundtrip_preserves_reasons_and_negative_issues(self):
        wire, aliases = alias_proof_packet(self.packet)
        inverse = {v: k for k, v in aliases.items()}
        value = {'checked': wire['coverage'], 'verdicts': [
            {'unit_id': inverse['section/claim'], 'verdict': 'needs_revision', 'reason': 'u1 stays literal'},
            {'unit_id': inverse['paper/finding/obligation'], 'verdict': 'passed', 'reason': 'Actual evidence checked'}],
            'status': 'needs_revision', 'reason': 'Scoped uncertainty',
            'issues': [{'unit_ids': [inverse['section/claim'], 'source'], 'description': 'Wrong quote', 'correction': 'Correct it'}]}
        original = copy.deepcopy(value)
        decoded = decode_proof_submission(value, aliases)
        self.assertEqual(value, original)
        self.assertEqual(decoded['checked'], self.coverage)
        self.assertEqual(decoded['verdicts'][0]['unit_id'], 'section/claim')
        self.assertEqual(decoded['verdicts'][0]['reason'], 'u1 stays literal')
        self.assertEqual(decoded['issues'][0]['unit_ids'], ['section/claim', 'source'])
        self.assertEqual(decoded['status'], 'needs_revision')

    def test_unknown_and_mixed_duplicates_not_silently_removed(self):
        _, aliases = alias_proof_packet(self.packet)
        alias = next(k for k,v in aliases.items() if v == 'section/claim')
        value = {'checked': {'claims': [alias, 'section/claim', 'foreign']}, 'verdicts': [], 'issues': []}
        self.assertEqual(decode_proof_submission(value, aliases)['checked']['claims'],
                         ['section/claim', 'section/claim', 'foreign'])

    def test_alias_cannot_shadow_canonical_id_or_material_id(self):
        self.packet['coverage']['claims'] = ['u1']
        self.packet['material_hashes']['_u1'] = 'sha2'
        wire, aliases = alias_proof_packet(self.packet)
        self.assertTrue(all(k.startswith('__u') for k in aliases))
        self.assertEqual(decode_proof_submission({'checked':wire['coverage'], 'verdicts':[], 'issues':[]}, aliases)['checked'],
                         self.packet['coverage'])

    def test_empty_integration_scope(self):
        self.packet['coverage'] = {dim: [] for dim in DIMENSIONS}
        wire, aliases = alias_proof_packet(self.packet)
        self.assertEqual(aliases, {})
        self.assertEqual(wire['coverage'], self.packet['coverage'])


if __name__ == '__main__':
    unittest.main()
