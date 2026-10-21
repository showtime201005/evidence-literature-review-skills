"""Mechanical full-DAG test with explicit fake scientific verdicts, zero API."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/literature-review/scripts/runtime'))
from litreview_core.review_workflow import ReviewWorkflow
from litreview_core.scientific_records import FIELDS, source_packet
from litreview_core.task_store import TaskStore
from litreview_core.proof_worker import SemanticProofFailure
from litreview_core.draft_wire import restore_draft_packet


class WorkflowTests(unittest.TestCase):
    def test_full_dag_mechanics_with_fake_science(self):
        self.exercise()

    def test_explicit_proof_packing_limit_is_forwarded(self):
        self.exercise(proof_max_units=8)

    def test_explicit_full_source_merge_is_forwarded(self):
        self.exercise(merge_full_source=True)

    def test_merged_semantic_negative_is_revised_and_freshly_checked(self):
        self.exercise(reject_first=True,merge_full_source=True)

    def test_repeated_merged_negative_still_exhausts_repair_budget(self):
        with self.assertRaisesRegex(RuntimeError,'repair budget exhausted'):
            self.exercise(reject_first=True,reject_always=True,merge_full_source=True)

    def test_proof_packing_limit_rejects_invalid_values(self):
        for limit in (0,129,True,1.5):
            with self.assertRaisesRegex(ValueError,'Proof unit limit'):
                ReviewWorkflow(None,[],[],proof_max_units=limit)

    def test_rejected_claim_is_revised_and_rechecked(self):
        self.exercise(reject_first=True)

    def test_repeated_negative_verdict_exhausts_repair_budget(self):
        with self.assertRaisesRegex(RuntimeError,'repair budget exhausted'):
            self.exercise(reject_first=True,reject_always=True)

    def test_early_card_gate_is_opt_in_and_retains_native_proofs(self):
        self.exercise(early_card_verification=True,merge_full_source=True)
        self.assertTrue(self.last_workflow.early_proof_nodes)
        self.assertEqual(self.last_workflow.early_card_history[-1]['status'],'qualified')
        self.assertEqual(self.last_workflow.repair_rounds_used,0)

    def test_early_negative_revises_card_before_any_comparison(self):
        self.exercise(early_card_verification=True,merge_full_source=True,reject_first=True)
        self.assertEqual(self.last_workflow.repair_rounds_used,1)
        self.assertEqual([r['status'] for r in self.last_workflow.early_card_history],['needs_revision','qualified'])
        self.assertLess(self.last_stages.index('early-card-revision-0'),self.last_stages.index('comparison'))
        self.assertTrue(self.last_early_snapshot['mini_bundle_hashes'])
        self.assertTrue(self.last_early_snapshot['submissions'])

    def test_early_repeated_negative_exhausts_budget_without_comparison(self):
        with self.assertRaisesRegex(RuntimeError,'repair budget exhausted'):
            self.exercise(early_card_verification=True,merge_full_source=True,reject_first=True,reject_always=True)
        self.assertNotIn('comparison',self.last_stages)
        self.assertFalse(any(row['role']=='comparer' for row in self.last_rows))
        self.assertEqual(self.last_workflow.repair_rounds_used,2)

    def test_early_and_global_scientific_revisions_share_one_budget(self):
        with self.assertRaisesRegex(RuntimeError,'repair budget exhausted'):
            self.exercise(early_card_verification=True,merge_full_source=True,reject_first=True,
                          reject_final=True,max_repairs=1)
        self.assertIn('comparison',self.last_stages)
        self.assertEqual(self.last_workflow.repair_rounds_used,1)

    def test_changed_source_during_early_check_blocks_comparison(self):
        with self.assertRaisesRegex(ValueError,'version changed'):
            self.exercise(early_card_verification=True,merge_full_source=True,change_source=True)
        self.assertNotIn('comparison',self.last_stages)

    def test_early_option_rejects_non_boolean(self):
        for value in (1,None,'true'):
            with self.assertRaisesRegex(ValueError,'early_card_verification'):
                ReviewWorkflow(None,[],[],early_card_verification=value)

    def exercise(self,reject_first=False,reject_always=False,proof_max_units=16,merge_full_source=False,
                 early_card_verification=False,reject_final=False,max_repairs=2,change_source=False):
        with tempfile.TemporaryDirectory() as tmp:
            questions=[{'id':'q','text':'What limits the result?'}]
            packets=[source_packet('p'+str(i),b'Failure persists.',questions) for i in range(3)]
            store=TaskStore(tmp)
            workflow=ReviewWorkflow(store,packets,questions,group_size=2,proof_max_units=proof_max_units,
                                    merge_full_source=merge_full_source,early_card_verification=early_card_verification,
                                    max_repairs=max_repairs)
            stages=[]
            rejected=[]
            final_rejected=[]
            async def dispatch(stage,factory,tickets=None):
                stages.append(stage)
                def ready():
                    return [r for r in store.ready(100) if tickets is None or r['id'] in tickets]
                while ready():
                    for row in ready():
                        identity=SimpleNamespace(role=row['role'],context_id='ctx-'+row['id'],
                            task_tool_call_id='mock-task-'+row['id'],coordinator_context_id='mock-parent')
                        worker=factory(identity,json.dumps({'ticket':row['id']}))
                        packet=next(iter(worker.inputs.values()))
                        if identity.role=='reader':
                            data={'observations':[{'part_id':p['part_id'],'note':'Failure persists'} for p in packet['parts']],
                                'findings':[{'local_id':'f','field':'limitations','text':'Failure persists',
                                    'attribution':'author_limitation','evidence':[{'part_id':'p0001'}],
                                    'obligations':['persistent_failure']}],
                                'fields':[{'field':f,'status':'extracted' if f=='limitations' else 'not_reported','reason':'test'} for f in FIELDS],
                                'questions':[{'question_id':'q','status':'addressed','reason':'Failure','support':[],'counterevidence':['f']}]}
                        elif identity.role in ('writer','comparer'):
                            packet=restore_draft_packet(packet)
                            claims=[]
                            for pid in packet['paper_ids']:
                                premises=[s['section_id']+'/'+c['local_id'] for s in packet['premises'] for c in s['claims']
                                          if pid in c['population_paper_ids']]
                                claims.append({'local_id':pid,'text':'Failure persists','evidence_refs':[pid+'/p0001'],
                                    'question_ids':['q'],'attribution':'source_finding','scope':'individual',
                                    'population_paper_ids':[pid],'premise_claim_ids':premises})
                            data={'claims':claims,'retention_groups':[{'obligation_ids':[o['id']],'status':'included',
                                'claim_ids':[o['source_refs'][0].split('/')[0]],'reason':'Failure retained'} for o in packet['obligations']],
                                'cells':[{'paper_id':p,'dimension':d,'claim_ids':[p]} for p in packet['paper_ids']
                                         for d in packet['dimensions']]}
                        else:
                            coverage=packet['coverage']
                            data={'checked':coverage,'verdicts':[{'unit_id':u,'verdict':'passed','reason':'Fake offline mechanical verdict'}
                                for u in coverage['claims']+coverage['obligations']],
                                'status':'passed','reason':'Fake offline mechanical verdict','issues':[]}
                            if ((reject_first and (not rejected or reject_always)) or
                                    (reject_final and stage.startswith('independent-proofs') and not final_rejected)) and coverage['claims']:
                                rejected.append(packet['node_id'])
                                if stage.startswith('independent-proofs'):
                                    final_rejected.append(packet['node_id'])
                                data['status']='needs_revision'
                                data['verdicts'][0]['verdict']='needs_revision'
                                data['issues']=[{'unit_ids':[coverage['claims'][0]],'description':'Fake repair trigger',
                                                'correction':'Re-read the limitation'}]
                        try:
                            receipt=worker.accept(data,identity)
                            accepted_row=next(r for r in store.status() if r['id']==row['id'])
                            for key,field in (('ticket','id'),('context','context'),
                                    ('input_hash','input_hash'),('output_hash','output_hash'),('status','status')):
                                self.assertEqual(receipt[key],accepted_row[field])
                        except SemanticProofFailure:
                            worker.on_finish(identity,{'accepted':False})
                            raise RuntimeError('Mock coordinator preserves scientific failure')
                        worker.on_finish(identity,{'accepted':True}) if worker.on_finish else None
                if change_source and stage.startswith('early-card-proofs'):
                    workflow.packets[0]['parts'][0]['text']+=' changed source'
            try:
                result=asyncio.run(workflow.run(dispatch))
            finally:
                self.last_workflow,self.last_stages,self.last_rows=workflow,stages,store.status()
                self.last_early_snapshot=store.get(workflow.early_card_history[0]['snapshot_hash']) if workflow.early_card_history else None
            self.assertEqual(result['gate']['status'],'passed')
            self.assertEqual(result['bundle']['max_scientific_units'],proof_max_units)
            self.assertEqual(result['bundle']['merge_full_source'],merge_full_source)
            self.assertEqual(result['early_card_verification'],early_card_verification)
            if early_card_verification:
                for nid,node in workflow.early_proof_nodes.items():
                    self.assertIs(result['nodes'][nid],node)
                for capsule in self.last_early_snapshot['mini_bundle_hashes'].values():
                    saved=store.get(capsule)
                    originals=[v for v in saved['materials'].values() if v['kind']=='raw_utf8']
                    self.assertTrue(originals)
                    from litreview_core.hierarchical_proof import payload_hash
                    self.assertTrue(all(payload_hash(v['text'].encode('utf-8'))==v['sha256'] for v in originals))
            self.assertEqual(len(result['records']),3)
            self.assertEqual(len(result['sections']),8)
            self.assertEqual(set(result['nodes']),set(result['bundle']['node_specs']))
            self.assertIn('synthesis-1',stages)
            if reject_first:
                self.assertEqual(len(result['repair_history']),1)
                self.assertTrue(any(s.startswith('early-card-revision-' if early_card_verification else 'revision-') for s in stages))
                self.assertTrue(any(r['status']=='failed' for r in store.status()))


if __name__=='__main__':
    unittest.main()
