from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/literature-review/scripts/runtime'))
from litreview_core.scientific_records import source_packet
from litreview_core.review_artifacts import draft_packet, validate_draft, render_section, premise_obligations, inference_packet
import copy


class ReviewArtifactTests(unittest.TestCase):
    def setUp(self):
        source=source_packet('p','結果有改善。\n\n修正後仍失敗。'.encode(),[{'id':'q','text':'effects'}])
        record={'paper_id':'p','source_sha256':source['source_sha256'],
                'evidence':[{'id':'e','part_id':'p0002'}],
                'obligations':[{'id':'failure','kind':'persistent_failure','evidence_refs':['e']}]}
        self.packet=draft_packet('paper_card',[source],[record],source['questions'])
        self.source,self.record=source,record
        self.value={'claims':[{'local_id':'c','text':'改善有限；仍失敗。','evidence_refs':['p/p0001','p/p0002'],
                    'question_ids':['q'],'attribution':'source_finding','scope':'individual','population_paper_ids':['p']}],
                    'retention':[{'obligation_id':'failure','status':'included','claim_ids':['c'],'reason':'保留失敗'}], 'cells':[]}

    def test_generated_full_line_inventory(self):
        section=validate_draft(self.packet,self.value,execution_id='writer')
        result=render_section(section)
        self.assertEqual(len(result['lines']),2)
        self.assertEqual(sum(bool(x.strip()) for x in result['text'].splitlines()),len(result['lines']))
        for line in result['lines']:
            self.assertEqual(result['text'][line['start_char']:line['end_char']],line['text'])

    def test_comparison_uses_actual_card_premises_and_retains_full_cell_contract(self):
        card=validate_draft(self.packet,self.value,execution_id='card-writer')
        packet=inference_packet([card],[self.source],[self.record],self.source['questions'],
                                kind='comparison',dimensions=['limitations'])
        self.assertEqual(packet['obligations'],premise_obligations([card]))
        self.assertNotIn('text',packet['sources']['p/p0001'])
        self.assertEqual(packet['premises'][0]['claims'],card['claims'])
        value=copy.deepcopy(self.value)
        value['claims'][0]['premise_claim_ids']=[card['section_id']+'/c']
        value['retention']=[{'obligation_id':packet['obligations'][0]['id'],
            'status':'included','claim_ids':['c'],'reason':'Failure retained'}]
        value['cells']=[{'paper_id':'p','dimension':'limitations','claim_ids':['c']}]
        comparison=validate_draft(packet,value,execution_id='comparer')
        self.assertEqual(comparison['premise_section_ids'],[card['section_id']])
        self.assertEqual(comparison['verification_status'],'unverified')
        value['cells']=[]
        with self.assertRaises(ValueError):
            validate_draft(packet,value,execution_id='comparer')

    def test_derived_comparison_rejects_unrepresented_papers_and_noncard_premises(self):
        card=validate_draft(self.packet,self.value,execution_id='card-writer')
        for kind,papers in (('synthesis',['p']),('paper_card',['foreign'])):
            invalid=copy.deepcopy(card)
            invalid.update(kind=kind,paper_ids=papers)
            with self.assertRaises(ValueError):
                inference_packet([invalid],[self.source],[self.record],self.source['questions'],kind='comparison')
        with self.assertRaisesRegex(ValueError,'one card per paper'):
            inference_packet([card,card],[self.source],[self.record],self.source['questions'],kind='comparison')

    def test_lost_counterevidence_cannot_pass(self):
        self.value['retention']=[]
        with self.assertRaises(ValueError):
            validate_draft(self.packet,self.value,execution_id='writer')

    def test_reader_evidence_ids_are_not_report_citations(self):
        obligation=self.packet['obligations'][0]
        self.assertNotIn('evidence_refs',obligation)
        self.assertEqual(obligation['reader_evidence_ids'],['e'])
        self.assertEqual(obligation['source_refs'],['p/p0002'])
        self.value['claims'][0]['evidence_refs']=['e','another_reader_id']
        with self.assertRaises(ValueError) as caught:
            validate_draft(self.packet,self.value,execution_id='writer')
        self.assertEqual(caught.exception.details['source_references']['invalid'][0]['unknown'],
                         ['another_reader_id','e'])
        self.assertEqual(caught.exception.details['source_references']['allowed'],['p/p0001','p/p0002'])

    def test_card_limits_reject_without_truncating_scientific_text(self):
        for mode in ('claims','characters'):
            value=copy.deepcopy(self.value)
            if mode=='claims':
                value['claims']=[dict(value['claims'][0],local_id='c'+str(i)) for i in range(13)]
                value['retention'][0]['claim_ids']=['c0']
            else:
                value['claims'][0]['text']='重要限制'*751
            original=copy.deepcopy(value)
            with self.assertRaises(ValueError) as caught:
                validate_draft(self.packet,value,execution_id='writer')
            self.assertIn('card_size',caught.exception.details)
            self.assertEqual(value,original)

    def test_unknown_citation_and_hidden_paragraph(self):
        self.value['claims'][0]['evidence_refs']=['unknown/p0001']
        with self.assertRaises(ValueError):
            validate_draft(self.packet,self.value,execution_id='writer')
        self.value['claims'][0]['evidence_refs']=['p/p0001']
        self.value['claims'][0]['text']='valid\n# undeclared factual heading'
        with self.assertRaises(ValueError):
            validate_draft(self.packet,self.value,execution_id='writer')

    def test_exclusion_is_explicit_but_not_semantically_approved(self):
        self.value['retention'][0].update(status='excluded',claim_ids=[],reason='Allegedly unrelated; auditor must assess')
        section=validate_draft(self.packet,self.value,execution_id='writer')
        self.assertEqual(section['verification_status'],'unverified')

    def test_direct_premise_inventory_is_derived_from_actual_claims(self):
        section = validate_draft(self.packet, self.value, execution_id='writer')
        obligations = premise_obligations([section])
        self.assertEqual(len(obligations), len(section['claims']))
        self.assertEqual(obligations[0]['text'], section['claims'][0]['text'])
        self.assertEqual(obligations[0]['source_refs'], section['claims'][0]['evidence_refs'])
        self.assertEqual(obligations[0]['premise_claim_id'], section['section_id']+'/c')
        with self.assertRaises(ValueError):
            premise_obligations([section, section])

    def test_included_premise_must_really_be_used_by_delivered_claim(self):
        section = validate_draft(self.packet, self.value, execution_id='writer')
        second = copy.deepcopy(section['claims'][0])
        second['local_id'] = 'counter'
        section['claims'].append(second)
        packet = copy.deepcopy(self.packet)
        packet.update(kind='synthesis', premises=[section], obligations=premise_obligations([section]))
        value = copy.deepcopy(self.value)
        value['claims'][0]['premise_claim_ids'] = [section['section_id']+'/c']
        value['retention'] = [{'obligation_id': o['id'], 'status':'included',
            'claim_ids':['c'], 'reason':'Included'} for o in packet['obligations']]
        with self.assertRaisesRegex(ValueError, 'actual premise'):
            validate_draft(packet, value, execution_id='synthesizer')
        value['claims'][0]['premise_claim_ids'].append(section['section_id']+'/counter')
        result = validate_draft(packet, value, execution_id='synthesizer')
        self.assertEqual(result['verification_status'], 'unverified')


if __name__=='__main__':
    unittest.main()
