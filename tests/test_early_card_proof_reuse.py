"""Early-card proof reuse through real SDK task lineage, with scripted science.

The test never calls a paid model or invents trusted RuntimeIdentity objects.
Scripted scientific judgments test mechanics only, not model comprehension.
Production ReviewWorkflow scheduling is not changed by this isolated driver.
"""
import argparse
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
import test_proof_planner as planner_fixture
from litreview_core.coordinator_frontier import run_frontiers
from litreview_core.delivery_export import export_review
from litreview_core.draft_wire import project_draft_packet
from litreview_core.draft_submission_wire import alias_obligations,decode_grouped_submission
from litreview_core.hierarchical_proof import ProofError,RuntimeIdentity,verify_dependency_closure,verify_proof
from litreview_core.native_agent import ROLE_SKILLS,create_review_agent
from litreview_core.proof_planner import plan_review
from litreview_core.proof_worker import proof_worker
from litreview_core.review_artifacts import draft_packet,inference_packet,validate_draft
from litreview_core.review_repair import reusable_nodes
from litreview_core.review_workflow import ReviewWorkflow
from litreview_core.scientific_records import source_packet,validate_reader
from litreview_core.task_store import ScopedTaskStore,TaskStore

REPORT_CASES=[]


class _StopBeforeGlobalProofs(RuntimeError):
    pass


def spec_differences(mini,global_bundle):
    differences={}
    for nid,spec in mini['node_specs'].items():
        if spec['kind']=='root':
            continue
        other=global_bundle['node_specs'].get(nid)
        diff={'missing_global_node':True} if other is None else {
            field:{'mini':spec.get(field),'global':other.get(field)}
            for field in set(spec)|set(other) if spec.get(field)!=other.get(field)}
        if diff:
            differences[nid]=diff
    return differences


class EarlyCardProofReuseTests(unittest.TestCase):
    def test_rich_fixture_all_spec_fields_equal_under_identical_budgets(self):
        fixture=planner_fixture.ProofPlannerTests()
        fixture.setUp()
        rows=[]
        for merge,units in ((False,16),(True,16),(False,2),(True,2)):
            global_bundle=fixture.compile(merge_full_source=merge,max_scientific_units=units)
            for card,packet,record in zip(fixture.cards,fixture.packets,fixture.records):
                mini=plan_review([card],[packet],[record],merge_full_source=merge,max_scientific_units=units)
                differences=spec_differences(mini,global_bundle)
                self.assertEqual(differences,{})
                rows.append({'paper_id':packet['paper_id'],'merge_full_source':merge,
                    'max_scientific_units':units,'early_nodes':len(mini['node_specs'])-1,'field_differences':differences})
        REPORT_CASES.append({'case':'rich_structural_spec_comparison','rows':rows,
            'science_assessed':False,'trusted_identities_created':False})

    def test_actual_sdk_split_card_proofs_reused_with_native_identity_and_final_gate(self):
        self.exercise(False)

    def test_actual_sdk_merged_card_proofs_reused_with_native_identity_and_final_gate(self):
        self.exercise(True)

    def exercise(self,merge):
        import httpx
        network_attempts=[]
        def blocked(*args,**kwargs):
            network_attempts.append(True)
            raise AssertionError('No network in early proof reuse test')
        with tempfile.TemporaryDirectory(prefix='early-card-sdk-') as tmp, \
                patch.object(socket,'create_connection',blocked), \
                patch.object(httpx.Client,'send',blocked),patch.object(httpx.AsyncClient,'send',blocked):
            root=Path(tmp)
            skills=root/'skills'
            for name in set(ROLE_SKILLS.values())|{'literature-review'}:
                folder=skills/name
                (folder/'references').mkdir(parents=True)
                (folder/'SKILL.md').write_text(f'---\nname: {name}\ndescription: Offline mechanics.\n---\nUse assigned tools.',encoding='utf-8')
                for ref in ('hierarchical-proof.md','scientific-records.md','mapped-drafts.md'):
                    (folder/'references'/ref).write_text('Scripted mechanics only.',encoding='utf-8')
            questions=[{'id':'q','text':'What limits the result?'}]
            packets=[source_packet('p'+str(i),b'Failure persists.',questions) for i in range(2)]
            store=TaskStore(root/'research')
            workflow=ReviewWorkflow(store,packets,questions,group_size=2,merge_full_source=merge)
            deadline=time.monotonic()+120
            actual_identities=[]
            graphs=[]
            early_nodes={}
            mini_bundles={}
            early_artifacts={}
            stage_paths=[]

            def model(role,script):
                return ScriptedModel(role=role,script=script,
                    profile={'tool_calling':True,'max_input_tokens':200000,'max_output_tokens':16384})

            async def native_dispatch(stage,task_store,factory,tickets=None):
                def agent_factory(ready_tasks,workspace):
                    assigned={}
                    calls=[0]
                    def parent(messages,role):
                        calls[0]+=1
                        cid='parent-'+str(calls[0])
                        results=[m for m in messages if isinstance(m,ToolMessage)]
                        if not results or results[-1].name=='task':
                            return AIMessage(content='',id=cid,tool_calls=[{'name':'ready_tasks','args':{},'id':cid+'-ready'}])
                        ready=json.loads(results[-1].content)
                        if ready['frontier_complete']:
                            return AIMessage(content='Assigned mechanics complete; no scientific inference.')
                        return AIMessage(content='',id=cid,response_metadata={'id':cid+'-response'},
                            tool_calls=[{'name':'task','args':item,'id':cid+'-task-'+str(i)} for i,item in enumerate(ready['ready'])])
                    def worker_factory(identity,description):
                        worker=factory(identity,description)
                        actual_identities.append(identity)
                        assigned[identity.context_id]=dict(worker.inputs)
                        return worker
                    def worker_model(identity):
                        def script(messages,role):
                            human=next(m for m in messages if isinstance(m,HumanMessage))
                            delivered=re.findall(r"<assigned_input path='/inputs/([^']+)'>\n(.*?)\n</assigned_input>",human.content,re.DOTALL)
                            actual={name:text if isinstance(assigned[identity.context_id][name],str) else json.loads(text) for name,text in delivered}
                            self.assertEqual(actual,assigned[identity.context_id])
                            value=scripted_submission(role,next(iter(actual.values())))
                            return AIMessage(content='',tool_calls=[{'name':'submit_result','args':{'data':value},'id':identity.context_id+'-submit'}])
                        return model(identity.role,script)
                    agent=create_review_agent(model('coordinator',parent),workspace,skills,
                        worker_factory=worker_factory,worker_model_factory=worker_model,
                        coordinator_tools=[ready_tasks],max_concurrency=2)
                    graphs.append(agent)
                    return agent
                scoped=ScopedTaskStore(task_store,tickets) if tickets is not None else task_store
                output=root/'stages'/stage
                stage_paths.append(stage)
                result=await run_frontiers(scoped,agent_factory,output,deadline,frontier_size=2)
                self.assertTrue(result['passed'],result)
                self.assertFalse(result['publication_verified'])

            async def execute_proofs(stage,bundles,nodes):
                proof_store=TaskStore(root/stage)
                tickets={}
                owner={}
                wanted={nid:(bundle,spec) for bundle in bundles for nid,spec in bundle['node_specs'].items()
                        if spec['kind']!='root' or stage=='remaining-global-proofs'}
                pending={nid:item for nid,item in wanted.items() if nid not in nodes}
                while pending:
                    ready=[nid for nid,(_,spec) in pending.items() if set(spec['dependencies'])<=set(nodes)|set(tickets)]
                    if not ready:
                        raise AssertionError('Missing early/global dependency')
                    for nid in ready:
                        bundle,spec=pending.pop(nid)
                        ticket=proof_store.create(spec['role'],{'node_id':nid},
                            dependencies=[tickets[d] for d in spec['dependencies'] if d in tickets],max_attempts=1)
                        tickets[nid]=ticket
                        owner[ticket]=bundle
                def factory(identity,description):
                    ticket=json.loads(description)['ticket']
                    lease=proof_store.claim(ticket,identity.role,identity.context_id)
                    bundle=owner[ticket]
                    nid=lease['payload']['node_id']
                    spec=bundle['node_specs'][nid]
                    dependencies={d:nodes[d] for d in spec['dependencies']}
                    def save(node,execution,submission):
                        nodes[nid]=node
                        workflow.identities[execution.execution_id]=execution
                        proof_store.put({'node':node,'submission':submission})
                        return proof_store.accept(ticket,identity.context_id,lease['lease'],node,validator=lambda a,b:None)
                    return proof_worker(bundle,nid,dependencies,identity,save=save,
                        proof_nodes={n:v for n,v in nodes.items() if n in bundle['node_specs']},
                        proof_identities=workflow.identities)
                if tickets:
                    await native_dispatch(stage,proof_store,factory)
                return list(tickets)

            async def intercepted_dispatch(stage,factory,tickets=None):
                if stage.startswith('independent-proofs'):
                    raise _StopBeforeGlobalProofs('Isolated reuse driver takes over; production scheduler unchanged')
                await native_dispatch(stage,store,factory,tickets)
                if stage=='cards':
                    outputs=[store.get(row['output_hash']) for row in store.status() if row['status']=='accepted']
                    records=[v for v in outputs if v.get('schema')=='scientific-record/1']
                    cards=[v for v in outputs if v.get('schema')=='review-section/1']
                    early_artifacts.update(records=records,cards=cards)
                    for card in cards:
                        pid=card['paper_ids'][0]
                        mini_bundles[pid]=plan_review([card],[next(p for p in packets if p['paper_id']==pid)],
                            [next(r for r in records if r['paper_id']==pid)],merge_full_source=merge)
                    await execute_proofs('early-card-proofs',list(mini_bundles.values()),early_nodes)
                    for mini in mini_bundles.values():
                        terminal=mini['section_assembly_nodes'][mini['root_section_ids'][0]]
                        proof=verify_dependency_closure(mini['plan'],early_nodes,mini['materials'],workflow.identities,[terminal])
                        self.assertEqual(proof['status'],'dependency_closure_validated')
                        self.assertFalse(proof['publication_verified'])

            async def run():
                with self.assertRaises(_StopBeforeGlobalProofs):
                    await workflow.run(intercepted_dispatch)
                global_bundle=workflow.bundle
                self.assertIsNotNone(global_bundle)
                for mini in mini_bundles.values():
                    self.assertEqual(spec_differences(mini,global_bundle),{})
                reused=reusable_nodes(global_bundle,early_nodes)
                if set(reused)!=set(early_nodes):
                    rejected=[]
                    for nid,node in early_nodes.items():
                        if nid in reused:
                            continue
                        spec=global_bundle['node_specs'][nid]
                        coverage_diff={dim:{'actual_sealed':node['payload']['coverage'][dim],
                            'planned_spec':spec['coverage'][dim],
                            'same_set':set(node['payload']['coverage'][dim])==set(spec['coverage'][dim])}
                            for dim in spec['coverage'] if node['payload']['coverage'][dim]!=spec['coverage'][dim]}
                        rejected.append({'node_id':nid,'kind':spec['kind'],
                            'inputs_equal':node['payload']['inputs']==spec['inputs'],
                            'dependency_ids_equal':set(node['payload']['dependencies'])==set(spec['dependencies']),
                            'coverage_order_differences':coverage_diff})
                    REPORT_CASES.append({'case':'actual_sdk_early_reuse_blocked','merge_full_source':merge,
                        'spec_field_differences':{},'early_real_nodes':len(early_nodes),
                        'reused_nodes':len(reused),'rejected':rejected,
                        'actual_identity_and_closure_preflight':True,'api_calls':0,'science_assessed':False})
                self.assertEqual(set(reused),set(early_nodes))
                for nid in reused:
                    self.assertIs(reused[nid],early_nodes[nid])
                    eid=reused[nid]['payload']['execution_id']
                    identity=workflow.identities[eid]
                    self.assertIs(type(identity),RuntimeIdentity)
                    self.assertTrue(identity.task_call_id and identity.parent_context_id)
                nodes=dict(reused)
                newly_executed=await execute_proofs('remaining-global-proofs',[global_bundle],nodes)
                self.assertTrue(newly_executed)
                self.assertFalse(set(newly_executed)&set(early_nodes))
                gate=verify_proof(global_bundle['plan'],nodes,global_bundle['materials'],workflow.identities)
                self.assertEqual(gate['status'],'passed')
                sections=[global_bundle['materials']['section/'+sid] for sid in global_bundle['materials']['review/scope']['section_ids']]
                export_review({'bundle':global_bundle,'nodes':nodes,'identities':workflow.identities,
                    'records':early_artifacts['records'],'sections':sections},root/'delivery')
                self.assertTrue((root/'delivery/main-review.md').is_file())
                return global_bundle,nodes,reused,newly_executed

            global_bundle,nodes,reused,newly_executed=asyncio.run(run())
            # Identity snapshots are evidence for a human, never runtime trust.
            untrusted=dict(workflow.identities)
            first=next(iter(untrusted))
            untrusted[first]={'execution_id':first,'role':'writer'}
            with self.assertRaises(ProofError) as identity_error:
                verify_proof(global_bundle['plan'],nodes,global_bundle['materials'],untrusted)
            self.assertEqual(identity_error.exception.code,'UNTRUSTED_IDENTITY')
            tampered=copy.deepcopy(global_bundle)
            tampered['materials']['original/p0']+=b' changed bytes'
            with self.assertRaises(ProofError) as tamper_error:
                verify_dependency_closure(tampered['plan'],early_nodes,tampered['materials'],workflow.identities,
                    [mini_bundles['p0']['section_assembly_nodes'][mini_bundles['p0']['root_section_ids'][0]]])

            def hypothetical_replan(source_changed=False):
                changed_packets=list(packets)
                records={r['paper_id']:r for r in early_artifacts['records']}
                cards={c['paper_ids'][0]:c for c in early_artifacts['cards']}
                if source_changed:
                    changed_packets[0]=source_packet('p0',b'Failure persists.\n\nHypothetical source version note.',questions)
                    records['p0']=validate_reader(changed_packets[0],scripted_submission('reader',changed_packets[0]),
                        execution_id='NOT_EXECUTED_SOURCE_MUTATION_FIXTURE')
                packet=draft_packet('paper_card',[changed_packets[0]],[records['p0']],questions)
                value={key:copy.deepcopy(cards['p0'][key]) for key in ('claims','retention','cells')}
                if source_changed:
                    aliased,aliases=alias_obligations(packet)
                    value=decode_grouped_submission(scripted_submission('writer',project_draft_packet(aliased)),aliases)
                else:
                    value['claims'][0]['text']='Failure still persists.'
                cards['p0']=validate_draft(packet,value,execution_id='NOT_EXECUTED_CARD_MUTATION_FIXTURE')
                ordered=[cards[p['paper_id']] for p in changed_packets]
                def draft(kind,premises):
                    packet=inference_packet(premises,changed_packets,list(records.values()),questions,
                        kind=kind,dimensions=workflow.dimensions if kind=='comparison' else ())
                    aliased,aliases=alias_obligations(packet)
                    value=decode_grouped_submission(scripted_submission('comparer' if kind=='comparison' else 'writer',project_draft_packet(aliased)),aliases)
                    return validate_draft(packet,value,execution_id='NOT_EXECUTED_'+kind.upper()+'_MUTATION_FIXTURE')
                comparison=draft('comparison',ordered)
                synthesis=draft('synthesis',ordered+[comparison])
                return plan_review(ordered+[comparison,synthesis],changed_packets,list(records.values()),merge_full_source=merge)

            invalidations=[]
            for source_changed in (False,True):
                candidate=hypothetical_replan(source_changed)
                surviving=reusable_nodes(candidate,early_nodes)
                p0_nodes={nid for nid in mini_bundles['p0']['node_specs'] if nid in early_nodes}
                p1_nodes={nid for nid in mini_bundles['p1']['node_specs'] if nid in early_nodes}
                self.assertFalse(set(surviving)&p0_nodes)
                self.assertEqual(set(surviving),p1_nodes)
                invalidations.append({'mutation':'source_version' if source_changed else 'card_text_version',
                    'changed_paper_reused':0,'unaffected_paper_reused':len(p1_nodes),
                    'candidate_executed_or_scientifically_approved':False})
            self.assertEqual(sum(e['event']=='task_delegated' for g in graphs for e in g.events),len(actual_identities))
            self.assertFalse(network_attempts)
            REPORT_CASES.append({'case':'actual_sdk_early_reuse','merge_full_source':merge,
                'early_real_nodes':len(early_nodes),'global_real_nodes':len(nodes),'reused_without_reseal':len(reused),
                'new_global_proof_tasks':len(newly_executed),'spec_field_differences':{},
                'identity_origin':'Actual DeepAgents task delegation and native proof_worker acceptance; no identity JSON trusted',
                'dependency_closure_preflight':True,'final_native_gate':'passed','exact_export':True,
                'untrusted_identity_json_rejected':identity_error.exception.code,
                'source_byte_tamper_rejected':tamper_error.exception.code,'version_invalidations':invalidations,
                'api_calls':0,'science_assessed':False,'stages':stage_paths})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    started=time.monotonic()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EarlyCardProofReuseTests))
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps({'schema':'early-card-native-proof-reuse-regression/1',
            'passed':result.wasSuccessful(),'tests_run':result.testsRun,'elapsed_seconds':time.monotonic()-started,
            'api_calls':0,'science_assessed':False,'production_scheduling_modified':False,'cases':REPORT_CASES,
            'limits':['Scripted scientific verdicts test execution, hashes, coverage and lineage only.',
                      'Two tiny papers plus a richer structural fixture; not a hundred-paper performance or semantic benchmark.',
                      'Reuse requires unchanged complete specs and actual runtime identities; reusable_nodes alone is not the final gate.']},
            ensure_ascii=False,indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
