"""v0.5 research, report supplementation and resumable verification CLI."""
from pathlib import Path
from .artifacts import read_json,write_json
from .sources import load_corpus


def add_commands(sub):
    p=sub.add_parser('comparison-draft',help='Project a full comparison for bounded verification without building an oversized packet')
    p.add_argument('comparison');p.add_argument('--out',required=True)
    p=sub.add_parser('research-request',help='Freeze research questions and complete corpus scope')
    p.add_argument('--corpus',required=True);p.add_argument('--spec',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('augment-request',help='Derive research questions from exact report gaps')
    p.add_argument('--corpus',required=True);p.add_argument('--augmentation-plan',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('corpus-search',help='Search every question across every supplied paper; never a reading substitute')
    p.add_argument('--corpus',required=True);p.add_argument('--request',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('question-map-template',help='Create an explicitly unreviewed full paper/question template')
    p.add_argument('--job',required=True);p.add_argument('--request',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('research-check',help='Check full search, reading and semantic-disposition coverage')
    for name in ['request','search','question-map','job']:p.add_argument('--'+name,required=True)
    p.add_argument('--evidence',action='append',default=[])
    p=sub.add_parser('augmentation-plan',help='Bind gap anchors to the immutable original report')
    p.add_argument('--report',required=True);p.add_argument('--gaps',required=True);p.add_argument('--context-id',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('augmentation-draft',help='Build a source-checkable projection of report gaps and proposed patches')
    p.add_argument('--augmentation-plan',required=True);p.add_argument('--resolutions',required=True);p.add_argument('--corpus',required=True)
    p.add_argument('--evidence',action='append',default=[]);p.add_argument('--out',required=True)
    p=sub.add_parser('verification-plan',help='Build bounded, immutable source-verification shards')
    p.add_argument('draft');p.add_argument('--corpus',required=True);p.add_argument('--evidence',action='append',default=[])
    p.add_argument('--context',action='append',default=[]);p.add_argument('--max-chars',type=int,default=100000);p.add_argument('--out',required=True)
    p=sub.add_parser('verification-status',help='Validate checkpoints and list only pending verifier shards')
    p.add_argument('--plan',required=True)
    p=sub.add_parser('verification-submit',help='Accept one independent shard verdict after source/scan gates')
    p.add_argument('verification');p.add_argument('--plan',required=True);p.add_argument('--shard',required=True)
    p=sub.add_parser('verification-assembly-packet',help='Prepare the separate whole-report assembly audit')
    p.add_argument('--plan',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('verification-merge',help='Merge complete verified shards plus independent assembly audit')
    p.add_argument('--plan',required=True);p.add_argument('--audit',required=True);p.add_argument('--out',required=True)
    for command in ['review-deliver','augment-deliver']:
        p=sub.add_parser(command,help='Deliver complete evidence-backed research with question coverage gates')
        for name in ['job','request','search','question-map','verification','out']:p.add_argument('--'+name,required=True)
        p.add_argument('--evidence',action='append',default=[])
        if command=='review-deliver':
            p.add_argument('--draft',required=True);p.add_argument('--comparison',required=True);p.add_argument('--comparison-verification')
            p.add_argument('--field-assessment',action='append',default=[])
        else:
            for name in ['report','augmentation-plan','resolutions']:p.add_argument('--'+name,required=True)


def run(args):
    from .cli import _evidence
    command=args.command
    if command=='comparison-draft':
        from .comparison import comparison_draft
        result=comparison_draft(read_json(args.comparison));write_json(args.out,result)
        return {'path':args.out,'quality':'unverified'}
    if command=='research-request':
        from .research import request_from_spec
        result=request_from_spec(read_json(args.spec),load_corpus(args.corpus));write_json(args.out,result)
        return {'path':args.out,'artifact_id':result['artifact_id'],'quality':'unverified'}
    if command=='augment-request':
        from .augmentation import augment_request
        result=augment_request(read_json(args.augmentation_plan),load_corpus(args.corpus));write_json(args.out,result)
        return {'path':args.out,'artifact_id':result['artifact_id']}
    if command=='corpus-search':
        from .research import search_corpus
        result=search_corpus(read_json(args.request),args.corpus);write_json(args.out,result)
        return {'path':args.out,'paper_question_records':len(result['payload']['records']),
            'hits':sum(len(r['hits']) for r in result['payload']['records']),'reading_performed':False}
    if command=='question-map-template':
        from .research import map_template
        result=map_template(read_json(args.request),args.job);write_json(args.out,result)
        return {'path':args.out,'quality':'template_not_ready','required':'Read every paper, replace reasons/status/evidence and remove template flag.'}
    if command=='research-check':
        from .research import check_research_coverage
        return check_research_coverage(read_json(args.request),read_json(args.search),read_json(args.question_map),args.job,_evidence(args.evidence))
    if command=='augmentation-plan':
        from .augmentation import make_plan
        result=make_plan(Path(args.report).read_bytes().decode('utf-8'),read_json(args.gaps),args.context_id);write_json(args.out,result)
        return {'path':args.out,'gaps':len(result['payload']['gaps'])}
    if command=='augmentation-draft':
        from .augmentation import augmentation_draft
        result=augmentation_draft(read_json(args.augmentation_plan),read_json(args.resolutions),_evidence(args.evidence),load_corpus(args.corpus))
        write_json(args.out,result);return {'path':args.out,'artifact_id':result['artifact_id']}
    if command=='verification-plan':
        from .sharding import create_plan
        return create_plan(read_json(args.draft),_evidence(args.evidence),args.corpus,args.out,args.max_chars,[read_json(p) for p in args.context])
    if command=='verification-status':
        from .sharding import plan_status
        return plan_status(args.plan)
    if command=='verification-submit':
        from .sharding import submit_verification
        return submit_verification(args.plan,args.shard,read_json(args.verification))
    if command=='verification-assembly-packet':
        from .sharding import assembly_packet
        result=assembly_packet(args.plan);write_json(args.out,result);return {'path':args.out,'plan_hash':result['plan_hash']}
    if command=='verification-merge':
        from .sharding import merge_verifications
        result=merge_verifications(args.plan,read_json(args.audit));write_json(args.out,result)
        return {'path':args.out,'quality':'passed','verification_method':'independent_model_sharded_review','manual_review':'not_performed'}
    if command=='review-deliver':
        from .review import deliver
        return deliver(args.job,read_json(args.draft),_evidence(args.evidence),read_json(args.verification),read_json(args.comparison),args.out,
            read_json(args.comparison_verification) if args.comparison_verification else None,[read_json(p) for p in args.field_assessment],
            {'request':read_json(args.request),'search':read_json(args.search),'mapping':read_json(args.question_map)})
    if command=='augment-deliver':
        from .augmentation import deliver_augmentation
        return deliver_augmentation(Path(args.report).read_bytes().decode('utf-8'),read_json(args.augmentation_plan),read_json(args.resolutions),
            read_json(args.request),read_json(args.search),read_json(args.question_map),args.job,_evidence(args.evidence),read_json(args.verification),args.out)
    return None
