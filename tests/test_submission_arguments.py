import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/literature-review/scripts/runtime'))
from litreview_core.native_reading import ReviewArguments


class SubmissionArgumentsTests(unittest.TestCase):
    def test_json_string_keeps_adverse_verdict(self):
        value={'verdicts':[{'finding_id':'f','status':'contradicted','reason':'Source says opposite'}],
               'checked_part_ids':['p'],'question_ids':['q'],'omission_check':'unresolved',
               'omission_reason':'Missing source context','issues':[]}
        decoded=ReviewArguments.model_validate({'data':json.dumps(value)})
        self.assertEqual(decoded.data.model_dump(),value)

    def test_invalid_json_is_not_repaired_or_evaluated(self):
        with self.assertRaises(ValueError):
            ReviewArguments.model_validate({'data':'{not JSON'})


if __name__=='__main__':
    unittest.main()
