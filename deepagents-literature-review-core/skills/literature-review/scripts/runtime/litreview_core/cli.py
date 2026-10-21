import argparse
import csv
import json
from pathlib import Path
import sys
import tarfile
from . import __version__
from .artifacts import atomic_bytes, digest, envelope, identifier, read_json, safe_path, write_json
from .artifacts.importer import import_artifact
from .contracts import migrate, validate, validate_object
from .errors import ReviewError
from .sources import load_corpus, prepare
from .sources.evidence import locate, make_evidence
from .verification import inspect_artifact
from .rendering import render


def _evidence(paths):
    result={}
    for path in paths or []:
        if Path(path).suffix.lower()=='.jsonl':
            import json
            try:artifacts=[json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]
            except ValueError as exc:raise ReviewError('INVALID_JSON','Invalid evidence JSONL',str(exc)) from exc
        else:artifacts=[read_json(path)]
        for art in artifacts:
            art=validate(art)
            if art['artifact_type']!='Evidence':
                raise ReviewError('WRONG_ARTIFACT_TYPE','--evidence expects Evidence JSON or JSONL')
            eid=art['payload']['evidence_id']
            if eid in result and result[eid]!=art:
                raise ReviewError('DUPLICATE_ID','Evidence ID has different definitions',eid)
            result[eid]=art
    return result


def parser():
    root=argparse.ArgumentParser(description='Corpus-only literature review tools. Model work runs in the harness.')
    root.add_argument('--version',action='version',version=__version__)
    sub=root.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare',help='Freeze local Markdown and build byte indexes')
    p.add_argument('input_dir');p.add_argument('--out',required=True);p.add_argument('--manifest');p.add_argument('--max-papers',type=int,default=100)
    p=sub.add_parser('evidence',help='Create program-checked evidence')
    p.add_argument('--corpus',required=True);p.add_argument('--document',required=True);p.add_argument('--quote');p.add_argument('--quote-file')
    p.add_argument('--start-byte',type=int);p.add_argument('--end-byte',type=int);p.add_argument('--spans',help='JSON list of exact spans')
    p.add_argument('--source-role',default='context');p.add_argument('--out',required=True)
    p=sub.add_parser('import-artifact',help='Import native JSON, report, notes, CSV or bibliography')
    p.add_argument('path');p.add_argument('--kind',choices=['native','report','notes','csv','bibliography'],default='native')
    p.add_argument('--bibliography');p.add_argument('--out',required=True)
    p=sub.add_parser('validate',help='Check schemas and optional source locators; never grants semantic approval')
    p.add_argument('artifact');p.add_argument('--corpus');p.add_argument('--evidence',action='append',default=[])
    p=sub.add_parser('collect',help='Validate then atomically store an independent artifact; no queue state changes')
    p.add_argument('artifact');p.add_argument('--store',required=True);p.add_argument('--corpus')
    p=sub.add_parser('status',help='Show source inventory and honest unverified coverage')
    p.add_argument('--corpus',required=True)
    p=sub.add_parser('render',help='Render a numbered draft; use deliver with independent verification for final reports')
    p.add_argument('draft');p.add_argument('--corpus',required=True);p.add_argument('--evidence',action='append',default=[])
    p.add_argument('--out',required=True);p.add_argument('--final',action='store_true')
    p=sub.add_parser('export',help='Export frozen corpus and optional public artifacts; no private DB required')
    p.add_argument('--corpus',required=True);p.add_argument('--artifact',action='append',default=[]);p.add_argument('--out',required=True)
    p=sub.add_parser('migrate',help='Explicit migration registry; v0.1 supports identity only')
    p.add_argument('artifact');p.add_argument('--target',default='1.0.0');p.add_argument('--out',required=True)
    p=sub.add_parser('task',help='Create a standalone self-contained task, without dispatching it')
    actions=p.add_subparsers(dest='task_command',required=True)
    t=actions.add_parser('create');t.add_argument('--capability',required=True);t.add_argument('--input',action='append',default=[])
    t.add_argument('--request',required=True);t.add_argument('--profile',required=True);t.add_argument('--output-location',required=True);t.add_argument('--out',required=True)
    from .commands import add_commands
    add_commands(sub)
    return root


def run(args):
    from .commands import run_extended
    extended=run_extended(args)
    if extended is not None:
        return extended
    cmd=args.command
    if cmd=='prepare':
        result=prepare(args.input_dir,args.out,args.manifest,args.max_papers)
        return {'corpus':str(Path(args.out).resolve()),'documents':len(result['payload']['documents']),
                'papers':result['payload']['logical_paper_count'],'execution':'partial','quality':'unverified'}
    if cmd=='import-artifact':
        bibliography=read_json(args.bibliography) if args.bibliography else None
        artifact=import_artifact(args.path,args.kind,bibliography)
        write_json(args.out,artifact)
        return {'artifact_id':artifact['artifact_id'],'path':args.out,'semantic_status':'not_checked'}
    if cmd=='migrate':
        artifact=migrate(read_json(args.artifact),args.target)
        write_json(args.out,artifact)
        return {'path':args.out,'schema_version':artifact['schema_version']}
    if cmd=='task':
        profile=read_json(args.profile)
        validate_object('RunConfig',profile)
        payload=dict(task_id=identifier('task',[args.capability,args.input,args.request,profile,args.output_location]),
            capability=args.capability,input_artifact_refs=args.input,request=args.request,profile=profile,output_location=args.output_location)
        artifact=envelope('TaskSpec',payload)
        validate(artifact);write_json(args.out,artifact)
        return {'task_id':payload['task_id'],'dispatch':'not_started'}
    if cmd in ('evidence','status','render','export') or getattr(args,'corpus',None):
        index=load_corpus(args.corpus)
    else:
        index=None
    if cmd=='evidence':
        if args.spans:
            if any(v is not None for v in (args.quote,args.quote_file,args.start_byte,args.end_byte)):
                raise ReviewError('ARGUMENT_CONFLICT','Use spans or quote options, not both')
            spans=read_json(args.spans)
            if not isinstance(spans,list):
                raise ReviewError('SCHEMA_INVALID','--spans requires a JSON array')
        else:
            if (args.quote is None)==(args.quote_file is None):
                raise ReviewError('ARGUMENT_REQUIRED','Specify exactly one of --quote and --quote-file')
            quote=Path(args.quote_file).read_bytes().decode('utf-8') if args.quote_file else args.quote
            spans=[locate(args.corpus,index,args.document,quote,args.start_byte,args.end_byte)]
        artifact=make_evidence(args.corpus,index,spans,args.source_role)
        write_json(args.out,artifact)
        return {'evidence_id':artifact['payload']['evidence_id'],'locator_status':'valid','semantic_status':'not_checked'}
    if cmd=='validate':
        result=inspect_artifact(read_json(args.artifact),args.corpus,index,_evidence(args.evidence) if args.evidence else None)
        return result
    if cmd=='collect':
        artifact=validate(read_json(args.artifact))
        result=inspect_artifact(artifact,args.corpus,index)
        if result['mechanical_status']=='failed':
            raise ReviewError('STRUCTURAL_GATE_FAILED','Artifact not accepted',result['issues'])
        destination=safe_path(args.store,artifact['artifact_id']+'.json')
        write_json(destination,artifact)
        return {'path':str(destination),'schema_valid':True,'quality':'unverified','queue_status':'standalone_artifact; use job submit to update reading coverage'}
    if cmd=='status':
        coverage=validate(read_json(Path(args.corpus)/'coverage.json'))
        counts={}
        for record in coverage['payload']['records']:
            counts[record['status']]=counts.get(record['status'],0)+1
        return {'documents':len(index['payload']['documents']),'papers':index['payload']['logical_paper_count'],
            'content_blocks':sum(b['kind']!='format' for b in index['payload']['blocks']),
            'coverage_records':counts,'execution':'partial','quality':'unverified',
            'note':'This is the frozen source inventory. For accepted model analysis coverage use job status --job JOB.'}
    if cmd=='render':
        draft=validate(read_json(args.draft))
        if draft['artifact_type']!='ReviewDraft':
            raise ReviewError('WRONG_ARTIFACT_TYPE','Expected ReviewDraft')
        evidence=_evidence(args.evidence)
        text,ledger=render(draft,evidence,args.corpus,index,args.final)
        # Commit sidecar first. A crash cannot leave a report without its audit data.
        write_json(str(args.out)+'.ledger.json',ledger)
        atomic_bytes(args.out,text.encode('utf-8'))
        return {'path':args.out,'ledger':str(args.out)+'.ledger.json','quality':'unverified','mode':'draft'}
    if cmd=='export':
        import io
        files={}
        for filename in ['corpus.json','coverage.json','references.json']:
            files[filename]=(Path(args.corpus)/filename).read_bytes()
        for doc in index['payload']['documents']:
            files[doc['snapshot_path']]=safe_path(args.corpus,doc['snapshot_path']).read_bytes()
        for path in args.artifact:
            artifact=validate(read_json(path))
            report=inspect_artifact(artifact,args.corpus,index)
            if report['mechanical_status']=='failed':
                raise ReviewError('STRUCTURAL_GATE_FAILED','Invalid exported artifact',report['issues'])
            name='artifacts/'+artifact['artifact_id']+'.json'
            content=(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n').encode()
            if name in files and files[name]!=content:
                raise ReviewError('DUPLICATE_ID','Conflicting exported artifact IDs',name)
            files[name]=content
        files['checksums.json']=(json.dumps({n:digest(b) for n,b in files.items()},indent=2)+'\n').encode()
        buffer=io.BytesIO()
        with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
            for name,content in sorted(files.items()):
                info=tarfile.TarInfo(name);info.size=len(content);info.mode=0o644
                archive.addfile(info,io.BytesIO(content))
        atomic_bytes(args.out,buffer.getvalue())
        return {'path':args.out,'files':len(files),'quality':'unverified'}
    raise ReviewError('UNKNOWN_COMMAND','Unsupported command')


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        result=run(args)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if result.get('mechanical_status')=='failed' else 0
    except (ReviewError,OSError,UnicodeError,csv.Error) as exc:
        error=exc.as_dict() if isinstance(exc,ReviewError) else {'code':'IO_ERROR','message':str(exc)}
        print(json.dumps({'error':error},ensure_ascii=False),file=sys.stderr)
        return 2

