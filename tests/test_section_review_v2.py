"""Zero-network v2 mechanics, NOT evidence of scientific judgment quality."""
import asyncio
import copy
from dataclasses import replace
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'skills/literature-review/scripts/runtime')]
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from test_native_agent import ScriptedModel
import test_proof_planner as planner_fixture
from test_review_workflow_native_sdk import scripted_submission
from litreview_core.coordinator_frontier import run_frontiers
from litreview_core.draft_worker import draft_worker
from litreview_core.hierarchical_proof import RuntimeIdentity, payload_hash
from litreview_core.native_agent import ROLE_SKILLS, create_review_agent
from litreview_core.paper_review_v2 import (ReviewV2Error, check_submission_v2,
    plan_paper_review_v2, restore_paper_review_v2, validate_paper_bundle_v2,
    verify_paper_review_v2, save_paper_review_attempt_v2)
from litreview_core.paper_review_worker_v2 import make_paper_review_v2_worker
from litreview_core.reader_worker import reader_worker
from litreview_core.review_artifacts import draft_packet, validate_draft
from litreview_core.scientific_records import source_packet
from litreview_core.task_store import TaskStore, ScopedTaskStore


from test_paper_review_v2 import scripted_v2, selected_submission
from litreview_core.review_observation_selectors import WHOLE_UNITS
from litreview_core.section_review_v2 import (plan_section_review_v2, section_draft_packet_v2, restore_section_review_v2, verify_section_review_v2, check_section_submission_v2)
from litreview_core.section_review_worker_v2 import make_section_review_v2_worker

def scripted_section(bundle, negative=False):
    p = bundle['payload']
    claims = {c['local_id']: c for c in p['section']['claims']}
    premises = {v['section']['section_id']+'/'+c['local_id']: c for v in p['direct_premises'] for c in v['section']['claims']}
    rows=[]
    for u in p['required_units']:
        row={'unit_id':u['unit_id'],'status':'supported','reason':'Scripted mechanics only','inference_checks':[]}
        if u['kind']=='new_inference':
            claim=claims[u['claim_id']]; ref=claim['premise_claim_ids'][0]
            row['inference_checks']=[{'minimum_unit_id':mid,'observations':[{'premise_claim_id':ref,'quote':premises[ref]['text']}],
                'premise_relation':'direct','inference_relation':'Scripted only','qualification_check':'Scripted only',
                'conclusion':'supported','reason':'Scripted mechanics only'} for mid in u['minimum_unit_ids']]
        rows.append(row)
    issues=[]
    if negative:
        rows[0]['status']='needs_revision'; rows[0]['inference_checks'][0]['conclusion']='needs_revision'
        issues=[{'unit_ids':[rows[0]['unit_id']],'description':'Scientific defect fixture','correction':'Revise original'}]
    return {'unit_verdicts':rows,'issues':issues}

class NativeSectionReviewV2Tests(unittest.TestCase):
    def test_real_sdk_selectors_nested_dependencies_and_negative(self):
        self.exercise(observation_mode=WHOLE_UNITS)
        self.exercise(negative=True, observation_mode=WHOLE_UNITS)
        self.exercise(excluded=True, observation_mode=WHOLE_UNITS)

    def test_real_sdk_reader_writer_review_task_lineage_and_mechanical_gate(self):
        self.exercise()

    def test_real_sdk_negative_terminal_and_invalid_negative_not_format_retried(self):
        self.exercise(negative=True)
        self.exercise(negative=True, malformed=True)

    def test_excluded_direct_premise_still_delivered_and_reviewed(self):
        self.exercise(excluded=True)

    def exercise(self, negative=False, malformed=False, excluded=False, observation_mode='quotes'):
        import httpx
        def blocked(*args, **kwargs): raise AssertionError('No network in v2 integration')
        with tempfile.TemporaryDirectory(prefix='paper-v2-') as temporary, \
                patch.object(socket,'create_connection',blocked), \
                patch.object(httpx.Client,'send',blocked), \
                patch.object(httpx.AsyncClient,'send',blocked):
            root=Path(temporary)
            skills=root/'skills'
            for skill in set(ROLE_SKILLS.values())|{'literature-review'}:
                (skills/skill/'references').mkdir(parents=True)
                (skills/skill/'SKILL.md').write_text('---\nname: '+skill+'\ndescription: Zero network mechanics.\n---\nUse assigned typed tools.',encoding='utf-8')
                for ref in ('scientific-records.md','mapped-drafts.md'):
                    (skills/skill/'references'/ref).write_text('Scripted mechanics only.',encoding='utf-8')
            source=source_packet('p',b'Failure persists.',[{'id':'q','text':'What limits the result?'}])
            store=TaskStore(root/'store')
            registry, attempts, bundles, captured, identities, calls = {}, [], [], [], [], []
            rt=store.create('reader',source,max_attempts=1)
            state={}
            def register(identity,ticket,artifact):
                row=next(r for r in store.status() if r['id']==ticket)
                registry[identity.context_id]=RuntimeIdentity(execution_id=identity.context_id,
                    context_id=identity.context_id,role=identity.role,input_hashes={ticket:row['input_hash']},
                    output_hashes={ticket:row['output_hash']},task_call_id=identity.task_tool_call_id,
                    parent_context_id=identity.coordinator_context_id)
                state[identity.role]=artifact
            def factory(identity, description):
                identities.append(identity)
                ticket=json.loads(description)['ticket']
                if identity.role in ('reader','writer'):
                    def accepted(t,artifact,receipt): register(identity,t,artifact)
                    return (reader_worker if identity.role=='reader' else draft_worker)(store,identity,ticket,on_accepted=accepted)
                lease=store.claim(ticket,identity.role,identity.context_id)
                b=state['bundle']
                def save(attempt, execution):
                    attempts.append(attempt)
                    store.put(attempt)
                    if execution is not None: registry[execution.context_id]=execution
                    if attempt['status']=='passed':
                        return store.accept(ticket,identity.context_id,lease['lease'],attempt['attestation'],validator=lambda p,v:None)
                    if attempt['status']!='invalid' or negative:
                        store.fail(ticket,identity.context_id,lease['lease'],{'reason':'Original negative retained','attempt_sha256':payload_hash(attempt)})
                maker = make_section_review_v2_worker if state.get('upper') else make_paper_review_v2_worker
                return maker(b,identity,trusted_identities=registry,save=save)
            def model(role,script):
                return ScriptedModel(role=role,script=script,profile={'tool_calling':True,'max_input_tokens':200000,'max_output_tokens':32768})
            async def stage(ticket):
                def agent_factory(ready, workspace):
                    assigned={}
                    def parent(messages,role):
                        results=[m for m in messages if isinstance(m,ToolMessage)]
                        if not results or results[-1].name=='task':
                            return AIMessage(content='',tool_calls=[{'id':'ready-'+str(len(messages)),'name':'ready_tasks','args':{}}])
                        data=json.loads(results[-1].content)
                        if data['frontier_complete']: return AIMessage(content='Mechanics only, never publish.')
                        return AIMessage(content='',tool_calls=[{'id':'delegate-'+str(i),'name':'task','args':x} for i,x in enumerate(data['ready'])])
                    def wrapped(identity,description):
                        worker=factory(identity,description)
                        assigned[identity.context_id]=worker.inputs
                        return worker
                    def worker_model(identity):
                        def script(messages,role):
                            calls.append(identity.context_id)
                            human=next(m for m in messages if isinstance(m,HumanMessage))
                            fields=re.findall(r"<assigned_input path='/inputs/([^']+)'>\n(.*?)\n</assigned_input>",human.content,re.DOTALL)
                            actual={name:json.loads(text) for name,text in fields}
                            self.assertEqual(actual,assigned[identity.context_id])
                            captured.append(actual)
                            if role!='verifier':
                                data=scripted_submission(role,next(iter(actual.values())))
                                if excluded and role=='writer' and state.get('writing_upper'):
                                    data['retention_groups'][0].update(status='excluded',claim_ids=[],reason='Scripted exclusion still must be reviewed')
                            else:
                                upper=state.get('upper',False)
                                key='section-review-v2.json' if upper else 'paper-review-v2.json'
                                restore=restore_section_review_v2 if upper else restore_paper_review_v2
                                self.assertEqual(restore(actual[key]),state['bundle']['payload'])
                                data=selected_submission(state['bundle'],(scripted_section if upper else scripted_v2)(state['bundle'],negative and upper))
                                if malformed and upper: data['unit_verdicts']=data['unit_verdicts'][:1]
                            return AIMessage(content='',tool_calls=[{'id':'submit-'+identity.context_id,'name':'submit_result','args':{'data':data}}])
                        return model(identity.role,script)
                    return create_review_agent(model('coordinator',parent),workspace,skills,
                        worker_factory=wrapped,worker_model_factory=worker_model,coordinator_tools=[ready],max_concurrency=1)
                return await run_frontiers(ScopedTaskStore(store,[ticket]),agent_factory,root/('stage-'+ticket),time.monotonic()+120,frontier_size=1)
            self.assertTrue(asyncio.run(stage(rt))['passed'])
            record=state['reader']
            wt=store.create('writer',draft_packet('paper_card',[source],[record],source['questions']),dependencies=[rt],max_attempts=1)
            self.assertTrue(asyncio.run(stage(wt))['passed'])
            state['bundle']=plan_paper_review_v2(source,record,state['writer'],observation_mode=observation_mode)
            vt=store.create('verifier',{'review_id':state['bundle']['review_id']},dependencies=[wt],max_attempts=1)
            self.assertTrue(asyncio.run(stage(vt))['passed'])
            children=[{'bundle':copy.deepcopy(state['bundle']),'attestation':attempts[0]['attestation']}]
            state['writing_upper']=True
            packet=section_draft_packet_v2(children,trusted_identities=registry,questions=source['questions'])
            wt=store.create('writer',packet,dependencies=[vt],max_attempts=1)
            self.assertTrue(asyncio.run(stage(wt))['passed'])
            state['bundle']=plan_section_review_v2(state['writer'],children,questions=source['questions'],trusted_identities=registry,observation_mode=observation_mode)
            state['upper']=True
            attempts.clear()
            vt=store.create('verifier',{'review_id':state['bundle']['review_id']},dependencies=[wt],max_attempts=1)
            if negative:
                self.assertFalse(asyncio.run(stage(vt))['passed'])
            else:
                self.assertTrue(asyncio.run(stage(vt))['passed'])
            reviewer=[i for i in identities if i.role=='verifier'][-1]
            self.assertEqual(calls.count(reviewer.context_id),1)
            self.assertEqual(len(identities),5)
            self.assertTrue(all(i.task_tool_call_id and i.coordinator_context_id for i in identities))
            self.assertEqual(len({i.context_id for i in identities}),5)
            self.assertEqual(len(attempts),1)
            self.assertFalse(attempts[0]['publication_verified'])
            if malformed:
                self.assertEqual(attempts[0]['status'],'invalid')
                self.assertIn('validation_error',attempts[0])
                self.assertEqual(attempts[0]['raw_tool_arguments']['data']['unit_verdicts'][0]['status'],'needs_revision')
            else:
                att=attempts[0]['attestation']
                gate=verify_section_review_v2(state['bundle'],att,trusted_identities=registry)
                self.assertEqual(gate['qualified_for_experiment'],not negative)
                self.assertFalse(gate['publication_verified'])
                if observation_mode == WHOLE_UNITS:
                    selection=att['payload']['observation_selection']
                    self.assertEqual(selection['raw_tool_arguments'],attempts[0]['raw_tool_arguments'])
                    self.assertIn('selector_id',selection['raw_tool_arguments']['data']['unit_verdicts'][0]['inference_checks'][0]['observations'][0])
                    self.assertIn('quote',att['payload']['submission']['unit_verdicts'][0]['inference_checks'][0]['observations'][0])
                bundle=state['bundle']
                retention_units=[u for u in bundle['payload']['required_units'] if u['kind']=='premise_retention']
                self.assertEqual(len(retention_units),sum(len(p['section']['claims']) for p in bundle['payload']['direct_premises']))
                if excluded: self.assertEqual(bundle['payload']['section']['retention'][0]['status'],'excluded')
                # A qualified upper review can become an exact dependency, retaining original closure host-side.
                next_children=[{'bundle':bundle,'attestation':att}]
                if negative:
                    with self.assertRaisesRegex(ReviewV2Error,'Negative or unresolved'):
                        section_draft_packet_v2(next_children,trusted_identities=registry,questions=source['questions'])
                else:
                    next_packet=section_draft_packet_v2(next_children,trusted_identities=registry,questions=source['questions'])
                    draft={k:copy.deepcopy(bundle['payload']['section'][k]) for k in ('claims','retention','cells')}
                    for claim in draft['claims']:
                        claim['premise_claim_ids']=[o['premise_claim_id'] for o in next_packet['obligations']]
                    draft['retention']=[{'obligation_id':o['id'],'status':'included','claim_ids':[draft['claims'][0]['local_id']],'reason':'Scripted'} for o in next_packet['obligations']]
                    next_section=validate_draft(next_packet,draft,execution_id='structural-next-writer')
                    next_bundle=plan_section_review_v2(next_section,next_children,questions=source['questions'],trusted_identities=registry)
                    self.assertEqual(next_bundle['payload']['source_versions'],bundle['payload']['source_versions'])
                    self.assertEqual(next_bundle['payload']['direct_premises'][0]['section'],bundle['payload']['section'])
                for mutation in ('v1','stale_attestation','missing_claim','negative'):
                    damaged=copy.deepcopy(children)
                    if mutation=='v1': damaged[0]['bundle']['schema']='legacy-proof/1'
                    if mutation=='stale_attestation': damaged[0]['attestation']['payload_sha256']='stale'
                    if mutation=='missing_claim': damaged[0]['bundle']['payload']['card']['claims'].pop()
                    if mutation=='negative': damaged[0]['attestation']['payload']['status']='needs_revision'
                    with self.subTest(dependency=mutation),self.assertRaises(ValueError):
                        section_draft_packet_v2(damaged,trusted_identities=registry,questions=source['questions'])
                for mutation in ('missing','duplicate','borrowed','quote','negative','retention','render_duty'):
                    bad=scripted_section(bundle)
                    checks=bad['unit_verdicts'][0]['inference_checks']
                    if mutation=='missing': checks.clear()
                    if mutation=='duplicate': checks.append(copy.deepcopy(checks[0]))
                    if mutation=='borrowed': checks[0]['observations'][0]['premise_claim_id']='foreign/c1'
                    if mutation=='quote': checks[0]['observations'][0]['quote']='invented quote absent'
                    if mutation=='negative': checks[0]['conclusion']='unresolved'
                    if mutation=='retention': bad['unit_verdicts']=[v for v in bad['unit_verdicts'] if v['unit_id']!=retention_units[0]['unit_id']]
                    if mutation=='render_duty': bad['unit_verdicts'].pop()
                    with self.subTest(submission=mutation),self.assertRaises(ValueError):
                        check_section_submission_v2(bundle,bad,trusted_identities=registry)
                value=scripted_section(state['bundle'])
                value['unit_verdicts'][0]['inference_checks'][0]['minimum_unit_id']='foreign'
                with self.assertRaisesRegex(ReviewV2Error,'Minimum-unit'):
                    check_section_submission_v2(state['bundle'],value,trusted_identities=registry)
                self.assertNotIn('source',state['bundle']['payload'])
                self.assertNotIn('reader',state['bundle']['payload'])
                wire=state['bundle']['wire']
                if observation_mode == WHOLE_UNITS: wire=wire['base_wire']
                self.assertEqual(wire['objects']['render']['text'],state['bundle']['payload']['render']['text'])
                for premise in state['bundle']['payload']['direct_premises']:
                    self.assertTrue(premise['section']['claims'])
                    self.assertTrue(premise['render']['text'])

                for mutation in ('identity','self_review','render','aggregate'):
                    b=copy.deepcopy(state['bundle']); a=copy.deepcopy(att); ids=dict(registry)
                    if mutation=='identity': ids[reviewer.context_id]=reviewer.as_dict()
                    if mutation=='self_review': ids[reviewer.context_id]=replace(ids[reviewer.context_id],ancestor_context_ids=(state['writer']['writer_execution_id'],))
                    if mutation=='render': b['payload']['render']['text']+='tampered'
                    if mutation=='aggregate': a['payload']['publication_verified']=True; a['payload_sha256']=payload_hash(a['payload'])
                    with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                        verify_section_review_v2(b,a,trusted_identities=ids)


if __name__=='__main__':
    unittest.main()
