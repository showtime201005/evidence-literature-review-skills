"""Opt-in worker contract; scripted judgments are not scientific acceptance."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/literature-review/scripts/runtime'))
sys.path.insert(0,str(ROOT/'tests'))
from test_native_task_verifier import fixture
from litreview_core.proof_quote_worker import source_witness_worker
from litreview_core.proof_quote_witness import WitnessValidationError
from litreview_core.proof_worker import SemanticProofFailure
from litreview_core.source_witness_audit import verify_source_witness_audits


class QuoteWorkerTests(unittest.TestCase):
    def setUp(self):
        self.value,self.bundle=fixture()
        self.identity=SimpleNamespace(role='verifier',context_id='independent-witness',
            task_tool_call_id='actual-test-task',coordinator_context_id='test-parent')
        self.saved=[]
        self.worker=source_witness_worker(self.bundle,self.value['node_id'],{},self.identity,
            save=lambda *args:self.saved.append(args))
        packet=self.worker.inputs['proof-task.json']
        aliases=packet['responsibility_aliases']
        rows={r['claim_id']:r for r in packet['citation_view']['claim_rows']}
        verdicts=[]
        for uid in packet['coverage']['claims']:
            row=rows[aliases[uid]]
            part=row['declared_parts'][0]
            verdicts.append({'unit_id':uid,'verdict':'passed','reason':'Scripted test only',
                'clause_checks':[{'clause':row['text'],'relation':'explicit_support',
                    'witnesses':[{'ref':part['ref'],'quote':part['text']}],
                    'reason':'Scripted test only'}]})
        verdicts.extend({'unit_id':uid,'verdict':'passed','reason':'Scripted test only'}
                        for uid in packet['coverage']['obligations'])
        self.args={'data':{'checked':copy.deepcopy(packet['coverage']),'verdicts':verdicts,
            'status':'passed','reason':'Scripted test only','issues':[]}}

    def test_saves_full_witness_audit_with_normal_proof(self):
        receipt=self.worker.accept(self.args,self.identity)
        self.assertEqual(receipt['proof_status'],'passed')
        self.assertTrue(self.worker.raw_tool_arguments)
        audit=self.saved[0][2]['quote_witness']
        self.assertEqual(audit['original_tool_arguments'],self.args)
        self.assertTrue(audit['literal_validation']['literal_checks_completed'])
        self.assertFalse(audit['semantic_entailment_proven'])
        self.assertEqual(self.saved[0][0]['payload']['status'],'passed')

    def test_valid_negative_is_saved_and_terminates(self):
        value=self.args['data']
        value['status']='needs_revision'
        value['verdicts'][0]['verdict']='needs_revision'
        value['verdicts'][0]['clause_checks'][0]['relation']='topic_only'
        value['issues']=[{'unit_ids':[value['verdicts'][0]['unit_id']],
                         'description':'Unsupported relation','correction':'Remove unsupported relation'}]
        with self.assertRaises(SemanticProofFailure):
            self.worker.accept(self.args,self.identity)
        self.assertEqual(self.saved[0][0]['payload']['status'],'needs_revision')
        self.assertTrue(self.saved[0][2]['quote_witness']['semantic_negative_detected'])

    def test_malformed_negative_is_not_sealed_or_erased(self):
        self.args['data']['status']='needs_revision'
        self.args['data']['verdicts'][0]['clause_checks']='bad format'
        with self.assertRaises(WitnessValidationError) as caught:
            self.worker.accept(self.args,self.identity)
        self.assertTrue(caught.exception.semantic_negative_detected)
        self.assertFalse(self.saved)

    def test_delivery_rechecks_current_scope_and_rejects_audit_or_verdict_changes(self):
        self.worker.accept(self.args,self.identity)
        node,identity,submission=self.saved[0]
        nid=self.value['node_id']
        scoped={**self.bundle,'node_specs':{nid:self.bundle['node_specs'][nid]}}
        checked=verify_source_witness_audits(scoped,{nid:node},{nid:submission})
        self.assertEqual(set(checked['source_nodes']),{nid})
        self.assertFalse(checked['semantic_entailment_proven'])
        for mutation in ('missing','audit','verdict'):
            changed=copy.deepcopy(submission)
            if mutation=='missing':
                changed.pop('quote_witness')
            elif mutation=='audit':
                changed['quote_witness']['canonical_witness_submission_sha256']='0'*64
            else:
                changed['verdicts'][0]['reason']='Changed after validation'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify_source_witness_audits(scoped,{nid:node},{nid:changed})


if __name__=='__main__':
    unittest.main()
