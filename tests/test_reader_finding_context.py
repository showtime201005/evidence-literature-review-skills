"""Writers must receive the actual propositions their dispositions refer to."""
import copy
import unittest

import test_proof_planner as fixture
from litreview_core.hierarchical_proof import payload_hash
from litreview_core.paper_review_v2 import plan_paper_review_v2,validate_paper_bundle_v2
from litreview_core.review_artifacts import draft_packet,validate_draft
from litreview_core.draft_wire import project_draft_packet,restore_draft_packet


class ReaderFindingContextTests(unittest.TestCase):
    def setUp(self):
        f=fixture.ProofPlannerTests();f.setUp()
        self.source,self.reader,self.card=f.packets[0],f.records[0],f.cards[0]

    def packet(self,reader=None):
        return draft_packet('paper_card',[self.source],[reader or self.reader],self.source['questions'],
                            include_reader_findings=True)

    def test_complete_findings_and_source_bindings_delivered_once_losslessly(self):
        packet=self.packet()
        context=packet['reader_findings'][0]
        self.assertEqual(context['record_sha256'],payload_hash(self.reader))
        self.assertEqual(context['execution_id'],self.reader['execution_id'])
        evidence={e['id']:e for e in self.reader['evidence']}
        for finding in self.reader['findings']:
            actual=context['findings'][finding['local_id']]
            self.assertEqual(actual['finding'],finding)
            refs=list(dict.fromkeys(self.reader['paper_id']+'/'+evidence[e]['part_id'] for e in finding['evidence_refs']))
            self.assertEqual(actual['source_refs'],refs)
        for obligation in packet['obligations']:
            self.assertIn(obligation['finding_id'],context['findings'])
        self.assertEqual(restore_draft_packet(project_draft_packet(packet)),packet)

    def test_new_context_is_bound_to_card_and_replayed_from_actual_reader(self):
        card=validate_draft(self.packet(),{k:self.card[k] for k in ('claims','retention','cells')},
                            execution_id=self.card['writer_execution_id'])
        self.assertEqual(card['reader_context_profile'],'reader-finding-context/1')
        self.assertNotEqual(card['packet_sha256'],self.card['packet_sha256'])
        bundle=plan_paper_review_v2(self.source,self.reader,card)
        validate_paper_bundle_v2(bundle)
        for damage in ('profile','finding'):
            changed=copy.deepcopy(bundle)
            if damage=='profile':changed['payload']['card'].pop('reader_context_profile')
            else:changed['payload']['reader']['findings'][0]['text']+=' unreviewed change'
            with self.subTest(damage=damage),self.assertRaises(ValueError):validate_paper_bundle_v2(changed)
        # Historical packets/cards retain their explicit older input contract.
        validate_paper_bundle_v2(plan_paper_review_v2(self.source,self.reader,self.card))

    def test_missing_finding_cannot_leave_an_unresolvable_retention_id(self):
        reader=copy.deepcopy(self.reader)
        fid=reader['obligations'][0]['finding_id']
        reader['findings']=[f for f in reader['findings'] if f['local_id']!=fid]
        with self.assertRaisesRegex(ValueError,'actual complete reader finding'):self.packet(reader)


if __name__=='__main__':unittest.main()
