from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/literature-review/scripts/runtime'))
from litreview_core.hierarchical_proof import DIMENSIONS, payload_hash
from litreview_core.proof_worker import proof_worker, SemanticProofFailure


class ProofWorkerTests(unittest.TestCase):
    def setUp(self):
        self.coverage={dim:[] for dim in DIMENSIONS}
        self.coverage.update(claims=['c'],obligations=['o'],lines=['l'])
        raw=b'Original\r\nsource'
        self.bundle={'materials':{'raw':raw},'node_specs':{'n':{
            'node_id':'n','kind':'source','role':'verifier','coverage':self.coverage,
            'input_ids':['raw'],'inputs':{'raw':payload_hash(raw)},'dependencies':[]}}}
        self.identity=SimpleNamespace(role='verifier',context_id='actual-verifier',
            task_tool_call_id='actual-task',coordinator_context_id='parent')
        self.saved=[]
        self.data={'checked':self.coverage,'verdicts':[
            {'unit_id':u,'verdict':'passed','reason':'Checked original evidence'} for u in ('c','o')],
            'status':'passed','reason':'Original source and limitations support target','issues':[]}

    def worker(self):
        return proof_worker(self.bundle,'n',{},self.identity,save=lambda *v:self.saved.append(v))

    def test_binds_actual_execution_and_original_bytes(self):
        worker=self.worker()
        raw=worker.inputs['proof-task.json']['materials']['raw'].encode()
        self.assertEqual(raw,self.bundle['materials']['raw'])
        receipt=worker.accept(self.data,self.identity)
        node,identity,submission=self.saved[0]
        self.assertEqual(identity.task_call_id,'actual-task')
        self.assertEqual(identity.output_hashes['n'],receipt['proof_hash'])
        self.assertEqual(node['payload']['execution_id'],'actual-verifier')

    def test_negative_preserved_and_terminal(self):
        self.data['status']='needs_revision'
        self.data['verdicts'][0].update(verdict='needs_revision',reason='Original result was null')
        self.data['issues']=[{'unit_ids':['c'],'description':'Null result called benefit','correction':'Preserve uncertainty'}]
        with self.assertRaises(SemanticProofFailure):
            self.worker().accept(self.data,self.identity)
        self.assertEqual(self.saved[0][0]['payload']['status'],'needs_revision')

    def test_native_store_receipt_survives_proof_submission(self):
        stored={'ticket':'t','context':'actual-verifier','input_hash':'input',
                'output_hash':'output','status':'accepted'}
        worker=proof_worker(self.bundle,'n',{},self.identity,save=lambda *args:stored)
        receipt=worker.accept(self.data,self.identity)
        for key,value in stored.items():
            self.assertEqual(receipt[key],value)
        self.assertEqual(receipt['proof_status'],'passed')
        self.assertEqual(receipt['node_id'],'n')
        self.assertIn('proof_hash',receipt)

    def test_aliased_submission_stores_exact_canonical_responsibilities(self):
        worker=self.worker()
        packet=worker.inputs['proof-task.json']
        inverse={v:k for k,v in packet['responsibility_aliases'].items()}
        self.data['checked']=packet['coverage']
        for verdict in self.data['verdicts']:
            verdict['unit_id']=inverse[verdict['unit_id']]
        worker.accept(self.data,self.identity)
        self.assertEqual(self.saved[0][2]['checked'],self.coverage)
        self.assertEqual([v['unit_id'] for v in self.saved[0][2]['verdicts']],['c','o'])

    def test_alias_plus_canonical_duplicate_is_rejected(self):
        worker=self.worker()
        inverse={v:k for k,v in worker.inputs['proof-task.json']['responsibility_aliases'].items()}
        self.data['verdicts'].append({'unit_id':inverse['c'],'verdict':'passed','reason':'duplicate'})
        with self.assertRaisesRegex(ValueError,'duplicates'):
            worker.accept(self.data,self.identity)
        self.assertEqual(self.saved,[])

    def test_missing_coverage_and_verdicts_rejected(self):
        self.data['checked']={**self.coverage,'lines':[]}
        with self.assertRaises(ValueError):
            self.worker().accept(self.data,self.identity)
        self.data['checked']=self.coverage
        self.data['verdicts']=self.data['verdicts'][:1]
        with self.assertRaises(ValueError):
            self.worker().accept(self.data,self.identity)
        self.assertEqual(self.saved,[])

    def test_stale_input_and_foreign_identity_rejected(self):
        worker=self.worker()
        with self.assertRaises(ValueError):
            worker.accept(self.data,SimpleNamespace(context_id='writer'))
        self.bundle['materials']['raw']=b'changed'
        with self.assertRaises(ValueError):
            self.worker()

    def test_pass_cannot_override_failed_unit(self):
        self.data['verdicts'][0]['verdict']='unresolved'
        with self.assertRaises(ValueError):
            self.worker().accept(self.data,self.identity)
        self.assertEqual(self.saved,[])

    def test_extra_scoped_verdict_is_retained_without_redundant_retry(self):
        self.data['verdicts'].append({'unit_id':'l','verdict':'passed','reason':'Rendered line checked'})
        self.worker().accept(self.data,self.identity)
        self.assertEqual(len(self.saved[0][2]['verdicts']),3)

    def test_extra_negative_verdict_cannot_pass(self):
        self.data['verdicts'].append({'unit_id':'l','verdict':'needs_revision','reason':'Misleading heading'})
        with self.assertRaises(ValueError):
            self.worker().accept(self.data,self.identity)
        self.assertEqual(self.saved,[])

    def test_verdict_diagnostic_lists_missing_unknown_and_duplicates(self):
        self.data['verdicts']=[{'unit_id':u,'verdict':'passed','reason':'fixture'} for u in ('c','c','foreign')]
        with self.assertRaises(ValueError) as caught:
            self.worker().accept(self.data,self.identity)
        error=str(caught.exception)
        for fragment in ('"missing": ["o"]','"unknown": ["foreign"]','"duplicates": ["c"]'):
            self.assertIn(fragment,error)
        self.assertEqual(self.saved,[])

    def compact_fixture(self):
        from test_hierarchical_proof import CompactDependencyReceiptTests
        fixture=CompactDependencyReceiptTests()
        fixture.setUp()
        host=fixture.h
        payload=host.nodes['cross']['payload']
        bundle={'plan':host.plan,'materials':host.materials,'node_specs':{'cross':{
            'node_id':'cross','kind':'cross_group','role':'verifier','coverage':payload['coverage'],
            'input_ids':list(payload['inputs']),'inputs':payload['inputs'],
            'dependencies':list(payload['dependencies'])}}}
        identity=SimpleNamespace(role='verifier',context_id='new-real-worker-context',
            task_tool_call_id='actual-sdk-task-id',coordinator_context_id='actual-parent')
        dependencies={dep:host.nodes[dep] for dep in payload['dependencies']}
        return host,bundle,identity,dependencies

    def test_compact_worker_preflights_and_binds_actual_receipt_bytes(self):
        host,bundle,identity,dependencies=self.compact_fixture()
        saved=[]
        worker=proof_worker(bundle,'cross',dependencies,identity,save=lambda *v:saved.append(v),
            proof_nodes=host.nodes,proof_identities=host.identities)
        packet=worker.inputs['proof-task.json']
        self.assertEqual(packet['dependency_delivery'],'dependency-proof-receipt/1')
        self.assertNotIn('dependency_proofs',packet)
        self.assertEqual(set(packet['dependency_receipts']),set(dependencies))
        for receipt in packet['dependency_receipts'].values():
            self.assertNotIn('inputs',receipt)
            self.assertNotIn('dependencies',receipt)
        coverage=packet['coverage']
        data={'checked':coverage,'verdicts':[{'unit_id':u,'verdict':'passed','reason':'Explicit offline structural fixture'}
             for u in coverage['claims']+coverage['obligations']],
             'status':'passed','reason':'Explicit offline structural fixture, not model QA','issues':[]}
        worker.accept(data,identity)
        runtime=saved[0][1]
        self.assertEqual(dict(runtime.delivered_dependency_receipt_hashes),
            {dep:payload_hash(receipt) for dep,receipt in packet['dependency_receipts'].items()})
        self.assertEqual(dict(runtime.dependency_hashes),{dep:node['payload_hash'] for dep,node in dependencies.items()})

    def test_compact_worker_missing_trusted_registry_fails_closed(self):
        host,bundle,identity,dependencies=self.compact_fixture()
        with self.assertRaisesRegex(ValueError,'complete trusted'):
            proof_worker(bundle,'cross',dependencies,identity,save=lambda *v:None)

    def test_compact_worker_missing_child_identity_fails_before_delivery(self):
        host,bundle,identity,dependencies=self.compact_fixture()
        del host.identities['exec-source-a']
        with self.assertRaises(ValueError):
            proof_worker(bundle,'cross',dependencies,identity,save=lambda *v:None,
                proof_nodes=host.nodes,proof_identities=host.identities)


if __name__=='__main__':
    unittest.main()
