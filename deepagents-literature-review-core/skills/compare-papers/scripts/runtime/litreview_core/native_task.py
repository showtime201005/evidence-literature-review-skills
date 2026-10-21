"""Run one native reading, drafting or source-verification task; never approves publication.

Verifier inputs use native-proof-input/1 with exactly packets, records, sections
and node_id. The complete plan is rebuilt from those actual artifacts. Only an
independent, dependency-free source node may be selected; caller-supplied proof
receipts, identities or material maps are never accepted as dependencies.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time
from dataclasses import fields
from collections.abc import Mapping

from .native_agent import ROLE_SKILLS, create_review_agent
from .coordinator_frontier import run_frontiers
from .reader_worker import reader_worker
from .draft_worker import draft_worker
from .proof_planner import plan_review
from .proof_worker import proof_worker
from .task_store import TaskStore
from .qwen_tokens import QwenRequestCounter
from .qwen_transport import create_model, aclose_http_clients, close_http_clients
from .request_governor import RequestGovernor, ThroughputConfig


def prepare_verifier_input(value, *, token_counter=None, proof_max_units=16, merge_full_source=False):
    """Reconstruct immutable scientific inputs before any output/model dispatch.

    This validates structural source/reader/draft consistency, not semantic
    correctness of a claim. The native verifier must make that judgment.
    """
    if type(proof_max_units) is not int or not 1<=proof_max_units<=128:
        raise ValueError('Proof unit limit must be an integer in 1..128')
    fields = {'schema', 'packets', 'records', 'sections', 'node_id'}
    if not isinstance(value, dict) or set(value) != fields or value.get('schema') != 'native-proof-input/1':
        raise ValueError('Expected native-proof-input/1 with exactly packets, records, sections and node_id; external dependency proofs are forbidden')
    if any(not isinstance(value[name], list) or not value[name] for name in ('packets', 'records', 'sections')):
        raise ValueError('Verifier requires nonempty original packets, reader records and mapped sections')
    node_id = value['node_id']
    if not isinstance(node_id, str) or not node_id or node_id != node_id.strip():
        raise ValueError('Verifier node_id must be a nonempty unpadded string')
    bundle = plan_review(value['sections'], value['packets'], value['records'], token_counter=token_counter,
                         max_scientific_units=proof_max_units,merge_full_source=merge_full_source)
    spec = bundle['node_specs'].get(node_id)
    if spec is None:
        raise ValueError('Unknown verifier node_id in reconstructed plan')
    if spec['role'] != 'verifier' or spec['kind'] != 'source' or spec['dependencies']:
        raise ValueError('Standalone verifier accepts only dependency-free source nodes; use the complete workflow for dependent proofs')
    return bundle


def source_proof_worker(store, identity, ticket, *, token_counter=None, on_saved=None, proof_max_units=16,
                        quote_witness=False, merge_full_source=False):
    """Actual task factory adapter; persist every semantic verdict and identity.

    TaskStore binds the entire original input envelope. Worker input/material
    hashes are separately bound by proof_worker to the reconstructed plan.
    """
    if identity.role != 'verifier':
        raise ValueError('Source verification requires the verifier runtime role')
    lease = store.claim(ticket, identity.role, identity.context_id)

    def fail_running(reason):
        row = next(row for row in store.status() if row['id'] == ticket)
        if row['status'] == 'running':
            store.fail(ticket, identity.context_id, lease['lease'], reason)

    try:
        value = lease['payload']
        bundle = prepare_verifier_input(value, token_counter=token_counter,proof_max_units=proof_max_units,
                                        merge_full_source=merge_full_source)
        node_id = value['node_id']

        def save(node, execution, submission):
            attestation = {'schema': 'native-source-proof-result/1',
                'completion_scope': 'Assigned dependency-free source responsibilities only; not a complete review or cold workflow',
                'publication_verified': False, 'input_sha256': lease['input_hash'],
                'node': node, 'runtime_identity': {
                    field.name: (dict(value) if isinstance(value, Mapping) else list(value) if isinstance(value, tuple) else value)
                    for field in fields(execution) for value in (getattr(execution, field.name),)},
                'actual_worker_identity': identity.as_dict(), 'submission': submission}
            digest = store.put(attestation)
            receipt = None
            if node['payload']['status'] == 'passed':
                receipt = store.accept(ticket, identity.context_id, lease['lease'],
                    attestation, validator=lambda original, output: None)
            else:
                store.fail(ticket, identity.context_id, lease['lease'],
                    {'code': 'VERIFICATION_ISSUES', 'attestation_hash': digest,
                     'node_id': node_id, 'status': node['payload']['status']})
            if on_saved is not None:
                on_saved(digest, attestation)
            return receipt

        def finish(actual_identity, receipt):
            if actual_identity.context_id != identity.context_id:
                raise ValueError('Foreign source-verifier finish context')
            fail_running({'reason': receipt.get('error', receipt.get('reason', 'incomplete'))})

        # This entry point accepts only dependency-free source leaves.
        worker_builder = proof_worker
        if quote_witness:
            from .proof_quote_worker import source_witness_worker
            worker_builder = source_witness_worker
        return worker_builder(bundle, node_id, {}, identity, save=save, on_finish=finish,
                            proof_nodes={}, proof_identities={})
    except BaseException as exc:
        try:
            fail_running({'reason': str(exc)})
        except BaseException as cleanup_error:
            exc.add_note('Source-verifier lease cleanup failed: ' + str(cleanup_error))
        raise


async def run(args):
    started=time.monotonic()
    output_budget=getattr(args,'max_output_tokens',16384)
    quote_witness=getattr(args,'quote_witness',False)
    if quote_witness and args.role!='verifier':
        raise ValueError('Quote witness experiment requires verifier role')
    if output_budget not in (16384,32768):
        raise ValueError('Worker output budget must be 16384 or 32768')
    output=args.out.resolve()
    if output.exists():
        raise ValueError('Task output must be a new directory')
    packet=json.loads(args.input.read_text(encoding='utf-8'))
    if isinstance(packet,dict) and packet.get('schema')=='native-proof-input/1' and args.role!='verifier':
        raise ValueError('native-proof-input/1 may only be used with --role verifier')
    counter=QwenRequestCounter(args.tokenizer)
    count_text=lambda text:len(counter.tokenizer.encode(text,add_special_tokens=False).ids)
    proof_max_units=getattr(args,'proof_max_units',16)
    merge_full_source=getattr(args,'merge_full_source',False)
    prepared=prepare_verifier_input(packet,token_counter=count_text,proof_max_units=proof_max_units,
        merge_full_source=merge_full_source) if args.role=='verifier' else None
    governor=RequestGovernor(ThroughputConfig(workers=1,minimum_workers=1,
        deadline_seconds=args.deadline,token_counter=counter))
    store=TaskStore(output/'artifacts')
    ticket=store.create(args.role,packet,max_attempts=1)
    preferences={'only':[args.provider],'allow_fallbacks':False} if args.provider else None
    reasoning_mode=getattr(args,'reasoning','low')
    if reasoning_mode not in ('low','off'):
        raise ValueError('Worker reasoning mode must be low or off')
    attestations=[]

    def factory(identity,description):
        request=json.loads(description)
        if request!={'ticket':ticket}:
            raise ValueError('Task description must match assigned ticket')
        if args.role=='verifier':
            worker=source_proof_worker(store,identity,ticket,token_counter=count_text,proof_max_units=proof_max_units,
                quote_witness=quote_witness,merge_full_source=merge_full_source,
                on_saved=lambda digest,value:attestations.append((digest,value)))
        else:
            worker=(reader_worker if args.role=='reader' else draft_worker)(store,identity,ticket)
        worker.max_model_calls=args.max_model_calls
        return worker

    def agent_factory(ready_tasks,workspace):
        return create_review_agent(create_model(governor=governor,max_tokens=4096,
            reasoning_effort='low',provider_preferences=preferences),workspace,args.skills_root,
            worker_factory=factory,coordinator_tools=[ready_tasks],max_concurrency=1,
            roles=(args.role,),coordinator_skill=ROLE_SKILLS[args.role],
            worker_model_factory=lambda identity:create_model(governor=governor,
                force_submit=args.tool_choice=='forced',max_tokens=output_budget,
                reasoning_enabled=reasoning_mode!='off',reasoning_effort='low' if reasoning_mode=='low' else None,
                temperature=.1,provider_preferences=preferences),
            coordinator_prompt='Use the installed skill for the supplied task. Get ready_tasks and '
                'delegate its exact ticket through task to the supplied role. Return its truthful outcome. '
                'A draft is not independently verified and does not authorize publication.')
    error=None
    frontier=None
    try:
        frontier=await run_frontiers(store,agent_factory,output/'native',started+args.deadline,frontier_size=1)
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
    finally:
        governor.close()
        await aclose_http_clients()
        close_http_clients()
    row=store.status()[0]
    passed=bool(frontier and frontier['passed'] and row['status']=='accepted' and error is None)
    if row['status']=='accepted':
        (output/'artifact.json').write_text(json.dumps(store.get(row['output_hash']),ensure_ascii=False,indent=2),encoding='utf-8')
    if attestations:
        (output/'proof-result.json').write_text(json.dumps(attestations[-1][1],ensure_ascii=False,indent=2),encoding='utf-8')
    report={'schema':'native-single-task/1','role':args.role,'passed':passed,
        'quote_witness_experiment':quote_witness,
        'proof_max_units':proof_max_units if args.role=='verifier' else None,
        'merge_full_source':merge_full_source if args.role=='verifier' else None,
        'publication_verified':False,'full_review_cold_acceptance':False,
        'input_sha256':row['input_hash'],'tool_choice':args.tool_choice,'provider_preferences':preferences,
        'max_worker_model_calls':args.max_model_calls,'elapsed_seconds':time.monotonic()-started,
        'reasoning':({'enabled':True,'effort':'low'} if reasoning_mode=='low' else {'enabled':False}),
        'worker_max_output_tokens':output_budget,
        'error':error or (frontier or {}).get('error'),'task':row,'telemetry':governor.finish(completed=passed)}
    if prepared is not None:
        spec=prepared['node_specs'][packet['node_id']]
        report['source_verification']={'node_id':packet['node_id'],'kind':spec['kind'],
            'dependencies':[],'coverage_counts':{key:len(ids) for key,ids in spec['coverage'].items()},
            'completion_scope':'Specified source responsibility only; no complete review or cold-workflow approval',
            'reconstructed_plan_hash':prepared['plan']['payload_hash'],
            'attestation_hashes':[digest for digest,value in attestations],
            'verdict_status':attestations[-1][1]['node']['payload']['status'] if attestations else None}
    (output/'task-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','role','tool_choice','elapsed_seconds','error')},ensure_ascii=False))
    return 0 if passed else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('input','out','skills-root','tokenizer'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--role',choices=('reader','writer','comparer','verifier'),required=True)
    parser.add_argument('--tool-choice',choices=('forced','auto'),default='auto')
    parser.add_argument('--provider')
    parser.add_argument('--reasoning',choices=('low','off'),default='low',
        help='Worker setting for controlled quality/latency tests; coordinator retains low reasoning')
    parser.add_argument('--deadline',type=float,default=300)
    parser.add_argument('--max-model-calls',type=int,default=6)
    parser.add_argument('--proof-max-units',type=int,default=16,
        help='Verifier packing limit (1..128); context caps remain unchanged')
    parser.add_argument('--merge-full-source',action='store_true',
        help='Opt-in complete source/card duty merge only when source and paired assembly both fit; otherwise retain the original partition')
    parser.add_argument('--max-output-tokens',type=int,choices=(16384,32768),default=16384,
        help='Experimental worker completion reservation; included in the unchanged 200K request cap')
    parser.add_argument('--quote-witness',action='store_true',
        help='Experimental source verifier exact quote checks; not whole-review publication approval')
    args=parser.parse_args()
    if args.deadline<=0 or not 1<=args.max_model_calls<=8:
        parser.error('Positive deadline and 1..8 model calls required')
    if not 1<=args.proof_max_units<=128:
        parser.error('--proof-max-units must be 1..128')
    raise SystemExit(asyncio.run(run(args)))
