"""Zero-network mechanics; scripted judgments do not establish science quality."""
import asyncio
import copy
from dataclasses import replace
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'skills/literature-review/scripts/runtime')]
from langchain_core.messages import AIMessage,HumanMessage,ToolMessage
from test_native_agent import ScriptedModel,ToolRecordingModel
import test_proof_planner as fixture
from test_paper_review_v2 import scripted_v2
from test_review_workflow_native_sdk import scripted_submission
from litreview_core.closed_scientific_checks import (ClosedCheckError,ClosedCheckNegative,
    plan_closed_checks,make_closed_check_worker,verify_closed_attestation)
from litreview_core.coordinator_frontier import run_frontiers
from litreview_core.draft_worker import draft_worker
from litreview_core.hierarchical_proof import RuntimeIdentity,payload_hash
from litreview_core.native_agent import ROLE_SKILLS,WorkerIdentity,create_review_agent
from litreview_core.paper_review_v2 import plan_paper_review_v2,verify_paper_review_v2
from litreview_core.reader_worker import reader_worker
from litreview_core.review_artifacts import draft_packet,validate_draft
from litreview_core.scientific_records import source_packet
from litreview_core.section_review_v2 import plan_section_review_v2,section_draft_packet_v2
from litreview_core.task_store import TaskStore,ScopedTaskStore


def scripted_closed_submission(packet,negative=False):
    """Public fixture for real SDK integration, never a semantic model result."""
    p=packet['payload'];rows=[]
    source=list(p['source_material_ids'])
    observations=source if p['check_kind']=='claim' else [m['material_id'] for m in p['materials']]
    for u in p['required_units']:
        row={'unit_id':u['unit_id'],'status':'supported','reason':'Scripted mechanics only.',
             'observations':list(observations),'minimum_checks':[],'missing_components':[]}
        for mid in u.get('minimum_unit_ids',[]):
            row['minimum_checks'].append({'minimum_unit_id':mid,'conclusion':'supported',
                'observations':list(source),'source_relation':'direct','claim_relation':'Scripted mechanics.',
                'qualification_check':'Scripted mechanics.','reason':'No scientific model was used.',
                'missing_components':[]})
        rows.append(row)
    issues=[]
    if negative:
        rows[0]['status']='needs_revision'
        if rows[0]['minimum_checks']:rows[0]['minimum_checks'][0]['conclusion']='needs_revision'
        issues=[{'unit_ids':[rows[0]['unit_id']],'description':'Scripted scientific defect.',
                 'correction':'Revise original scientific artifact; preserve this negative.'}]
    return {'unit_verdicts':rows,'issues':issues}


class ClosedScientificChecksTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ProofPlannerTests();self.f.setUp();self.registry={}
        # Host fixture lineage for structural unit tests. The SDK test below
        # obtains reader, writer AND reviewer identities from real task calls.
        for source,record,card in zip(self.f.packets,self.f.records,self.f.cards):
            for context,role,artifact in ((record['execution_id'],'reader',record),
                                          (card['writer_execution_id'],'writer',card)):
                self.registry[context]=RuntimeIdentity(execution_id=context,context_id=context,role=role,
                    input_hashes={'fixture-input':payload_hash(source)},output_hashes={'fixture-output':payload_hash(artifact)},
                    task_call_id='host-fixture-'+context,parent_context_id='host-fixture-parent')
        self.bundle=plan_paper_review_v2(self.f.packets[0],self.f.records[0],self.f.cards[0])
        self.packets=plan_closed_checks(self.bundle,trusted_identities=self.registry)

    def identity(self,context='closed-fixture'):
        return WorkerIdentity(context_id=context,role='verifier',skill='verify-citations',workspace=Path('.'),
            coordinator_context_id='fixture-closed-parent',task_tool_call_id='fixture-task-'+context,
            parent_model_message_id='fixture-parent-message',parent_response_id=None,
            description_sha256=payload_hash('fixture description'),skill_sha256=payload_hash('fixture skill'))

    def accept(self,packet,value=None):
        attempts=[];registry=dict(self.registry)
        def save(attempt,execution):
            attempts.append(attempt)
            if execution is not None:registry[execution.context_id]=execution
            return {'saved':True,'status':'accepted'}
        identity=self.identity()
        worker=make_closed_check_worker(packet,identity,save=save)
        raw={'data':value if value is not None else scripted_closed_submission(packet)}
        receipt=worker.accept(raw,identity)
        return attempts[-1]['attestation'],registry,attempts,receipt

    def test_planner_claims_and_retention_are_exact_closed_scopes_and_original_ids(self):
        p=self.bundle['payload'];claim_packets=[x for x in self.packets if x['payload']['check_kind']=='claim']
        self.assertEqual(len(claim_packets),len(p['card']['claims']))
        for packet in claim_packets:
            q=packet['payload'];self.assertEqual(packet['check_id'],payload_hash(q))
            mats={m['material_id']:m for m in q['materials']};claim=mats[q['target_material_ids'][0]]['value']
            refs={mats[mid]['value']['source_ref'] for mid in q['source_material_ids']}
            self.assertEqual(refs,set(claim['evidence_refs']))
            self.assertFalse(any(m['role'] in ('finding','named_destination') for m in q['materials']))
            self.assertEqual(''.join(m['text'] for m in q['minimum_units']),claim['text'])
        retention=[x for x in self.packets if x['payload']['check_kind']=='retention']
        original={u['unit_id'] for u in p['required_units'] if u['kind']=='raw_retention'}
        actual=[u['unit_id'] for x in retention for u in x['payload']['required_units']]
        self.assertEqual(set(actual),original);self.assertEqual(len(actual),len(set(actual)))
        self.assertLess(len(retention),len(original))
        for packet in retention:
            q=packet['payload'];mats={m['material_id']:m for m in q['materials']}
            dest=[mats[mid]['value']['local_id'] for mid in q['destination_material_ids']]
            self.assertEqual(dest,q['retention']['disposition']['claim_ids'])
            self.assertEqual(sum(m['role']=='finding' for m in q['materials']),1)
            self.assertEqual(q['minimum_units'],[])

    def test_roundtrip_actual_attestation_raw_defaults_hashes_and_identity(self):
        packet=self.packets[0];data=scripted_closed_submission(packet)
        data.pop('issues')
        for row in data['unit_verdicts']:row.pop('missing_components')
        att,registry,attempts,receipt=self.accept(packet,data)
        self.assertEqual(receipt['status'],'accepted')
        self.assertEqual(receipt['check_status'],'passed')
        gate=verify_closed_attestation(packet,att,trusted_identities=registry)
        self.assertTrue(gate['qualified_for_experiment']);self.assertFalse(gate['publication_verified'])
        self.assertEqual(att['payload']['raw_sha256'],payload_hash({'data':data}))
        self.assertNotIn('issues',att['payload']['raw_tool_arguments']['data'])
        self.assertEqual(att['payload']['submission']['issues'],[])
        self.assertEqual(attempts[0]['raw_tool_arguments'],{'data':data})
        self.assertEqual(dict(registry['closed-fixture'].input_hashes),{'closed-check.json':payload_hash(packet)})
        retention=next(p for p in self.packets if p['payload']['check_kind']=='retention')
        data=scripted_closed_submission(retention);data.pop('issues')
        for row in data['unit_verdicts']:
            row.pop('minimum_checks');row.pop('missing_components')
        att,ids,_,_=self.accept(retention,data)
        self.assertTrue(verify_closed_attestation(retention,att,trusted_identities=ids)['qualified_for_experiment'])
        self.assertTrue(all(v['minimum_checks']==[] for v in att['payload']['submission']['unit_verdicts']))

    def test_planner_rejects_json_producers_or_tampered_parent_bundle(self):
        ids=dict(self.registry);ids[self.f.records[0]['execution_id']]={}
        with self.assertRaises(ValueError):plan_closed_checks(self.bundle,trusted_identities=ids)
        bundle=copy.deepcopy(self.bundle)
        bundle['payload']['card']['claims'][0]['text']='Changed unverified parent claim.'
        with self.assertRaises(ValueError):plan_closed_checks(bundle,trusted_identities=self.registry)

    def test_packet_specific_tool_schema_enumerates_exact_ids_and_forbids_duplicate_selectors(self):
        for packet in self.packets:
            p=packet['payload'];identity=self.identity()
            worker=make_closed_check_worker(packet,identity,save=lambda a,i:None)
            inventory=worker.submission_schema['properties']['data']['properties']['unit_verdicts']
            self.assertEqual(inventory['minItems'],len(p['required_units']))
            self.assertEqual(inventory['maxItems'],len(p['required_units']))
            self.assertIn('Return exactly '+str(len(p['required_units']))+' unit rows',worker.instruction)
            self.assertIn('Minimum IDs belong only nested inside that unit minimum_checks',worker.instruction)
            definitions=worker.submission_schema['$defs']
            unit=definitions['UnitVerdict']['properties'];minimum=definitions['MinimumCheck']['properties']
            self.assertEqual(unit['unit_id']['enum'],[u['unit_id'] for u in p['required_units']])
            allowed=p['source_material_ids'] if p['check_kind']=='claim' else [m['material_id'] for m in p['materials']]
            self.assertEqual(unit['observations']['items']['enum'],allowed)
            self.assertTrue(unit['observations']['uniqueItems'])
            self.assertEqual(minimum['observations']['items']['enum'],p['source_material_ids'])
            self.assertTrue(minimum['observations']['uniqueItems'])
            if p['minimum_units']:
                self.assertEqual(minimum['minimum_unit_id']['enum'],[m['minimum_unit_id'] for m in p['minimum_units']])
            else:self.assertEqual(unit['minimum_checks']['maxItems'],0)
            self.assertIn('Put all explanation in reason',worker.instruction)
            self.assertIn('generic description does not establish',worker.instruction)
            self.assertIn('named_destination.value.text actually written',worker.instruction)
            for invalid in ('The source supports this claim.',allowed[0]+': explanation'):
                self.assertNotIn(invalid,unit['observations']['items']['enum'])
                value=scripted_closed_submission(packet);value['unit_verdicts'][0]['observations']=[invalid]
                with self.assertRaisesRegex(ClosedCheckError,'Foreign/duplicate'):
                    self.accept(packet,value)

    def test_wrong_source_target_or_foreign_named_destination_cannot_rescue(self):
        claim=self.packets[0]
        data=scripted_closed_submission(claim)
        for bad in ('unprovided-source',claim['payload']['target_material_ids'][0]):
            value=copy.deepcopy(data);value['unit_verdicts'][0]['observations']=[bad]
            with self.assertRaisesRegex(ClosedCheckError,'Foreign/duplicate'):
                self.accept(claim,value)
        retention=next(p for p in self.packets if p['payload']['check_kind']=='retention')
        value=scripted_closed_submission(retention)
        value['unit_verdicts'][0]['observations']=[retention['payload']['target_material_ids'][0]]+retention['payload']['source_material_ids']
        with self.assertRaisesRegex(ClosedCheckError,'EVERY named destination'):
            self.accept(retention,value)
        value['unit_verdicts'][0]['observations'].append('named_destination/not-provided')
        with self.assertRaisesRegex(ClosedCheckError,'Foreign/duplicate'):
            self.accept(retention,value)

    def test_same_finding_different_disposition_must_be_separate_groups(self):
        card=copy.deepcopy(self.f.cards[0]);card['retention'][-1]['reason']='A distinct scientific disposition.'
        packet=draft_packet('paper_card',[self.f.packets[0]],[self.f.records[0]],self.f.questions)
        card=validate_draft(packet,{k:card[k] for k in ('claims','retention','cells')},execution_id=card['writer_execution_id'])
        self.registry[card['writer_execution_id']]=replace(self.registry[card['writer_execution_id']],output_hashes={'changed':payload_hash(card)})
        bundle=plan_paper_review_v2(self.f.packets[0],self.f.records[0],card)
        groups=plan_closed_checks(bundle,trusted_identities=self.registry)
        self.assertGreater(len(groups),len(self.packets))
        self.assertEqual(sum(len(x['payload']['required_units']) for x in groups),
                         sum(len(x['payload']['required_units']) for x in self.packets))

    def test_each_original_tag_preserves_its_negative_and_blocks_group(self):
        packet=next(p for p in self.packets if p['payload']['check_kind']=='retention' and len(p['payload']['required_units'])>1)
        data=scripted_closed_submission(packet);data['unit_verdicts'][1]['status']='unsupported'
        data['unit_verdicts'][1]['reason']='This tag is absent from its actual named destination.'
        attempts=[];registry={};identity=self.identity()
        def save(a,i):
            attempts.append(a)
            if i:registry[i.context_id]=i
        worker=make_closed_check_worker(packet,identity,save=save)
        with self.assertRaises(ClosedCheckNegative):worker.accept({'data':data},identity)
        att=attempts[0]['attestation']
        self.assertEqual(att['payload']['status'],'needs_revision')
        self.assertEqual(att['payload']['submission']['unit_verdicts'][0]['status'],'supported')
        self.assertEqual(att['payload']['submission']['unit_verdicts'][1]['status'],'unsupported')
        self.assertFalse(verify_closed_attestation(packet,att,trusted_identities=registry)['qualified_for_experiment'])

    def test_missing_duplicate_units_minimums_and_supported_missing_components_rejected(self):
        packet=self.packets[0];baseline=scripted_closed_submission(packet)
        variants=[]
        a=copy.deepcopy(baseline);a['unit_verdicts']=[];variants.append(a)
        a=copy.deepcopy(baseline);a['unit_verdicts']*=2;variants.append(a)
        a=copy.deepcopy(baseline);a['unit_verdicts'][0]['minimum_checks']=[];variants.append(a)
        for value in variants:
            with self.assertRaises(ClosedCheckError):self.accept(packet,value)
        a=copy.deepcopy(baseline);a['unit_verdicts'][0]['missing_components']=['Unreported timing.']
        with self.assertRaises(ClosedCheckNegative) as raised:self.accept(packet,a)
        self.assertTrue(raised.exception.semantic_negative_detected)

    def test_extra_and_string_raw_are_invalid_without_coercion_and_negative_is_terminal(self):
        packet=self.packets[0];attempts=[];identity=self.identity()
        worker=make_closed_check_worker(packet,identity,save=lambda a,i:attempts.append(a))
        data=scripted_closed_submission(packet)
        for raw in ({'data':json.dumps(data)},{'data':data,'extra':None}):
            with self.assertRaises(ClosedCheckError):worker.accept(raw,identity)
        negative=scripted_closed_submission(packet,True);negative['extra']='invalid yet honest negative'
        with self.assertRaises(ClosedCheckNegative):worker.accept({'data':negative},identity)
        self.assertEqual(attempts[-1]['status'],'invalid')
        self.assertEqual(attempts[-1]['raw_tool_arguments']['data'],negative)
        self.assertNotIn('invalid yet honest negative',attempts[-1]['validation_error'])
        with self.assertRaises(ClosedCheckNegative):
            worker.accept({'data':json.dumps(negative)},identity)
        self.assertIsInstance(attempts[-1]['raw_tool_arguments']['data'],str)
        self.assertEqual(attempts[-1]['status'],'invalid')

    def test_changed_packet_raw_defaults_submission_and_json_identity_fail_fresh_replay(self):
        packet=self.packets[0];att,registry,_,_=self.accept(packet)
        for mutation in ('packet','raw','normalized','json_identity','input','ancestry'):
            changed=copy.deepcopy(packet);a=copy.deepcopy(att);ids=dict(registry)
            if mutation=='packet':changed['payload']['materials'][0]['value']['text']='Changed actual science.'
            elif mutation=='raw':a['payload']['raw_tool_arguments']['data']['unit_verdicts'][0]['reason']='Changed'
            elif mutation=='normalized':a['payload']['submission']['issues']=[{'invented':True}]
            elif mutation=='json_identity':ids['closed-fixture']={}
            elif mutation=='input':ids['closed-fixture']=replace(ids['closed-fixture'],input_hashes={'closed-check.json':payload_hash('wrong')})
            else:ids['closed-fixture']=replace(ids['closed-fixture'],ancestor_context_ids=(packet['payload']['producer_execution_ids'][0],))
            if mutation in ('raw','normalized'):a['payload_sha256']=payload_hash(a['payload'])
            with self.subTest(mutation=mutation),self.assertRaises(ClosedCheckError):
                verify_closed_attestation(changed,a,trusted_identities=ids)
        with self.assertRaises(ClosedCheckError):
            make_closed_check_worker(packet,self.identity(packet['payload']['producer_execution_ids'][0]),save=lambda a,i:None)

    def test_section_closed_claims_only_own_premises_and_retention_only_named_destinations(self):
        children=[]
        for i in range(2):
            bundle=plan_paper_review_v2(self.f.packets[i],self.f.records[i],self.f.cards[i])
            data=scripted_v2(bundle);context='host-fixture-paper-review-'+str(i)
            payload={'review_id':bundle['review_id'],'bundle_sha256':bundle['payload_sha256'],
                'wire_sha256':bundle['wire_sha256'],'execution_id':context,'status':'passed',
                'submission':data,'publication_verified':False}
            att={'schema':'paper-review-attestation/2','payload':payload,'payload_sha256':payload_hash(payload)}
            self.registry[context]=RuntimeIdentity(execution_id=context,context_id=context,role='verifier',
                input_hashes={'paper-review-v2.json':bundle['wire_sha256']},output_hashes={bundle['review_id']:att['payload_sha256']},
                task_call_id='fixture-review-'+str(i),parent_context_id='fixture-review-parent')
            verify_paper_review_v2(bundle,att,trusted_identities=self.registry)
            children.append({'bundle':bundle,'attestation':att})
        packet=section_draft_packet_v2(children,trusted_identities=self.registry,questions=self.f.questions,
                                      kind='comparison',dimensions=['effect','conditions'])
        section=self.f.make_premise_comparison()
        context=section['writer_execution_id']
        self.registry[context]=RuntimeIdentity(execution_id=context,context_id=context,role='comparer',
            input_hashes={'draft':payload_hash(packet)},output_hashes={'section':payload_hash(section)},
            task_call_id='fixture-derived',parent_context_id='fixture-derived-parent')
        bundle=plan_section_review_v2(section,children,questions=self.f.questions,trusted_identities=self.registry)
        packets=plan_closed_checks(bundle,trusted_identities=self.registry)
        for packet in packets:
            q=packet['payload'];self.assertFalse(any(m['role']=='source_part' for m in q['materials']))
            if q['check_kind']=='claim':
                target=next(m['value'] for m in q['materials'] if m['role']=='target_claim')
                self.assertEqual({m['value']['premise_claim_id'] for m in q['materials'] if m['role']=='premise'},
                                 set(target['premise_claim_ids']))
                self.assertEqual({u['kind'] for u in q['required_units']},{'new_inference','population_scope'})
            att,ids,_,_=self.accept(packet)
            self.assertTrue(verify_closed_attestation(packet,att,trusted_identities=ids)['qualified_for_experiment'])

    def test_real_sdk_creates_reader_writer_and_closed_reviewer_with_zero_network(self):
        import httpx
        network=[]
        def blocked(*a,**k):network.append(True);raise AssertionError('No API in closed SDK regression')
        with tempfile.TemporaryDirectory(prefix='closed-sdk-') as temporary,patch.object(socket,'create_connection',blocked), \
                patch.object(httpx.Client,'send',blocked),patch.object(httpx.AsyncClient,'send',blocked):
            root=Path(temporary);skills=root/'skills';store=TaskStore(root/'store');registry={};state={};attempts=[];identities=[];bound=[]
            for name in set(ROLE_SKILLS.values())|{'literature-review'}:
                folder=skills/name;(folder/'references').mkdir(parents=True)
                (folder/'SKILL.md').write_text('---\nname: '+name+'\ndescription: Scripted mechanics.\n---\nUse tools.',encoding='utf8')
                for ref in ('scientific-records.md','mapped-drafts.md'):(folder/'references'/ref).write_text('Mechanics only.',encoding='utf8')
            source=source_packet('p',b'Failure persists.',[{'id':'q','text':'What limits the result?'}])
            def factory(identity,description):
                identities.append(identity);ticket=json.loads(description)['ticket']
                def registered(t,artifact,receipt):
                    registry[identity.context_id]=RuntimeIdentity(execution_id=identity.context_id,context_id=identity.context_id,
                        role=identity.role,input_hashes={t:next(r for r in store.status() if r['id']==t)['input_hash']},
                        output_hashes={t:receipt['output_hash']},task_call_id=identity.task_tool_call_id,parent_context_id=identity.coordinator_context_id)
                    state[identity.role]=artifact
                if identity.role in ('reader','writer'):
                    return (reader_worker if identity.role=='reader' else draft_worker)(store,identity,ticket,on_accepted=registered)
                lease=store.claim(ticket,identity.role,identity.context_id)
                def save(attempt,execution):
                    attempts.append(attempt);store.put(attempt)
                    if execution:registry[execution.context_id]=execution
                    if attempt['status']=='passed':return store.accept(ticket,identity.context_id,lease['lease'],attempt['attestation'],validator=lambda p,a:None)
                return make_closed_check_worker(state['closed'],identity,save=save)
            def model(role,script):
                cls=ToolRecordingModel if role=='verifier' else ScriptedModel
                extra={'bound_tools':bound} if role=='verifier' else {}
                return cls(role=role,script=script,profile={'tool_calling':True,'max_input_tokens':200000,'max_output_tokens':16384},**extra)
            def run(ticket,role):
                def parent(messages,r):
                    if any(isinstance(m,ToolMessage) for m in messages):return AIMessage(content='Actual receipts received.')
                    return AIMessage(content='',tool_calls=[{'id':'actual-'+ticket,'name':'task','args':{'subagent_type':role,'description':json.dumps({'ticket':ticket})}}])
                def worker(identity):
                    def script(messages,r):
                        data=scripted_closed_submission(state['closed']) if r=='verifier' else scripted_submission(r,state['assigned'])
                        return AIMessage(content='',tool_calls=[{'id':'submit-'+identity.context_id,'name':'submit_result','args':{'data':data}}])
                    return model(identity.role,script)
                def agent_factory(ready,workspace):
                    return create_review_agent(model('coordinator',parent),workspace,skills,worker_factory=factory,
                        worker_model_factory=worker,coordinator_tools=[ready],max_concurrency=1)
                result=asyncio.run(run_frontiers(ScopedTaskStore(store,[ticket]),agent_factory,
                    root/('agents-'+ticket),time.monotonic()+60,frontier_size=1))
                self.assertTrue(result['passed'],result)
            ticket=store.create('reader',source,max_attempts=1);state['assigned']=source;run(ticket,'reader')
            dp=draft_packet('paper_card',[source],[state['reader']],source['questions'])
            # Scripted writer helper consumes actual wire aliases.
            from litreview_core.draft_submission_wire import alias_obligations
            from litreview_core.draft_wire import project_draft_packet
            state['assigned']=project_draft_packet(alias_obligations(dp)[0])
            wt=store.create('writer',dp,dependencies=[ticket],max_attempts=1);run(wt,'writer')
            bundle=plan_paper_review_v2(source,state['reader'],state['writer'])
            state['closed']=plan_closed_checks(bundle,trusted_identities=registry)[0]
            vt=store.create('verifier',state['closed'],dependencies=[wt],max_attempts=1);run(vt,'verifier')
            self.assertTrue(all(r['status']=='accepted' for r in store.status()))
            self.assertEqual(len(identities),3);self.assertEqual(len({i.context_id for i in identities}),3)
            self.assertTrue(all(i.task_tool_call_id and i.coordinator_context_id for i in identities))
            self.assertTrue(verify_closed_attestation(state['closed'],attempts[0]['attestation'],trusted_identities=registry)['qualified_for_experiment'])
            advertised=[t['function']['parameters'] for role,tools in bound for t in tools
                        if t['function']['name']=='submit_result']
            self.assertTrue(advertised)
            for schema in advertised:
                # LangChain dereferences the JSON Schema definitions when
                # binding the actual OpenAI function tool. Check that real
                # advertised schema, not just our pre-conversion definition.
                inventory=schema['properties']['data']['properties']['unit_verdicts']
                self.assertEqual(inventory['minItems'],len(state['closed']['payload']['required_units']))
                self.assertEqual(inventory['maxItems'],len(state['closed']['payload']['required_units']))
                props=inventory['items']['properties']
                self.assertEqual(props['observations']['items']['enum'],state['closed']['payload']['source_material_ids'])
                self.assertEqual(props['unit_id']['enum'],[u['unit_id'] for u in state['closed']['payload']['required_units']])
                self.assertEqual(props['minimum_checks']['items']['properties']['minimum_unit_id']['enum'],
                                 [m['minimum_unit_id'] for m in state['closed']['payload']['minimum_units']])
            self.assertEqual(network,[])


if __name__=='__main__':unittest.main()
