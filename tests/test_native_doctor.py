import importlib.util
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_doctor',ROOT/'skills/literature-review/scripts/native_doctor.py')
doctor=importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


class DoctorTests(unittest.TestCase):
    def test_missing_installation_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=doctor.diagnose(tmp,Path(tmp)/'missing.json',require_key=False)
            self.assertFalse(result['passed'])
            self.assertEqual(result['network_calls'],0)

    def test_wrong_tokenizer_and_missing_key_are_separate_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            tokenizer=Path(tmp)/'tokenizer.json'
            tokenizer.write_text('{}',encoding='utf-8')
            with patch.dict(doctor.os.environ,{},clear=True):
                result=doctor.diagnose(ROOT/'skills',tokenizer)
            checks={c['check']:c for c in result['checks']}
            self.assertFalse(checks['tokenizer']['passed'])
            self.assertFalse(checks['openrouter_key']['passed'])

    def test_key_never_appears_in_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(doctor.os.environ,{'OPENROUTER_API_KEY':'private-diagnostic-test-value'}):
                result=doctor.diagnose(ROOT/'skills',Path(tmp)/'missing')
            self.assertNotIn('private-diagnostic-test-value',str(result))
            self.assertTrue(next(c for c in result['checks'] if c['check']=='openrouter_key')['passed'])
            self.assertFalse(result['passed'])

    def test_selected_skill_uses_its_own_runtime_without_other_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            skill=root/'write-review'
            runtime=skill/'scripts/runtime/litreview_core'
            runtime.mkdir(parents=True)
            (skill/'references').mkdir()
            (skill/'SKILL.md').write_text('fixture',encoding='utf-8')
            (skill/'references/mapped-drafts.md').write_text('fixture',encoding='utf-8')
            (skill/'scripts/requirements-native.txt').write_text('fixture-package==1.0\n',encoding='utf-8')
            for module in ('native_agent','native_review','review_workflow','coordinator_frontier',
                           'proof_planner','proof_worker','review_repair','delivery_export','qwen_transport'):
                (runtime/(module+'.py')).write_text('# fixture',encoding='utf-8')
            tokenizer=root/'tokenizer.json'
            tokenizer.write_bytes(b'{}')
            (runtime/'qwen_tokens.py').write_text('EXPECTED_SHA256 = '+repr(sha256(b'{}').hexdigest()),encoding='utf-8')
            with patch.object(doctor,'version',return_value='1.0'):
                result=doctor.diagnose(root,tokenizer,require_key=False,skills=['write-review'])
            self.assertTrue(result['passed'])
            self.assertEqual(result['runtime_skill'],'write-review')
            self.assertEqual(result['selected_skills'],['write-review'])
            self.assertEqual(result['model_inference'],'not_tested')
            self.assertFalse((root/'literature-review').exists())

    def test_unknown_skill_rejected(self):
        with self.assertRaises(ValueError):
            doctor.diagnose(ROOT/'skills',Path('missing'),skills=['unknown'])


if __name__=='__main__':
    unittest.main()
