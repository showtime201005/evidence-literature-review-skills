from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/literature-review/scripts/runtime'))
from litreview_core.draft_submission_wire import alias_obligations, decode_grouped_submission
from litreview_core.review_artifacts import validate_draft, premise_obligations
import test_review_artifacts as fixtures


class GroupedDraftTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ReviewArtifactTests()
        f.setUp()
        self.packet,self.value=f.packet,f.value
        self.wire,self.aliases=alias_obligations(self.packet)
        self.grouped={'claims':self.value['claims'],'cells':[],
            'retention_groups':[{'obligation_ids':['o1'],'status':'included','claim_ids':['c'],'reason':'保留失敗'}]}

    def test_exact_expansion_preserves_decision_and_original_ids(self):
        decoded=decode_grouped_submission(self.grouped,self.aliases)
        for claim in self.value['claims']:
            claim.setdefault('premise_claim_ids',[])
        self.assertEqual(decoded,self.value)
        self.assertEqual(self.wire['obligations'][0]['id'],'o1')
        self.assertEqual(self.packet['obligations'][0]['id'],'failure')

    def test_missing_unknown_and_duplicate_aliases_rejected(self):
        for ids in ([],['o2'],['o1','o1']):
            self.grouped['retention_groups'][0]['obligation_ids']=ids
            with self.assertRaises(ValueError):
                decode_grouped_submission(self.grouped,self.aliases)

    def test_shared_reason_expands_without_approving_exclusion(self):
        self.aliases['o2']='second-qualification'
        self.grouped['retention_groups'][0].update(obligation_ids=['o1','o2'],status='excluded',claim_ids=[],reason='Requires independent relevance review')
        result=decode_grouped_submission(self.grouped,self.aliases)
        self.assertEqual(len(result['retention']),2)
        self.assertTrue(all(r['status']=='excluded' for r in result['retention']))

    def test_historical_premise_retention_keeps_its_own_canonical_scope(self):
        section=validate_draft(self.packet,self.value,execution_id='writer')
        packet={**self.packet,'kind':'synthesis','premises':[section],
                'obligations':premise_obligations([section])}
        wire,aliases=alias_obligations(packet)
        self.assertEqual(wire['obligations'][0]['id'],'o1')
        self.assertEqual(wire['premises'][0]['retention'],section['retention'])
        self.assertEqual(aliases['o1'],packet['obligations'][0]['id'])
        self.assertNotIn(section['retention'][0]['obligation_id'],aliases.values())


if __name__=='__main__':
    unittest.main()
