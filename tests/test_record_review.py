from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/literature-review/scripts/runtime'))
from litreview_core.record_review import validate_record_review, RecordReviewFailure, record_projection, restore_record
from hashlib import sha256


class RecordReviewTests(unittest.TestCase):
    def setUp(self):
        self.packet={'paper_id':'p','source_sha256':'version','parts':[{'part_id':'p1'},{'part_id':'p2'}],
                     'questions':[{'id':'q'}]}
        self.record={'paper_id':'p','source_sha256':'version','execution_id':'writer','findings':[{'local_id':'f'}]}
        self.review={'verdicts':[{'finding_id':'f','status':'supported','reason':'Original source confirms'}],
                     'checked_part_ids':['p1','p2'],'question_ids':['q'], 'omission_check':'passed',
                     'omission_reason':'No important missing qualifications','issues':[]}

    def test_independence_and_complete_source(self):
        with self.assertRaises(ValueError):
            validate_record_review(self.packet,self.record,self.review,execution_id='writer')
        self.review['checked_part_ids'].pop()
        with self.assertRaises(ValueError):
            validate_record_review(self.packet,self.record,self.review,execution_id='verifier')

    def test_true_sentences_do_not_offset_missing_counterevidence(self):
        self.review['omission_check']='needs_revision'
        self.review['issues']=[{'kind':'important_omission','finding_ids':[], 'part_ids':['p2'],
            'description':'Persistent failure omitted','required_correction':'Add failure after mitigation'}]
        with self.assertRaises(RecordReviewFailure) as raised:
            validate_record_review(self.packet,self.record,self.review,execution_id='verifier')
        self.assertEqual(raised.exception.review['status'],'needs_revision')
        self.assertEqual(raised.exception.review['verdicts'][0]['status'],'supported')

    def test_pass_is_bound_to_record(self):
        result=validate_record_review(self.packet,self.record,self.review,execution_id='verifier')
        self.assertEqual(result['status'],'passed')
        self.assertEqual(len(result['record_sha256']),64)

    def test_projection_roundtrip_and_tamper(self):
        raw='原文\r\n保持'.encode('utf-8')
        digest=sha256(raw).hexdigest()
        packet={'source_sha256':digest,'parts':[{'text':raw.decode('utf-8')} ]}
        record={'evidence':[{'start_byte':0,'end_byte':len(raw),'source_sha256':digest,'quote':raw.decode('utf-8')}],
                'findings':[{'text':'保持原始內容'}]}
        view=record_projection(packet,record)
        self.assertNotIn('quote',view['record']['evidence'][0])
        self.assertEqual(restore_record(packet,view),record)
        view['record']['findings'][0]['text']='改動'
        with self.assertRaises(ValueError):
            restore_record(packet,view)


if __name__=='__main__':
    unittest.main()
