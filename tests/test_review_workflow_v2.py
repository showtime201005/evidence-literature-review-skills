"""Full native SDK experimental v2; scripted science never proves quality."""
import asyncio
import copy
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'skills/literature-review/scripts/runtime')]
from langchain_core.messages import AIMessage,HumanMessage,ToolMessage
from test_native_agent import ScriptedModel
from test_review_workflow_native_sdk import scripted_submission
from test_paper_review_v2 import scripted_v2
from test_section_review_v2 import scripted_section
from litreview_core.coordinator_frontier import run_frontiers
from litreview_core.delivery_export_v2 import export_review_v2,save_review_attempt_v2
from litreview_core.hierarchical_proof import payload_hash
from litreview_core.native_agent import ROLE_SKILLS,create_review_agent
from litreview_core.paper_review_v2 import restore_paper_review_v2
from litreview_core.section_review_v2 import restore_section_review_v2
from litreview_core.review_workflow_v2 import ReviewWorkflowV2
from litreview_core.review_release_v2 import verify_review_release_v2
from litreview_core.scientific_records import source_packet
from litreview_core.task_store import TaskStore,ScopedTaskStore


class WorkflowV2Tests(unittest.TestCase):
    def test_raw_writer_schema_retry_does_not_echo_complete_draft(self):
        self.exercise(malformed_writer=True)

    def test_closed_native_checks_bind_every_current_section_and_export(self):
        self.exercise(closed_checks=True)

    def test_closed_negative_forces_revision_before_full_review(self):
        self.exercise(closed_checks=True,closed_negative=True)

    def test_malformed_missing_component_still_forces_actual_revision(self):
        self.exercise(closed_checks=True,closed_negative=True,malformed_closed_negative=True)

    def test_selectors_complete_export_and_revision_keep_raw_observations(self):
        self.exercise(observation_mode='whole-unit-selectors/1',negative_stages={'v2-cards-review'})

    def test_whole_actual_sdk_v2_lineage_closure_four_deliveries_and_export_tamper_rejection(self):
        self.exercise()

    def test_negative_card_is_revised_before_comparison_and_original_is_preserved(self):
        self.exercise(negative_stages={'v2-cards-review'})

    def test_comparison_negative_is_revised_before_synthesis(self):
        self.exercise(negative_stages={'v2-comparison-review'})

    def test_exhausted_shared_repair_budget_stops_new_parent_and_preserves_partial(self):
        self.exercise(negative_stages={'v2-cards-review','v2-comparison-review'},max_repairs=1,expect_failure=True)

    def test_changed_source_fails_before_comparison(self):
        self.exercise(change_source=True,expect_failure=True)

    def test_no_change_writer_cannot_reroll_an_honest_negative(self):
        self.exercise(negative_stages={'v2-cards-review'},unchanged_revision=True,expect_failure=True)

    def test_original_deadline_is_not_reset_by_revision(self):
        self.exercise(expire_review=True,expect_failure=True)

    def exercise(self,negative_stages=(),max_repairs=2,expect_failure=False,change_source=False,
                 unchanged_revision=False,expire_review=False,observation_mode='quotes',
                 closed_checks=False,closed_negative=False,malformed_closed_negative=False,malformed_writer=False):
        import httpx
        def blocked(*a,**k):raise AssertionError('Zero network v2 integration')
        with tempfile.TemporaryDirectory(prefix='wf-v2-') as temporary,patch.object(socket,'create_connection',blocked), \
                patch.object(httpx.Client,'send',blocked),patch.object(httpx.AsyncClient,'send',blocked):
            root=Path(temporary);skills=root/'skills'
            for skill in set(ROLE_SKILLS.values())|{'literature-review'}:
                (skills/skill/'references').mkdir(parents=True)
                (skills/skill/'SKILL.md').write_text('---\nname: '+skill+'\ndescription: Local scripted mechanics.\n---\nUse assigned tools.',encoding='utf8')
                for ref in ('mapped-drafts.md','scientific-records.md'):
                    (skills/skill/'references'/ref).write_text('Offline mechanics, not scientific validation.',encoding='utf8')
            questions=[{'id':'q','text':'What limits the result?'}]
            packets=[source_packet('p'+str(i),b'Failure persists.',questions) for i in range(2)]
            store=TaskStore(root/'store')
            workflow=ReviewWorkflowV2(store,packets,questions,group_size=2,max_repairs=max_repairs,deadline_at=time.monotonic()+120,observation_mode=observation_mode,closed_checks=closed_checks)
            stages=[];identities=[];graphs=[];rejected=set();assignments={}
            def model(role,script):return ScriptedModel(role=role,script=script,profile={'tool_calling':True,'max_input_tokens':200000,'max_output_tokens':32768})
            async def dispatch(stage,factory,tickets=None):
                self.assertIsNotNone(tickets)
                stages.append(stage)
                if stage=='v2-comparison-draft':
                    self.assertTrue(any(s.startswith('v2-cards-review') for s in stages))
                    self.assertTrue(all(r['status']=='pending' for r in store.status() if r['id'] in tickets))
                    with store._transaction() as db:
                        dependencies={row['dependency'] for t in tickets for row in db.execute('SELECT dependency FROM dependencies WHERE task=?',(t,))}
                    accepted={row['id'] for row in store.status() if row['status']=='accepted' and row['role']=='verifier'}
                    if closed_checks:
                        self.assertTrue(dependencies<=accepted)
                        self.assertTrue(dependencies)
                    else:self.assertEqual(dependencies,accepted)
                def agent_factory(ready,workspace):
                    assigned={}
                    def parent(messages,role):
                        results=[m for m in messages if isinstance(m,ToolMessage)]
                        if not results or results[-1].name=='task':return AIMessage(content='',tool_calls=[{'id':'ready-'+str(len(messages)),'name':'ready_tasks','args':{}}])
                        data=json.loads(results[-1].content)
                        if data['frontier_complete']:return AIMessage(content='Scripted experimental protocol stage only.')
                        return AIMessage(content='',tool_calls=[{'id':'delegate-'+str(i),'name':'task','args':x} for i,x in enumerate(data['ready'])])
                    def wrapped(identity,description):
                        worker=factory(identity,description);assigned[identity.context_id]=worker.inputs
                        identities.append(identity);assignments[identity.context_id]=stage
                        return worker
                    def worker_model(identity):
                        def script(messages,role):
                            human=next(m for m in messages if isinstance(m,HumanMessage))
                            fields=re.findall(r"<assigned_input path='/inputs/([^']+)'>\n(.*?)\n</assigned_input>",human.content,re.S)
                            actual={name:json.loads(text) for name,text in fields}
                            self.assertEqual(actual,assigned[identity.context_id])
                            if role!='verifier':
                                value=scripted_submission(role,next(iter(actual.values())))
                                if malformed_writer and role=='writer':
                                    errors=[m for m in messages if isinstance(m,ToolMessage)]
                                    for message in errors:
                                        self.assertNotIn('DO_NOT_ECHO_PRIVATE_DRAFT',str(message.content))
                                    if 'bad-writer' not in rejected:
                                        rejected.add('bad-writer')
                                        value['undeclared_note']='DO_NOT_ECHO_PRIVATE_DRAFT_'*1000
                                if 'revision.json' in actual and not unchanged_revision:value['claims'][0]['text']+='（修訂版）'
                            else:
                                wire=next(iter(actual.values()))
                                if wire['schema']=='closed-scientific-check/1':
                                    from test_closed_scientific_checks import scripted_closed_submission
                                    reject=closed_negative and stage.startswith('v2-cards-closed') and 'closed' not in rejected
                                    if reject:rejected.add('closed')
                                    value=scripted_closed_submission(wire,negative=bool(reject))
                                    if reject and malformed_closed_negative:
                                        value['unit_verdicts'][0]['status']='supported'
                                        for minimum in value['unit_verdicts'][0]['minimum_checks']:minimum['conclusion']='supported'
                                        value['unit_verdicts'][0]['missing_components']=['A real scientific component is absent.']
                                        value['issues']=[]
                                    return AIMessage(content='',tool_calls=[{'id':'submit-'+identity.context_id,'name':'submit_result','args':{'data':value}}])
                                paper=wire.get('kind')=='paper' or wire['schema'].startswith('paper-review-wire/')
                                payload=restore_paper_review_v2(wire) if paper else restore_section_review_v2(wire)
                                reject=next((s for s in negative_stages if stage.startswith(s) and s not in rejected),None)
                                if reject:rejected.add(reject)
                                value=(scripted_v2 if paper else scripted_section)({'payload':payload},negative=bool(reject))
                                from test_paper_review_v2 import selected_submission
                                value=selected_submission({'payload':payload,'wire':wire},value)
                            return AIMessage(content='',tool_calls=[{'id':'submit-'+identity.context_id,'name':'submit_result','args':{'data':value}}])
                        return model(identity.role,script)
                    graph=create_review_agent(model('coordinator',parent),workspace,skills,worker_factory=wrapped,
                        worker_model_factory=worker_model,coordinator_tools=[ready],max_concurrency=2)
                    graphs.append(graph);return graph
                report=await run_frontiers(ScopedTaskStore(store,tickets),agent_factory,root/'stages'/stage,workflow.deadline_at,frontier_size=2)
                if change_source and stage.startswith('v2-cards-review'):workflow.packets[0]['parts'][0]['text']+=' changed source'
                if expire_review and stage.startswith('v2-cards-review'):workflow.deadline_at=time.monotonic()-1
                if not report['passed']:raise RuntimeError('Native stage failed '+stage)
            if expect_failure:
                with self.assertRaises((RuntimeError,ValueError,TimeoutError)):asyncio.run(workflow.run(dispatch))
                partial=workflow.partial_snapshot()
                self.assertFalse(partial['protocol_completed_experimental'])
                manifest=save_review_attempt_v2(partial,root/'unpublished',native_trace_root=root/'stages')
                self.assertFalse(manifest['publication_verified']);self.assertFalse(manifest['quality_validated'])
                self.assertFalse(manifest['protocol_completed_experimental'])
                self.assertTrue((root/'unpublished/raw/review-attempts/index.json').exists())
                if change_source or expire_review or unchanged_revision:self.assertNotIn('v2-comparison-draft',stages)
                else:
                    self.assertNotIn('v2-synthesis-0-draft',stages)
                    self.assertEqual(workflow.repair_rounds_used,1)
                return
            result=asyncio.run(workflow.run(dispatch))
            self.assertTrue(result['protocol_completed_experimental']);self.assertFalse(result['publication_verified'])
            self.assertFalse(result['quality_validated'])
            gate=verify_review_release_v2(result)
            self.assertTrue(gate['no_model_publication_root'])
            self.assertEqual(len(result['sections']),4)
            self.assertEqual(len(result['reviews']),4)
            if closed_checks:
                self.assertTrue(result['closed_checks_required'])
                self.assertEqual(set(result['closed_checks']),{s['section_id'] for s in result['sections']})
                self.assertTrue(all(result['closed_checks'].values()))
                if closed_negative:
                    self.assertEqual(workflow.repair_rounds_used,1)
                    self.assertTrue(any(a['attempt'].get('closed_check') and a['attempt'].get('semantic_negative_detected') for a in result['attempt_history']))
            self.assertFalse(any(i.role=='assembly-auditor' for i in identities))
            self.assertEqual(len({i.context_id for i in identities}),len(identities))
            self.assertTrue(all(i.task_tool_call_id and i.coordinator_context_id for i in identities))
            self.assertEqual(sum(e['event']=='task_delegated' for g in graphs for e in g.events),len(identities))
            for job in negative_stages:
                prefix=job.rsplit('-review',1)[0]
                self.assertLess(stages.index(prefix+'-revision-0'),stages.index('v2-comparison-draft' if 'cards' in job else 'v2-synthesis-0-draft'))
            if negative_stages:
                self.assertTrue(any(a['attempt']['status']=='needs_revision' for a in result['attempt_history']))
                self.assertEqual(result['repair_rounds_used'],len(negative_stages))
            manifest=export_review_v2(result,root/'delivery',deadline_at=workflow.deadline_at,native_trace_root=root/'stages')
            self.assertEqual(manifest['status'],'protocol_completed_experimental')
            self.assertFalse(manifest['publication_verified']);self.assertFalse(manifest['quality_validated'])
            if closed_checks:
                self.assertTrue(manifest['closed_checks_required'])
                self.assertTrue((root/'delivery/audit/closed-checks.json').exists())
                for damage in ('missing','changed_input','changed_raw'):
                    bad=copy.deepcopy({k:v for k,v in result.items() if k!='identities'});bad['identities']=dict(result['identities'])
                    items=next(iter(bad['closed_checks'].values()))
                    if damage=='missing':items.pop()
                    elif damage=='changed_input':items[0]['packet']['payload']['target_section_id']='changed'
                    else:items[0]['attestation']['payload']['raw_tool_arguments']['data']['unit_verdicts'][0]['reason']='changed'
                    with self.subTest(closed_damage=damage),self.assertRaises(ValueError):
                        verify_review_release_v2(bad)
            for name in ('main-review.md','evidence-cards.md','comparison-table.md','citations.json','source-spans.json','raw/native/index.json'):
                self.assertTrue((root/'delivery'/name).is_file(),name)
            for name,info in manifest['files'].items():self.assertEqual(payload_hash((root/'delivery'/name).read_bytes()),info['sha256'])
            self.assertEqual(len(list((root/'delivery/sources').glob('*.md'))),1) # distinct papers may share exact bytes
            self.assertEqual(len(json.loads((root/'delivery/citations.json').read_text(encoding='utf8'))['sources']),2)
            self.assertIn('尚未經品質對照驗收',(root/'delivery/README.md').read_text(encoding='utf8'))
            for mutation in ('paper','card','identity','text','dependency'):
                bad=copy.deepcopy({k:v for k,v in result.items() if k!='identities'});bad['identities']=dict(result['identities'])
                if mutation=='paper':bad['packets'].pop()
                if mutation=='card':bad['sections'].pop(0)
                if mutation=='identity':bad['identities'][next(iter(bad['identities']))]={}
                if mutation=='text':bad['sections'][-1]['claims'][0]['text']='unreviewed global science'
                if mutation=='dependency':
                    rootentry=bad['reviews'][bad['root_section_ids'][0]]
                    rootentry['bundle']['children'][0]['attestation']['payload']['status']='unresolved'
                with self.subTest(mutation=mutation),self.assertRaises((ValueError,KeyError)):
                    export_review_v2(bad,root/('reject-'+mutation))
                self.assertFalse((root/('reject-'+mutation)/'manifest.json').exists())
            with self.assertRaises(TimeoutError):export_review_v2(result,root/'late',deadline_at=time.monotonic()-1)


if __name__=='__main__':unittest.main()
