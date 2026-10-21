"""Cold native Qwen review runner; no prior accepted analysis cache is loaded."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time

from .native_agent import create_review_agent
from .qwen_transport import create_model, aclose_http_clients, close_http_clients
from .qwen_tokens import QwenRequestCounter
from .request_governor import RequestGovernor, ThroughputConfig
from .resource_monitor import ResourceMonitor
from .scientific_records import source_packet
from .task_store import TaskStore
from .review_workflow import ReviewWorkflow


def markdown_sources(directory):
    """Portable discovery and identity checks before any paid task is created."""
    directory=Path(directory)
    if not directory.is_dir():
        raise ValueError('Markdown source directory does not exist')
    paths=sorted((p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in ('.md','.markdown')),
                 key=lambda p:(p.name.casefold(),p.name))
    if not 1<=len(paths)<=100:
        raise ValueError('Provide 1..100 Markdown papers')
    identities=[p.stem.casefold() for p in paths]
    if len(identities)!=len(set(identities)):
        raise ValueError('Paper filename stems must be unique, including case, across .md and .markdown files')
    return paths


def role_reasoning_enabled(role, writer_mode='low', reviewer_mode='low', reader_mode='low'):
    if any(mode not in ('low','off') for mode in (writer_mode,reviewer_mode,reader_mode)):
        raise ValueError('Role reasoning mode must be low or off')
    return not ((writer_mode=='off' and role in ('writer','comparer')) or
                (reviewer_mode=='off' and role in ('verifier','assembly-auditor')) or
                (reader_mode=='off' and role=='reader'))


def review_provider_preferences(args):
    """Optional parent routing override; all roles retain the same Qwen model."""
    worker=getattr(args,'provider',None)
    parent=getattr(args,'coordinator_provider',None) or worker
    def preferences(name):
        return {'only':[name],'allow_fallbacks':False} if name else None
    return {'coordinator':preferences(parent),'worker':preferences(worker)}


def validated_review_protocol(args):
    protocol=getattr(args,'review_protocol','v1')
    if protocol not in ('v1','v2'):
        raise ValueError('Review protocol must be v1 or v2')
    observations=getattr(args,'review_observations','quotes')
    if observations not in ('quotes','whole-unit'):
        raise ValueError('Review observations must be quotes or whole-unit')
    if protocol!='v2' and observations!='quotes':
        raise ValueError('Whole-unit observations require experimental review protocol v2')
    if protocol!='v2' and getattr(args,'closed_checks',False):
        raise ValueError('Closed local checks require experimental review protocol v2')
    if protocol=='v2' and (getattr(args,'source_quote_witness',False)
            or getattr(args,'merge_full_source',False)
            or getattr(args,'proof_max_units',16)!=16):
        raise ValueError('V1 witness/merge/proof packing flags do not apply to review protocol v2')
    return protocol


def review_delivery_flags(protocol, delivered):
    if protocol not in ('v1','v2'):
        raise ValueError('Review protocol must be v1 or v2')
    return {'review_protocol':protocol,
        'publication_verified':bool(delivered and protocol=='v1'),
        'protocol_completed_experimental':bool(delivered and protocol=='v2'),
        'quality_validated':False}


def make_review_workflow(args, store, packets, questions, counter, deadline_at):
    protocol=validated_review_protocol(args)
    count=lambda text:len(counter.tokenizer.encode(text,add_special_tokens=False).ids)
    if protocol=='v2':
        from .review_workflow_v2 import ReviewWorkflowV2
        return ReviewWorkflowV2(store,packets,questions,group_size=args.group_size,
                               token_counter=count,deadline_at=deadline_at,
                               observation_mode=('whole-unit-selectors/1'
                                   if getattr(args,'review_observations','quotes')=='whole-unit' else 'quotes'),
                               closed_checks=getattr(args,'closed_checks',False))
    return ReviewWorkflow(store,packets,questions,group_size=args.group_size,
        source_quote_witness=getattr(args,'source_quote_witness',False),
        early_card_verification=getattr(args,'early_card_verification',False),
        proof_max_units=getattr(args,'proof_max_units',16),
        merge_full_source=getattr(args,'merge_full_source',False),token_counter=count)


def review_throughput_config(args, counter, remaining_seconds):
    active_limit=getattr(args,'active_token_limit',1_000_000)
    if type(active_limit) is not int or not 200_000<=active_limit<=6_400_000:
        raise ValueError('Aggregate active-token limit must be 200000..6400000')
    return ThroughputConfig(workers=args.workers,minimum_workers=1,
        active_token_limit=active_limit,context_limit=200_000,
        deadline_seconds=max(.01,remaining_seconds),token_counter=counter)


async def timed_stage(stage, operation, stages, run_started):
    """Retain monotonic stage timing even when the outer deadline cancels work."""
    began=time.monotonic()
    entry={'stage':stage,'started_after_seconds':began-run_started}
    try:
        result=await operation()
        entry['result']=result
        entry['status']='completed' if result['passed'] else 'failed'
        return result
    except BaseException as exc:
        entry['status']='cancelled' if isinstance(exc,asyncio.CancelledError) else 'failed'
        entry['error']={'type':type(exc).__name__,'message':str(exc)}
        raise
    finally:
        entry['elapsed_seconds']=time.monotonic()-began
        stages.append(entry)


async def run(args):
    # Starts before loading sources, tokenization, scheduling or any model work.
    started=time.monotonic()
    protocol=validated_review_protocol(args)
    reviewer_output=getattr(args,'reviewer_max_output_tokens',16384)
    if reviewer_output not in (16384,32768):
        raise ValueError('Reviewer output budget must be 16384 or 32768')
    deadline_at=started+args.deadline
    output=args.out.resolve()
    if output.exists() or output.is_relative_to(args.sources.resolve()):
        raise ValueError('Cold output must be a new directory outside input')
    paths=markdown_sources(args.sources)
    questions=json.loads(args.questions.read_text(encoding='utf-8'))
    if isinstance(questions,dict):
        questions=questions['questions']
    packets=[source_packet(p.stem,p.read_bytes(),questions) for p in paths]
    questions=packets[0]['questions']
    counter=QwenRequestCounter(args.tokenizer)
    governor=RequestGovernor(review_throughput_config(args,counter,deadline_at-time.monotonic()))
    store=TaskStore(output/'artifacts')
    workflow=make_review_workflow(args,store,packets,questions,counter,deadline_at)
    stages=[]
    writer_reasoning=getattr(args,'writer_reasoning','low')
    reviewer_reasoning=getattr(args,'reviewer_reasoning','low')
    reader_reasoning=getattr(args,'reader_reasoning','low')
    role_reasoning_enabled('coordinator',writer_reasoning,reviewer_reasoning,reader_reasoning)
    routing=review_provider_preferences(args)
    provider_preferences=routing['worker']
    async def dispatch(stage,factory,tickets=None):
        from .coordinator_frontier import run_frontiers
        from .task_store import ScopedTaskStore
        closed_stage='-closed-' in stage
        def agent_factory(ready_tasks,workspace):
            return create_review_agent(
                create_model(governor=governor,max_tokens=4096,reasoning_effort='low',
                             provider_preferences=routing['coordinator']),
                workspace,args.skills_root,worker_factory=factory,
                worker_model_factory=lambda identity:create_model(governor=governor,
                    force_submit=True,max_tokens=(8192 if closed_stage else
                        reviewer_output if identity.role in ('verifier','assembly-auditor') else 16384),
                    reasoning_effort=None if closed_stage else 'low',
                    reasoning_max_tokens=2048 if closed_stage else None,temperature=.1,
                    reasoning_enabled=role_reasoning_enabled(identity.role,writer_reasoning,reviewer_reasoning,reader_reasoning),
                    provider_preferences=provider_preferences),
                coordinator_tools=[ready_tasks],max_concurrency=args.workers,
                coordinator_prompt='Use literature-review to complete the supplied ready tickets. '
                    'Call ready_tasks and delegate each exact description through task to its assigned role, '
                    'in parallel when independent. Do not execute legacy CLI or invent additional tickets. '
                    'Inspect returned receipts and stop truthfully if the assigned work cannot complete.')
        stage_store=ScopedTaskStore(store,tickets) if tickets is not None else store
        result=await timed_stage(stage,
            lambda:run_frontiers(stage_store,agent_factory,output/'stages'/stage,deadline_at,
                                 frontier_size=args.workers),stages,started)
        if not result['passed']:
            raise RuntimeError('Native stage failed: '+stage)

    monitor=ResourceMonitor()
    error=None
    delivered=False
    try:
        result=await asyncio.wait_for(workflow.run(dispatch),
            timeout=max(.01,deadline_at-time.monotonic()))
        if time.monotonic()>=deadline_at:
            raise TimeoutError('Deadline reached before delivery')
        if protocol=='v2':
            from .delivery_export_v2 import export_review_v2
            export_review_v2(result,output/'delivery',deadline_at=deadline_at,
                             native_trace_root=output/'stages')
        else:
            from .delivery_export import export_review
            export_review(result,output/'delivery')
        delivered=True
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
        try:
            if protocol=='v2':
                from .delivery_export_v2 import save_review_attempt_v2
                save_review_attempt_v2(workflow.partial_snapshot(),output/'unpublished-attempt',
                                       native_trace_root=output/'stages')
            else:
                from .delivery_export import save_review_attempt
                accepted=[store.get(row['output_hash']) for row in store.status() if row['status']=='accepted']
                save_review_attempt({'bundle':workflow.bundle,'nodes':workflow.nodes,
                    'source_quote_witness_required':workflow.source_quote_witness,
                    'proof_submissions':workflow.submissions,
                    'identities':workflow.identities,
                    'records':[v for v in accepted if v.get('schema')=='scientific-record/1'],
                    'sections':[v for v in accepted if v.get('schema')=='review-section/1']},output/'unpublished-attempt')
        except Exception as archive_exc:
            error['archive_error']={'type':type(archive_exc).__name__,'message':str(archive_exc)}
    finally:
        governor.close()
        await aclose_http_clients()
        close_http_clients()
        resources=monitor.close()
    elapsed=time.monotonic()-started
    passed=delivered and error is None and elapsed<=args.deadline
    report={'schema':'native-review-run/1','cold_run':True,'passed':passed,
        **review_delivery_flags(protocol,delivered),'within_deadline':elapsed<=args.deadline,
        'papers':len(paths),'elapsed_seconds':elapsed,'deadline_seconds':args.deadline,
        'includes_retries_repairs_verification_delivery':True,
        'automatic_semantic_repair_implemented':True,'max_semantic_repair_rounds':workflow.max_repairs,
        'repair_history':workflow.repair_history,
        'early_card_verification':getattr(workflow,'early_card_verification',False),
        'early_card_history':getattr(workflow,'early_card_history',[]),
        'repair_rounds_used':getattr(workflow,'repair_rounds_used',None),
        'provider_preferences':provider_preferences,
        'provider_preferences_by_role':routing,
        'reasoning':{'enabled':True,'effort':'low'},'worker_max_output_tokens':max(16384,reviewer_output),
        'worker_output_tokens_by_role':{'reader':16384,'writer':16384,'comparer':16384,
                                       'verifier':reviewer_output,'assembly-auditor':reviewer_output},
        'writer_reasoning_mode':writer_reasoning,
        'reviewer_reasoning_mode':reviewer_reasoning,
        'reader_reasoning_mode':reader_reasoning,
        'review_observations':getattr(args,'review_observations','quotes'),
        'closed_checks_required':getattr(args,'closed_checks',False),
        'closed_check_max_output_tokens':8192 if getattr(args,'closed_checks',False) else None,
        'closed_check_reasoning_max_tokens':(2048 if reviewer_reasoning!='off' else 0) if getattr(args,'closed_checks',False) else None,
        'proof_max_units':getattr(workflow,'proof_max_units',None),
        'source_quote_witness_experiment':getattr(workflow,'source_quote_witness',False),
        'merge_full_source':getattr(workflow,'merge_full_source',False),
        'active_token_limit':governor.config.active_token_limit,
        'error':error,'stages':stages,'tasks':store.status(),'resources':resources,
        'telemetry':governor.finish(completed=passed)}
    (output/'review-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','review_protocol','publication_verified',
        'protocol_completed_experimental','quality_validated','papers','elapsed_seconds','error')},ensure_ascii=False))
    return 0 if passed else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('sources','questions','out','skills-root','tokenizer'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--review-protocol',choices=('v1','v2'),default='v1',
        help='v2 is an experimental combined-review workflow; delivery does not imply scientific quality validation')
    parser.add_argument('--review-observations',choices=('quotes','whole-unit'),default='quotes',
        help='Experimental v2: select exact complete source parts/premise claims instead of retyping quotes; scientific judgments remain required')
    parser.add_argument('--closed-checks',action='store_true',
        help='Experimental v2: independently check each claim against only its own sources and each retention mapping against only its named destinations, in addition to the full review')
    parser.add_argument('--source-quote-witness',action='store_true',
        help='Experimental exact-quote checking for every source verifier; independent semantic judgments remain required')
    parser.add_argument('--early-card-verification',action='store_true',
        help='Verify and repair cards before comparison; reuse unchanged proofs within this cold run')
    parser.add_argument('--active-token-limit',type=int,default=1_000_000,
        help='Aggregate concurrent request reservation (200000..6400000); per-request cap remains 200000')
    parser.add_argument('--group-size',type=int,default=4)
    parser.add_argument('--proof-max-units',type=int,default=16,
        help='Experimental proof packing limit (1..128); input and full-request token caps still apply')
    parser.add_argument('--merge-full-source',action='store_true',
        help='Opt-in complete source/card duty merge only if source and independent assembly both fit current budgets; otherwise preserve the original split')
    parser.add_argument('--reviewer-max-output-tokens',type=int,choices=(16384,32768),default=16384,
        help='Experimental reviewer completion reservation; included in the unchanged 200K request cap')
    parser.add_argument('--deadline',type=float,default=5400)
    parser.add_argument('--provider',help='Optional OpenRouter provider slug; disables fallback for controlled runs')
    parser.add_argument('--coordinator-provider',
        help='Optional coordinator-only route override; workers retain --provider and all requests retain capacity checks')
    parser.add_argument('--writer-reasoning',choices=('low','off'),default='low',
        help='Experimental writer/comparer reasoning mode; does not change other roles')
    parser.add_argument('--reader-reasoning',choices=('low','off'),default='low',
        help='Experimental reader reasoning mode; default low; scientific quality requires separate validation')
    parser.add_argument('--reviewer-reasoning',choices=('low','off'),default='low',
        help='Controlled reviewer quality/latency experiment; default low; coordinator remains low')
    args=parser.parse_args()
    if args.deadline<=0 or not 1<=args.workers<=32:
        parser.error('Positive deadline and 1..32 workers required')
    if not 1<=args.proof_max_units<=128:
        parser.error('--proof-max-units must be 1..128')
    if not 200_000<=args.active_token_limit<=6_400_000:
        parser.error('--active-token-limit must be 200000..6400000')
    raise SystemExit(asyncio.run(run(args)))
