"""Experimental v2 exact deliveries; no publication/quality approval claims."""
from __future__ import annotations

import copy
from pathlib import Path
import time

from .delivery_export import _identity_data
from .hierarchical_proof import RuntimeIdentity,payload_hash
from .review_release_v2 import verify_review_release_v2,delivery_projection_v2
from .task_store import canonical


def _snapshot(result):
    if not isinstance(result,dict):raise ValueError('A workflow result or partial_snapshot dictionary is required')
    out=copy.deepcopy({k:v for k,v in result.items() if k!='identities'})
    identities=result.get('identities',{})
    if any(not isinstance(v,RuntimeIdentity) for v in identities.values()):raise ValueError('JSON identities are not trusted runtime executions')
    out['identities']=dict(identities)
    return out


def _write(result,path,*,gate,complete,deadline_at=None,native_trace_root=None):
    def deadline():
        if complete and deadline_at is not None and time.monotonic()>=deadline_at:
            raise TimeoutError('Cold-run deadline reached during experimental export')
    deadline()
    projection=None;projection_error=None
    try:projection=delivery_projection_v2(result)
    except (KeyError,TypeError,ValueError) as exc:
        if complete:raise
        projection_error={'type':type(exc).__name__,'message':str(exc)}
    root=Path(path).resolve()
    root.parent.mkdir(parents=True,exist_ok=True)
    root.mkdir(exist_ok=False)
    files={}
    def put(name,raw):
        deadline()
        target=root/name
        if not target.resolve().is_relative_to(root):raise ValueError('Unsafe experimental export member')
        if name in files:
            if files[name]['sha256']!=payload_hash(raw):raise ValueError('Export hash collision')
            return
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(raw)
        files[name]={'sha256':payload_hash(raw),'size_bytes':len(raw)}
    def putjson(name,value):put(name,canonical(value))
    putjson('audit/release-gate.json',gate)
    putjson('audit/source-inventory.json',result.get('source_inventory'))
    putjson('audit/runtime-identities.json',{'trust':'Unauthenticated provenance archive; never import as runtime identity trust',
        'identities':{key:_identity_data(value) for key,value in result.get('identities',{}).items()}})
    putjson('audit/repair-history.json',result.get('repair_history',[]))
    putjson('audit/qualification-history.json',result.get('qualification_history',[]))
    putjson('audit/tasks.json',result.get('task_status',[]))
    putjson('audit/closed-checks.json',{'required':result.get('closed_checks_required',False),
        'checks':result.get('closed_checks',{})})
    attempts=[]
    for attempt in result.get('attempt_history',[]):
        name='raw/review-attempts/'+payload_hash(attempt)+'.json'
        putjson(name,attempt);attempts.append(name)
    putjson('raw/review-attempts/index.json',attempts)
    # Flatten ONLY the archive representation. Runtime proofs/identities are not
    # regenerated; exact child artifacts remain content-addressed and auditable.
    review_index={}
    def save_review(entry):
        bundle,att=entry['bundle'],entry['attestation'];rid=bundle['review_id']
        if rid in review_index:
            if review_index[rid]['attestation_sha256']!=att['payload_sha256']:raise ValueError('Conflicting review versions')
            return rid
        shallow={k:v for k,v in bundle.items() if k!='children'}
        child_refs=[save_review(c) for c in bundle.get('children',[])]
        archive={'schema':'review-v2-archive-reference/1','bundle_without_children':shallow,
                 'children':child_refs,'original_runtime_bundle_sha256':payload_hash(bundle),
                 'attestation':att,'not_a_trust_import_format':True}
        name='audit/reviews/'+payload_hash(archive)+'.json';putjson(name,archive)
        review_index[rid]={'path':name,'attestation_sha256':att['payload_sha256']}
        return rid
    for entry in result.get('reviews',{}).values():save_review(entry)
    putjson('audit/reviews/index.json',review_index)
    putjson('raw/reader-records.json',result.get('records',[]))
    putjson('raw/final-sections.json',result.get('sections',[]))
    putjson('raw/accepted-artifacts.json',result.get('accepted_artifacts',[]))
    if native_trace_root is not None:
        trace=Path(native_trace_root).resolve()
        if trace==root or trace.is_relative_to(root) or root.is_relative_to(trace):raise ValueError('Trace and delivery roots must be separate')
        if trace.is_dir():
            trace_index={}
            for source in sorted(trace.rglob('*')):
                deadline()
                if source.is_file() and source.suffix.lower() in ('.json','.jsonl'):
                    # Native task traces contain public assigned inputs, raw
                    # submissions, conversations and lineage, never HTTP headers.
                    if not source.resolve().is_relative_to(trace):raise ValueError('Trace symlink escapes the current run')
                    raw=source.read_bytes();name='raw/native/'+payload_hash(raw)+source.suffix.lower()
                    put(name,raw)
                    trace_index[source.relative_to(trace).as_posix()]={'path':name,'sha256':payload_hash(raw)}
            putjson('raw/native/index.json',trace_index)
    prefix='' if complete else 'draft-'
    if projection is not None:
        put(prefix+'review.md',projection['full']['text'].encode('utf8'))
        put(prefix+'main-review.md',projection['main']['text'].encode('utf8'))
        putjson(prefix+'review-lines.json',projection['full']['lines'])
        putjson(prefix+'main-review-lines.json',projection['main']['lines'])
        put(prefix+'evidence-cards.md',projection['cards_markdown'])
        putjson(prefix+'evidence-cards-index.json',projection['cards_map'])
        put(prefix+'comparison-table.md',projection['comparison_markdown'])
        putjson(prefix+'comparison-table-map.json',projection['comparison_map'])
        put('comparison-cells.csv',projection['comparison_csv'])
        putjson('citations.json',projection['source_index'])
        putjson('source-spans.json',projection['source_index'])
        for pid,raw in projection['originals'].items():
            put(projection['source_index']['sources'][pid]['path'],raw)
        putjson('audit/render-scope.json',projection['scope'])
    else:
        for packet in result.get('packets',[]):
            raw=b''.join(p['text'].encode('utf8') for p in packet['parts'])
            put('sources/'+payload_hash(raw)+'.md',raw)
        putjson('projection-error.json',projection_error)
    status='實驗 v2 指定模型審查與機械重播已完成，尚未經品質對照驗收。' if complete else '實驗 v2 尚未完整通過；保留草稿與所有失敗原稿。'
    readme='# 文獻回顧（實驗 v2）\n\n'+status+'\n\n'+ '\n'.join([
        '- [主報告]('+prefix+'main-review.md)', '- [證據卡]('+prefix+'evidence-cards.md)',
        '- [比較表]('+prefix+'comparison-table.md)', '- [引用與原文定位](citations.json)',
        '- [完整章節]('+prefix+'review.md)', '- [審查軌跡](audit/reviews/index.json)'])+'\n'
    put('README.md',readme.encode('utf8'))
    for name,info in files.items():
        deadline();raw=(root/name).read_bytes()
        if payload_hash(raw)!=info['sha256'] or len(raw)!=info['size_bytes']:raise ValueError('Export bytes changed before finalization')
    deadline()
    manifest={'schema':'literature-review-delivery/2','protocol':'literature-review-v2',
        'status':'protocol_completed_experimental' if complete else 'unpublished_attempt',
        'protocol_completed_experimental':complete,'publication_verified':False,'quality_validated':False,
        'closed_checks_required':result.get('closed_checks_required',False),
        'no_model_publication_root':True,'gate':gate,'files':files,
        'limitations':['Model judgments and exact coverage are not scientific quality validation.',
                       'Identity JSON is provenance, not a trust registry; no digital signature is implied.']}
    with (root/'manifest.json').open('xb') as stream:stream.write(canonical(manifest))
    return {**manifest,'output_path':str(root),'manifest_path':str(root/'manifest.json')}


def export_review_v2(result,output_path,*,deadline_at=None,native_trace_root=None):
    snapshot=_snapshot(result)
    if snapshot.get('protocol_completed_experimental') is not True:raise ValueError('Workflow has not completed the experimental v2 protocol')
    deadline=deadline_at if deadline_at is not None else snapshot.get('deadline_at')
    gate=verify_review_release_v2(snapshot,deadline_at=deadline)
    return _write(snapshot,output_path,gate=gate,complete=True,deadline_at=deadline,native_trace_root=native_trace_root)


def save_review_attempt_v2(result,output_path,*,native_trace_root=None):
    snapshot=_snapshot(result)
    gate={'status':'incomplete','protocol_completed_experimental':False,
          'publication_verified':False,'quality_validated':False}
    try:gate={**verify_review_release_v2(snapshot),'protocol_completed_experimental':False}
    except Exception as exc:gate['error']={'type':type(exc).__name__,'message':str(exc)}
    return _write(snapshot,output_path,gate=gate,complete=False,native_trace_root=native_trace_root)
