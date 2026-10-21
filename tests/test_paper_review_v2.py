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
    verify_paper_review_v2, save_paper_review_attempt_v2,project_paper_review_v2)
from litreview_core.review_minimum_units import minimum_claim_units
from litreview_core.paper_review_worker_v2 import make_paper_review_v2_worker
from litreview_core.reader_worker import reader_worker
from litreview_core.review_artifacts import draft_packet
from litreview_core.scientific_records import source_packet
from litreview_core.task_store import TaskStore, ScopedTaskStore
from litreview_core.review_observation_selectors import WHOLE_UNITS, whole_unit_mode


def selected_submission(bundle, data):
    """Script the transport only; scientific verdicts remain unchanged."""
    if not whole_unit_mode(bundle):
        return data
    data = copy.deepcopy(data)
    paper = bundle['wire']['kind'] == 'paper'
    owner = 'source_ref' if paper else 'premise_claim_id'
    checks = 'claim_checks' if paper else 'inference_checks'
    selectors = {r[owner]: r['selector_id'] for r in bundle['wire']['selector_index']}
    for row in data['unit_verdicts']:
        for check in row.get(checks, []):
            check['observations'] = [{'selector_id': selectors[o[owner]]}
                                     for o in check['observations']]
    return data


def scripted_v2(bundle, negative=False):
    """Literal exact fixtures only; all semantic judgments are scripted."""
    p = bundle['payload']
    claims = {c['local_id']: c for c in p['card']['claims']}
    parts = {p['source']['paper_id']+'/'+x['part_id']: x['text'] for x in p['source']['parts']}
    rows = []
    for unit in p['required_units']:
        row = {'unit_id': unit['unit_id'], 'status': 'supported',
               'reason': 'Scripted test only; no scientific quality claim', 'claim_checks': []}
        if unit['kind'] == 'claim_support':
            claim = claims[unit['claim_id']]
            ref = claim['evidence_refs'][0]
            row['claim_checks'] = [{'minimum_unit_id': mid,
                'observations': [{'source_ref': ref, 'quote': parts[ref]}],
                'source_relation': 'direct', 'claim_relation': 'Scripted mechanics',
                'qualification_check': 'Scripted mechanics', 'conclusion': 'supported',
                'reason': 'Literal location only; no semantic model was used'} for mid in unit['minimum_unit_ids']]
        rows.append(row)
    issues = []
    if negative:
        rows[0]['status'] = 'needs_revision'
        rows[0]['claim_checks'][0]['conclusion'] = 'needs_revision'
        issues = [{'unit_ids': [rows[0]['unit_id']], 'description': 'Scripted scientific defect',
                   'correction': 'Revise original card, never erase negative for format repair'}]
    return {'unit_verdicts': rows, 'new_omissions': [], 'issues': issues}


class PaperReviewV2Tests(unittest.TestCase):
    def setUp(self):
        fixture = planner_fixture.ProofPlannerTests()
        fixture.setUp()
        self.source, self.record, self.card = fixture.packets[0], fixture.records[0], fixture.cards[0]
        self.bundle = plan_paper_review_v2(self.source, self.record, self.card)

    def test_original_reader_card_render_roundtrip_exact_and_single_text_values(self):
        b = self.bundle
        self.assertEqual(restore_paper_review_v2(b['wire']), b['payload'])
        self.assertEqual(validate_paper_bundle_v2(b), b['payload'])
        table = b['wire']['text_table']
        self.assertEqual(len(table), len(set(table.values())))
        for part in self.source['parts']:
            self.assertEqual(list(table.values()).count(part['text']), 1)
        for claim in self.card['claims']:
            self.assertEqual(list(table.values()).count(claim['text']), 1)
        self.assertEqual(len(b['payload']['required_units']), len(self.card['claims'])+len(self.record['obligations'])+2)
        self.assertEqual(b['wire']['objects']['render']['text'],b['payload']['render']['text'])
        self.assertFalse(b['diagnostics']['publication_verified'])
        self.assertFalse(b['diagnostics']['complete_request_budget_checked'])

    def test_scientific_verdict_and_important_omission_preserved(self):
        data = scripted_v2(self.bundle, negative=True)
        actual, status = check_submission_v2(self.bundle, data)
        self.assertEqual(status, 'needs_revision')
        self.assertEqual(actual, data)
        data = scripted_v2(self.bundle)
        data['new_omissions'] = [{'source_refs': [self.source['paper_id']+'/p0001'],
            'description': 'Scripted missing design qualification', 'importance': 'Affects interpretation',
            'affected_target_ids': []}]
        self.assertEqual(check_submission_v2(self.bundle, data)[1], 'needs_revision')

    def test_all_missing_unknown_duplicate_duties_diagnosed_together(self):
        value = scripted_v2(self.bundle)
        value['unit_verdicts'] = [value['unit_verdicts'][0], value['unit_verdicts'][0],
            {**value['unit_verdicts'][0], 'unit_id': 'unknown'}]
        with self.assertRaisesRegex(ReviewV2Error, 'missing.*unknown.*duplicates'):
            check_submission_v2(self.bundle, value)

    def test_minimum_ids_need_exact_coverage_without_model_retyping(self):
        value = scripted_v2(self.bundle)
        check=value['unit_verdicts'][0]['claim_checks'][0]
        self.assertNotIn('clause',check)
        check['minimum_unit_id']='foreign'
        with self.assertRaisesRegex(ReviewV2Error, 'Minimum-unit inventory'):
            check_submission_v2(self.bundle, value)

    def test_literal_quote_feedback_identifies_observation_without_echoing_submission(self):
        value=scripted_v2(self.bundle)
        row=value['unit_verdicts'][0]
        check=row['claim_checks'][0]
        observation=check['observations'][0]
        observation['quote']='UNMATCHED_QUOTE_MUST_NOT_BE_ECHOED'
        before=copy.deepcopy(value)
        with self.assertRaises(ReviewV2Error) as caught:
            check_submission_v2(self.bundle,value)
        message=str(caught.exception)
        self.assertIn('unit='+row['unit_id'],message)
        self.assertIn('minimum_unit='+check['minimum_unit_id'],message)
        self.assertIn('claim_checks[0].observations[0]',message)
        self.assertIn('source_ref='+observation['source_ref'],message)
        self.assertNotIn(observation['quote'],message)
        self.assertEqual(value,before)

    def test_borrowed_ref_absent_quote_and_negative_clause_rejected(self):
        original = scripted_v2(self.bundle)
        for operation, error in ((lambda v: v['unit_verdicts'][0]['claim_checks'][0]['observations'][0].update(source_ref=self.source['paper_id']+'/p0001'), 'undeclared'),
                                 (lambda v: v['unit_verdicts'][0]['claim_checks'][0]['observations'][0].update(quote='absent fabricated quotation'), 'Literal'),
                                 (lambda v: v['unit_verdicts'][0]['claim_checks'][0].update(conclusion='unresolved'), 'negative minimum')):
            value = copy.deepcopy(original)
            operation(value)
            with self.assertRaisesRegex(ReviewV2Error, error):
                check_submission_v2(self.bundle, value)

    def test_missing_raw_obligation_source_or_render_invalidates_bundle(self):
        for mutation in ('unit', 'source', 'reader', 'render', 'wire'):
            value = copy.deepcopy(self.bundle)
            if mutation == 'unit': value['payload']['required_units'].pop()
            if mutation == 'source': value['payload']['source']['parts'][0]['text'] += 'tampered'
            if mutation == 'reader': value['payload']['reader']['obligations'].pop()
            if mutation == 'render': value['payload']['render']['text'] += 'new unreviewed science'
            if mutation == 'wire': value['wire']['text_table'][next(iter(value['wire']['text_table']))] += 'tampered'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_paper_bundle_v2(value)

    def test_oversize_rejected_never_truncated(self):
        with self.assertRaisesRegex(ReviewV2Error, 'OVERSIZED'):
            plan_paper_review_v2(self.source,self.record,self.card,wire_counter=lambda p:200001)
        self.assertEqual(self.source['parts'][0]['text'], self.bundle['payload']['source']['parts'][0]['text'])

    def test_unknown_or_unreferenced_wire_values_rejected(self):
        for mutation in ('unknown', 'unused'):
            value = project_paper_review_v2(self.bundle['payload'],encoding='paper-review-wire/2')
            if mutation == 'unknown': value['objects']['source']['parts'][0]['text'] = {'$text':'missing'}
            else: value['text_table']['hidden'] = 'unreviewed scientific claim'
            with self.assertRaises(ReviewV2Error): restore_paper_review_v2(value)

    def test_minimum_units_preserve_punctuation_spaces_and_every_claim(self):
        claims=[{'local_id':'c','text':' 風險可能增加；成本未知。  '},{'local_id':'d','text':'CI [-.02,.04] includes zero.'}]
        units=minimum_claim_units(claims)
        for claim in claims:
            selected=[u for u in units if u['claim_id']==claim['local_id']]
            self.assertEqual(''.join(u['text'] for u in selected),claim['text'])
            self.assertEqual(selected[0]['start_char'],0)
            self.assertEqual(selected[-1]['end_char'],len(claim['text']))
        self.assertEqual(len({u['minimum_unit_id'] for u in units}),len(units))
        with self.assertRaises(ValueError):minimum_claim_units(claims+[claims[0]])

    def test_old_text_table_and_new_column_rows_are_explicit_and_lossless(self):
        for version in ('paper-review-wire/2','paper-review-wire/2.1'):
            wire=project_paper_review_v2(self.bundle['payload'],encoding=version)
            self.assertEqual(wire['schema'],version)
            self.assertEqual(restore_paper_review_v2(wire),self.bundle['payload'])
            self.assertEqual(wire['objects']['render']['text'],self.bundle['payload']['render']['text'])

    def test_metadata_rows_reject_duplicate_alias_unknown_ref_and_malformed_rows(self):
        original=self.bundle['wire']
        for mutation in ('duplicate_alias','unknown_alias','row_length','duplicate_column'):
            wire=copy.deepcopy(original)
            index=wire['opaque_id_index']
            if mutation=='duplicate_alias':index[wire['opaque_alias_prefix']+'9999']=next(iter(index.values()))
            if mutation=='unknown_alias':wire['objects']['source']['source_sha256']=wire['opaque_alias_prefix']+'9999'
            if mutation=='row_length':wire['objects']['reader']['fields']['$rows'][0].pop()
            if mutation=='duplicate_column':wire['objects']['reader']['fields']['$columns'][0]=wire['objects']['reader']['fields']['$columns'][1]
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):restore_paper_review_v2(wire)

    def test_encoding_or_minimum_unit_mutation_invalidates_actual_hash_binding(self):
        for mutation in ('wire','minimum','rehashed_alias_swap'):
            bundle=copy.deepcopy(self.bundle)
            if mutation=='wire':bundle['wire']['opaque_alias_prefix']+='changed'
            elif mutation=='minimum':bundle['payload']['minimum_units'][0]['text']='hidden changed science'
            else:
                index=bundle['wire']['opaque_id_index'];a,b=list(index)[:2]
                index[a],index[b]=index[b],index[a]
                bundle['wire_sha256']=payload_hash(bundle['wire'])
            with self.assertRaises(ValueError):validate_paper_bundle_v2(bundle)

    def test_missing_duplicate_minimum_ids_report_all_affected_claims(self):
        value=scripted_v2(self.bundle)
        value['unit_verdicts'][0]['claim_checks']*=2
        value['unit_verdicts'][1]['claim_checks']=[]
        with self.assertRaises(ReviewV2Error) as caught:check_submission_v2(self.bundle,value)
        for term in ('u1','u2','missing','duplicates'):self.assertIn(term,str(caught.exception))


class NativePaperReviewV2Tests(unittest.TestCase):
    def test_real_sdk_selectors_preserve_raw_replay_and_negative(self):
        self.exercise(observation_mode=WHOLE_UNITS)
        self.exercise(negative=True, observation_mode=WHOLE_UNITS)
        self.exercise(negative=True, malformed=True, observation_mode=WHOLE_UNITS)

    def test_real_sdk_reader_writer_review_task_lineage_and_mechanical_gate(self):
        self.exercise()

    def test_real_sdk_negative_terminal_and_invalid_negative_not_format_retried(self):
        self.exercise(negative=True)
        self.exercise(negative=True, malformed=True)

    def exercise(self, negative=False, malformed=False, observation_mode='quotes'):
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
                return make_paper_review_v2_worker(b,identity,trusted_identities=registry,save=save)
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
                            if role!='verifier': data=scripted_submission(role,next(iter(actual.values())))
                            else:
                                self.assertEqual(restore_paper_review_v2(actual['paper-review-v2.json']),state['bundle']['payload'])
                                data=selected_submission(state['bundle'],scripted_v2(state['bundle'],negative))
                                if malformed: data['unit_verdicts']=data['unit_verdicts'][:1]
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
            if negative:
                self.assertFalse(asyncio.run(stage(vt))['passed'])
            else:
                self.assertTrue(asyncio.run(stage(vt))['passed'])
            reviewer=next(i for i in identities if i.role=='verifier')
            self.assertEqual(calls.count(reviewer.context_id),1)
            self.assertEqual(len(identities),3)
            self.assertTrue(all(i.task_tool_call_id and i.coordinator_context_id for i in identities))
            self.assertEqual(len({i.context_id for i in identities}),3)
            self.assertEqual(len(attempts),1)
            archive=save_paper_review_attempt_v2(state['bundle'],attempts,root/'unpublished')
            self.assertFalse(json.loads(archive.read_text(encoding='utf-8'))['publication_verified'])
            if malformed:
                self.assertEqual(attempts[0]['status'],'invalid')
                self.assertIn('validation_error',attempts[0])
                self.assertEqual(attempts[0]['raw_tool_arguments']['data']['unit_verdicts'][0]['status'],'needs_revision')
            else:
                att=attempts[0]['attestation']
                gate=verify_paper_review_v2(state['bundle'],att,trusted_identities=registry)
                self.assertEqual(gate['qualified_for_experiment'],not negative)
                self.assertFalse(gate['publication_verified'])
                if observation_mode == WHOLE_UNITS:
                    selection=att['payload']['observation_selection']
                    self.assertEqual(selection['raw_tool_arguments'],attempts[0]['raw_tool_arguments'])
                    self.assertIn('selector_id',selection['raw_tool_arguments']['data']['unit_verdicts'][0]['claim_checks'][0]['observations'][0])
                    self.assertIn('quote',att['payload']['submission']['unit_verdicts'][0]['claim_checks'][0]['observations'][0])
                    damaged=copy.deepcopy(att)
                    damaged['payload']['observation_selection']['raw_tool_arguments']['data']['unit_verdicts'][0]['reason']='Changed raw verdict'
                    damaged['payload_sha256']=payload_hash(damaged['payload'])
                    with self.assertRaises(ValueError):
                        verify_paper_review_v2(state['bundle'],damaged,trusted_identities=registry)
                for mutation in ('identity','self_review','render','aggregate'):
                    b=copy.deepcopy(state['bundle']); a=copy.deepcopy(att); ids=dict(registry)
                    if mutation=='identity': ids[reviewer.context_id]=reviewer.as_dict()
                    if mutation=='self_review': ids[reviewer.context_id]=replace(ids[reviewer.context_id],ancestor_context_ids=(state['writer']['writer_execution_id'],))
                    if mutation=='render': b['payload']['render']['text']+='tampered'
                    if mutation=='aggregate': a['payload']['publication_verified']=True; a['payload_sha256']=payload_hash(a['payload'])
                    with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                        verify_paper_review_v2(b,a,trusted_identities=ids)


if __name__=='__main__':
    unittest.main()
