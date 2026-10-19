"""Extended CLI, separated to keep legacy single-artifact operations stable."""
from pathlib import Path
from .artifacts import read_json,write_json
from .contracts import validate
from .workflow import init_job,next_task,submit,status,assemble,rebuild,cancel,retry,need
from .review import draft_from_sections,verification_packet,deliver
from .sources import load_corpus


def add_commands(sub):
    from .research_commands import add_commands as add_research
    add_research(sub)
    job=sub.add_parser('job',help='Harness-driven reading queue and restartable checkpoints')
    actions=job.add_subparsers(dest='action',required=True)
    p=actions.add_parser('init');p.add_argument('--corpus',required=True);p.add_argument('--out',required=True);p.add_argument('--config',required=True)
    p.add_argument('--max-chars',type=int,default=16000);p.add_argument('--model-config',default='unknown')
    for name in ['next','submit','status','assemble','rebuild','cancel','retry']:
        p=actions.add_parser(name);p.add_argument('--job',required=True)
        if name=='next':
            p.add_argument('--worker',required=True);p.add_argument('--lease-seconds',type=int,default=600)
        if name=='submit':
            p.add_argument('response');p.add_argument('--worker',required=True)
        if name in ('cancel','retry'):
            p.add_argument('--task-id',required=True)
        if name=='assemble':
            p.add_argument('--out',required=True)
    p=sub.add_parser('draft',help='Build a mapped ReviewDraft from structured claim sections')
    p.add_argument('sections');p.add_argument('--context-id',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('verification-packet',help='Prepare original source context for a separate verifier')
    p.add_argument('draft');p.add_argument('--corpus',required=True);p.add_argument('--evidence',action='append',default=[])
    p.add_argument('--out',required=True);p.add_argument('--max-chars',type=int,default=100000)
    p=sub.add_parser('deliver',help='Publish full-corpus report only after source, semantic, appendix and matrix gates pass')
    p.add_argument('--job',required=True);p.add_argument('--draft',required=True);p.add_argument('--verification',required=True)
    p.add_argument('--comparison',required=True);p.add_argument('--evidence',action='append',default=[]);p.add_argument('--out',required=True)
    p.add_argument('--comparison-verification')
    p.add_argument('--field-assessment',action='append',default=[],help='Apply explicit paper field assessments in revision order')
    p=sub.add_parser('capability-check',help='Check capability invariants; never grants semantic approval')
    p.add_argument('artifact')
    p=sub.add_parser('assess-fields',help='Apply an explicit missing-field assessment to a new analysis revision')
    p.add_argument('analysis');p.add_argument('--assessment',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('task-result',help='Write a v2 actionable task response without performing model work')
    p.add_argument('--task-id',required=True);p.add_argument('--status',required=True,choices=['succeeded','partial','needs_input','failed','cancelled'])
    p.add_argument('--issues');p.add_argument('--artifact-ref',action='append',default=[]);p.add_argument('--context-id',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('handoff',help='Generate paired JSON/Markdown and a hash-bound portable manifest')
    p.add_argument('artifact');p.add_argument('--material',action='append',default=[]);p.add_argument('--corpus');p.add_argument('--out',required=True)
    p=sub.add_parser('handoff-check',help='Detect changed generated projections and bundle materials')
    p.add_argument('directory')
    for name in ['comparison-packet','comparison-accept','comparison-check']:
        p=sub.add_parser(name,help='Independent comparison verification; no report job required')
        p.add_argument('comparison');p.add_argument('--corpus',required=True);p.add_argument('--evidence',action='append',default=[])
        if name=='comparison-packet':p.add_argument('--max-chars',type=int,default=100000)
        else:p.add_argument('--verification',required=True)
        if name!='comparison-check':p.add_argument('--out',required=True)
    p=sub.add_parser('adapter',help='Check declared harness capabilities; file-mailbox transport is portable fallback')
    p.add_argument('harness',choices=['codex','claude-code','opencode','deepagents']);p.add_argument('--probe',required=True);p.add_argument('--out')
    p=sub.add_parser('reuse',help='Copy compatible accepted tasks into a new revision job; unknown model config is never reused')
    p.add_argument('--from-job',required=True);p.add_argument('--to-job',required=True)


def run_extended(args):
    from .research_commands import run as run_research
    extended=run_research(args)
    if extended is not None:return extended
    from .cli import _evidence
    if args.command=='capability-check':
        from .capabilities import capability_check
        return capability_check(read_json(args.artifact))
    if args.command=='assess-fields':
        from .capabilities import apply_assessments
        result=apply_assessments(read_json(args.analysis),read_json(args.assessment))
        write_json(args.out,result);return {'path':args.out,'artifact_id':result['artifact_id'],'quality':'unverified'}
    if args.command=='task-result':
        from .capabilities import task_result
        result=task_result(args.task_id,args.status,read_json(args.issues) if args.issues else [],args.artifact_ref,context_id=args.context_id)
        write_json(args.out,result);return {'path':args.out,'status':result['payload']['status'],'quality':'unverified'}
    if args.command=='handoff':
        from .handoff import write_handoff
        materials=[]
        for path in args.material:
            if Path(path).suffix=='.jsonl':
                from .review import read_jsonl
                materials.extend(read_jsonl(path))
            else:
                value=read_json(path)
                materials.extend(value if isinstance(value,list) else [value])
        from .artifacts import envelope
        if any(not isinstance(m,dict) for m in materials):
            from .errors import ReviewError
            raise ReviewError('SCHEMA_INVALID','Materials must be artifact objects or bare Claim records')
        materials=[envelope('Claim',m) if 'artifact_type' not in m and 'claim_id' in m else m for m in materials]
        return write_handoff(read_json(args.artifact),args.out,materials,args.corpus)
    if args.command=='handoff-check':
        from .handoff import check_handoff
        return check_handoff(args.directory)
    if args.command in ('comparison-packet','comparison-accept','comparison-check'):
        from .comparison import comparison_packet,bind_verification,comparison_gate
        comparison=read_json(args.comparison);evidence=_evidence(args.evidence);index=load_corpus(args.corpus)
        if args.command=='comparison-packet':
            packet=comparison_packet(comparison,evidence,args.corpus,index,args.max_chars)
            write_json(args.out,packet);return {'path':args.out,'target_hash':packet['target_hash']}
        if args.command=='comparison-accept':
            result=bind_verification(comparison,read_json(args.verification),evidence,args.corpus,index)
            write_json(args.out,result);return {'path':args.out,'quality':'passed','manual_review':'not_performed'}
        return comparison_gate(comparison,evidence,args.corpus,index,read_json(args.verification))
    if args.command=='job':
        if args.action=='init':
            return init_job(args.corpus,args.out,read_json(args.config),args.max_chars,args.model_config)
        if args.action=='next':
            result=next_task(args.job,args.worker,args.lease_seconds)
            if 'task' in result:
                task=result.pop('task');tid=task['payload']['task_id']
                result['task_path']=str((Path(args.job)/'tasks'/(tid+'.json')).resolve())
                result['task_id']=tid
            return result
        if args.action=='submit':
            return submit(args.job,read_json(args.response),args.worker)
        if args.action=='status':return status(args.job)
        if args.action=='assemble':return assemble(args.job,args.out)
        if args.action=='rebuild':rebuild(args.job);return status(args.job)
        if args.action=='cancel':return cancel(args.job,args.task_id)
        if args.action=='retry':return retry(args.job,args.task_id)
    if args.command=='draft':
        artifact=draft_from_sections(read_json(args.sections),args.context_id)
        write_json(args.out,artifact);return {'path':args.out,'artifact_id':artifact['artifact_id']}
    if args.command=='verification-packet':
        packet=verification_packet(read_json(args.draft),_evidence(args.evidence),args.corpus,load_corpus(args.corpus),args.max_chars)
        write_json(args.out,packet);return {'path':args.out,'target_hash':packet['target_hash']}
    if args.command=='deliver':
        return deliver(args.job,read_json(args.draft),_evidence(args.evidence),read_json(args.verification),read_json(args.comparison),args.out,
            read_json(args.comparison_verification) if args.comparison_verification else None,[read_json(p) for p in args.field_assessment])
    if args.command=='adapter':
        from .harness import check_capabilities
        result=check_capabilities(args.harness,read_json(args.probe))
        if args.out:write_json(args.out,result)
        return result
    if args.command=='reuse':
        from .workflow import reuse
        return reuse(args.from_job,args.to_job)
    return None
