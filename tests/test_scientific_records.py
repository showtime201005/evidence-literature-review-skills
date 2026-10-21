from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/literature-review/scripts/runtime'))
from litreview_core.scientific_records import FIELDS, source_packet, validate_reader


class ScientificRecordTests(unittest.TestCase):
    def setUp(self):
        self.raw = '# 論文\r\n\r\n修正後仍失敗。\r\n\r\n成本未測量。'.encode('utf-8')
        self.packet = source_packet('paper1', self.raw, [{'id':'q1','text':'What fails?'}])
        self.value = {'observations':[{'part_id':p['part_id'], 'note':p['text']} for p in self.packet['parts']],
            'findings':[{'local_id':'f1','field':'unexpected_findings','text':'修正後仍失敗。',
                'attribution':'author_result','evidence':[{'part_id':'p0002','quote':'修正後仍失敗。'}],
                'obligations':['persistent_failure']}],
            'fields':[{'field':f,'status':'extracted' if f=='unexpected_findings' else 'not_reported','reason':'test'} for f in FIELDS],
            'questions':[{'question_id':'q1','status':'addressed','reason':'Failure persists','support':[], 'counterevidence':['f1']}]}

    def test_original_bytes_and_failure_outside_qmap(self):
        self.value['questions'][0].update(status='unresolved', counterevidence=[])
        record = validate_reader(self.packet,self.value,execution_id='runtime1')
        span = record['evidence'][0]
        self.assertEqual(self.raw[span['start_byte']:span['end_byte']].decode('utf-8'),span['quote'])
        self.assertIn('persistent_failure',{o['kind'] for o in record['obligations']})
        self.assertIn('extracted_unexpected_findings',{o['kind'] for o in record['obligations']})
        self.assertEqual(record['verification_status'],'unverified')

    def test_forged_quote(self):
        self.value['findings'][0]['evidence'][0]['quote']='不存在'
        with self.assertRaises(ValueError):
            validate_reader(self.packet,self.value,execution_id='runtime1')

    def test_whole_part_selection_preserves_exact_original(self):
        self.value['findings'][0]['evidence'] = [{'part_id':'p0002'}]
        record = validate_reader(self.packet,self.value,execution_id='runtime1')
        evidence = record['evidence'][0]
        self.assertEqual(evidence['quote'],self.packet['parts'][1]['text'])
        self.assertEqual(self.raw[evidence['start_byte']:evidence['end_byte']],evidence['quote'].encode('utf-8'))
    def test_omitted_source_part(self):
        self.value['observations'].pop()
        with self.assertRaises(ValueError):
            validate_reader(self.packet,self.value,execution_id='runtime1')


if __name__ == '__main__':
    unittest.main()
