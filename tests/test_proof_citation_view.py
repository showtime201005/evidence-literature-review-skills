"""Adversarial deterministic views; no model approval, API or added evidence."""
import copy
from hashlib import sha256
from pathlib import Path
import sys
import unittest
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/literature-review/scripts/runtime'))
sys.path.insert(0,str(ROOT/'tests'))
from litreview_core.hierarchical_proof import DIMENSIONS,payload_hash
from litreview_core.proof_citation_view import attach_citation_view,build_citation_view
from litreview_core.proof_planner import node_payload
from litreview_core.proof_submission_wire import alias_proof_packet
import test_proof_planner as planner_fixtures


class CitationViewTests(unittest.TestCase):
    def setUp(self):
        self.a='來源在評估前凍結。\r\n帳本記錄內容摘要。\r\n\r\n'
        self.b='The schedule is monthly; a limitation persists.\r\n'
        raw=(self.a+self.b).encode('utf-8')
        self.source_hash=sha256(raw).hexdigest()
        self.materials={'original/paper':raw,
            'claim/S%2Fc1':{'claim_id':'S/c1','text':'Digest recording preceded freezing.',
                           'evidence_refs':['paper/p1']},
            'claim/S%2Fc2':{'claim_id':'S/c2','text':'The schedule is monthly.',
                           'evidence_refs':['paper/p2']},
            'o1':{'section_id':'S','definition':{'id':'o1','kind':'applicability'},
                  'original_finding':{'text':'Original narrow qualification.'},
                  'disposition':{'status':'included','claim_ids':['c1'],
                                 'reason':'Runtime must inspect only the named prose.'}},
            'reader/paper':{'evidence':[{'part_id':'p2','quote':self.b}],
                            'counterevidence':['A source qualification outside the declared first locator.']}}
        for part_id,start,text in [('p1',0,self.a),('p2',len(self.a.encode('utf-8')),self.b)]:
            self.materials['locator/'+quote('paper/'+part_id,safe='')]={
                'paper_id':'paper','part_id':part_id,'start_byte':start,
                'end_byte':start+len(text.encode('utf-8')),'source_sha256':self.source_hash,
                'text_sha256':sha256(text.encode('utf-8')).hexdigest()}
        self.coverage={dim:[] for dim in DIMENSIONS}
        self.coverage.update(claims=['S/c1','S/c2'],obligations=['o1'])

    def packet(self):
        return {'schema':'hierarchical-proof-task/1','node_id':'source','kind':'source',
                'coverage':copy.deepcopy(self.coverage),
                'materials':{mid:value.decode('utf-8') if isinstance(value,bytes) else copy.deepcopy(value)
                             for mid,value in self.materials.items()},
                'material_hashes':{mid:payload_hash(value) for mid,value in self.materials.items()},
                'required_dependency_ids':[],'dependency_proofs':{}}

    def test_exact_declared_complete_parts_crlf_and_unicode_no_invented_support(self):
        view=build_citation_view(self.packet())
        row=view['claim_rows'][0]
        self.assertEqual(row['text'],'Digest recording preceded freezing.')
        self.assertEqual(row['declared_evidence_refs'],['paper/p1'])
        self.assertEqual([part['ref'] for part in row['declared_parts']],['paper/p1'])
        self.assertEqual(row['declared_parts'][0]['text'],self.a)
        self.assertNotIn(self.b,str(row))
        self.assertNotIn('monthly',str(row))
        self.assertNotIn('expected_verdict',str(view))
        # This is not a semantic approval of the deliberately stronger claim.

    def test_named_obligation_prose_excludes_other_delivered_claims(self):
        row=build_citation_view(self.packet())['obligation_rows'][0]
        self.assertEqual([claim['claim_id'] for claim in row['named_claims']],['S/c1'])
        self.assertNotIn('S/c2',str(row['named_claims']))
        self.assertEqual(row['original_finding'],self.materials['o1']['original_finding'])

    def test_complete_source_duty_lists_actual_complete_card_claims_without_fake_disposition(self):
        packet=self.packet();packet['coverage']['claims']=[]
        packet['materials']['o1']['definition']={'kind':'full_source_review','claim_ids':['S/c1','S/c2']}
        packet['materials']['o1']['disposition']=None
        packet['material_hashes']['o1']=payload_hash(packet['materials']['o1'])
        view=build_citation_view(packet)
        self.assertEqual([row['claim_id'] for row in view['claim_rows']],['S/c1','S/c2'])
        self.assertIsNone(view['obligation_rows'][0]['disposition'])
        self.assertEqual(view['obligation_rows'][0]['named_claims'],[])

    def test_canonical_materials_full_counterevidence_coverage_and_input_unchanged(self):
        packet=self.packet();before=copy.deepcopy(packet)
        projected=attach_citation_view(packet)
        self.assertEqual(packet,before)
        for key in ('materials','material_hashes','coverage','dependency_proofs'):
            self.assertEqual(projected[key],before[key])
        self.assertIn(self.b,projected['materials']['original/paper'])
        self.assertEqual(projected['materials']['reader/paper'],before['materials']['reader/paper'])
        view=projected['citation_view'];digest=view.pop('view_sha256')
        self.assertEqual(digest,payload_hash(view))
        self.assertEqual(view['base_task_sha256'],payload_hash(packet))
        self.assertEqual(build_citation_view(packet),build_citation_view(packet))

    def test_stale_delivered_source_and_material_hash_rejected(self):
        packet=self.packet();packet['materials']['original/paper']+='tampered'
        with self.assertRaisesRegex(ValueError,'material hash'):
            build_citation_view(packet)
        packet=self.packet();packet['materials']['claim/S%2Fc1']['text']='changed'
        with self.assertRaisesRegex(ValueError,'material hash'):
            build_citation_view(packet)

    def test_source_version_text_hash_and_out_of_range_locator_rejected(self):
        key='locator/'+quote('paper/p1',safe='')
        for kind in ('source_version','text_hash','negative','beyond','boolean'):
            packet=self.packet();locator=packet['materials'][key]
            if kind=='source_version':locator['source_sha256']='0'*64
            elif kind=='text_hash':locator['text_sha256']='1'*64
            elif kind=='negative':locator['start_byte']=-1
            elif kind=='beyond':locator['end_byte']=10**6
            else:locator['start_byte']=False
            packet['material_hashes'][key]=payload_hash(locator)
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                build_citation_view(packet)

    def test_utf8_mid_character_cut_rejected_even_if_slice_hash_matches(self):
        packet=self.packet();key='locator/'+quote('paper/p1',safe='')
        locator=packet['materials'][key];locator['start_byte']=1
        raw=packet['materials']['original/paper'].encode('utf-8')
        locator['text_sha256']=sha256(raw[1:locator['end_byte']]).hexdigest()
        packet['material_hashes'][key]=payload_hash(locator)
        with self.assertRaisesRegex(ValueError,'UTF-8'):
            build_citation_view(packet)

    def test_missing_locator_cannot_be_repaired_from_reader_quote(self):
        packet=self.packet();key='locator/'+quote('paper/p1',safe='')
        del packet['materials'][key];del packet['material_hashes'][key]
        with self.assertRaisesRegex(ValueError,'lacks a delivered locator'):
            build_citation_view(packet)

    def test_cross_group_original_absent_is_explicit_not_a_source_quote(self):
        packet=self.packet();packet['kind']='cross_group'
        for key in list(packet['materials']):
            if key.startswith(('original/','locator/')):
                del packet['materials'][key];del packet['material_hashes'][key]
        view=build_citation_view(packet)
        self.assertTrue(all(part['availability']=='original_not_delivered'
            and part['text'] is None for row in view['claim_rows'] for part in row['declared_parts']))
        self.assertEqual(packet['materials']['reader/paper']['evidence'][0]['quote'],self.b)

    def test_missing_named_claim_is_not_substituted_with_another_card_claim(self):
        packet=self.packet();key='claim/S%2Fc1'
        del packet['materials'][key];del packet['material_hashes'][key]
        row=build_citation_view(packet)['obligation_rows'][0]
        self.assertEqual(row['named_claims'][0]['availability'],'claim_material_not_delivered')
        self.assertIsNone(row['named_claims'][0]['text'])
        self.assertNotIn('monthly',str(row['named_claims']))

    def test_no_supplied_view_and_aliases_change_only_responsibility_positions(self):
        packet=self.packet();projected=attach_citation_view(packet)
        with self.assertRaisesRegex(ValueError,'Caller-supplied'):
            attach_citation_view(projected)
        wire,aliases=alias_proof_packet(projected)
        self.assertEqual(wire['citation_view'],projected['citation_view'])
        self.assertEqual(wire['materials'],packet['materials'])
        self.assertEqual([aliases[uid] for uid in wire['coverage']['claims']],packet['coverage']['claims'])

    def test_all_actual_planned_node_kinds_get_truthful_views(self):
        fixture=planner_fixtures.ProofPlannerTests();fixture.setUp();bundle=fixture.compile()
        kinds=set()
        for node_id,spec in bundle['node_specs'].items():
            packet=node_payload(bundle,node_id,{})
            view=attach_citation_view(packet)
            self.assertEqual(view['materials'],packet['materials'])
            self.assertEqual(view['coverage'],packet['coverage'])
            kinds.add(spec['kind'])
            if spec['kind']=='cross_group':
                self.assertTrue(all(part['availability']=='original_not_delivered'
                    for row in view['citation_view']['claim_rows'] for part in row['declared_parts']))
        self.assertEqual(kinds,{'source','cross_group','assembly','root'})


if __name__=='__main__':
    unittest.main()
