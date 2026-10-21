"""Bounded independent verification, immutable checkpoints and assembly audit."""
import copy
import json
from pathlib import Path
from .artifacts import atomic_bytes,canonical,envelope,identifier,read_json,safe_path,write_json
from .contracts import validate
from .review import verification_packet,gate,lines_to_scan
from .sources import load_corpus
from .workflow import need,payload_hash


def packet_chars(packet):
    """Count the actual multiline serialization emitted by write_json."""
    return len(json.dumps(packet,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def slice_draft(draft,start,end):
    p=draft['payload'];mappings=[];ids=set()
    for m in p['claim_mappings']:
        overlap=m['start_char']<end and m['end_char']>start
        if overlap:
            need(start<=m['start_char']<m['end_char']<=end,'SPLIT_CLAIM','A verification boundary cuts a mapped claim')
            mappings.append(dict(m,start_char=m['start_char']-start,end_char=m['end_char']-start));ids.add(m['claim_id'])
    claims=[copy.deepcopy(c) for c in p['claims'] if c['claim_id'] in ids]
    result=envelope('ReviewDraft',dict(text=p['text'][start:end],claims=claims,claim_mappings=mappings,
        citation_map=copy.deepcopy(p['citation_map']),scan_status='not_checked',scope=p.get('scope','corpus_only')),
        producer=copy.deepcopy(draft.get('producer',{})))
    validate(result);return result


def evidence_subset(draft,evidence):
    ids={eid for c in draft['payload']['claims'] for eid in c['evidence_refs']}
    # Preserve placeholders on lines that were not declared as facts too.
    import re
    ids.update(re.findall(r'\{\{evidence:([^{}]+)\}\}',draft['payload']['text']))
    need(ids<=set(evidence),'UNKNOWN_EVIDENCE','Draft references evidence not supplied')
    return {eid:evidence[eid] for eid in sorted(ids)}


def packet_for(draft,evidence,corpus,index,max_chars):
    subset=evidence_subset(draft,evidence)
    packet=verification_packet(draft,subset,corpus,index,max_chars=10**12)
    docs={s['document_id'] for ev in subset.values() for s in ev['payload']['spans']}
    packet['source_inventory']=[d for d in packet['source_inventory'] if d['document_id'] in docs]
    packet['overall_corpus_hash']=payload_hash(index)
    need(packet_chars(packet)<=max_chars,'VERIFICATION_PACKET_TOO_LARGE','Bounded shard source context is too large')
    return packet


def boundaries(draft):
    text=draft['payload']['text'];intervals={}
    for m in draft['payload']['claim_mappings']:
        a,b=intervals.get(m['claim_id'],(m['start_char'],m['end_char']))
        intervals[m['claim_id']]=(min(a,m['start_char']),max(b,m['end_char']))
    positions=[0];cursor=0
    for line in text.splitlines(keepends=True):
        cursor+=len(line)
        if not any(a<cursor<b for a,b in intervals.values()):positions.append(cursor)
    if positions[-1]!=len(text):positions.append(len(text))
    return positions


def create_plan(draft,evidence,corpus,out,max_chars=100000,context_artifacts=None):
    validate(draft);need(draft['artifact_type']=='ReviewDraft','WRONG_ARTIFACT_TYPE','Expected ReviewDraft')
    need(max_chars>0,'BUDGET_INVALID','max_chars must be positive; it is not a token budget')
    context_artifacts=context_artifacts or []
    for a in context_artifacts:validate(a)
    index=load_corpus(corpus);positions=boundaries(draft);shards=[];packets=[];i=0
    while i<len(positions)-1:
        start=positions[i];best=None;best_end=None;low=i+1;high=i+1;step=1
        # Exponential probing avoids repeatedly materializing half a huge report
        # for every small shard. Refine only between the last fit and first miss.
        while high<len(positions):
            chunk=slice_draft(draft,start,positions[high])
            try:packet=packet_for(chunk,evidence,corpus,index,max_chars-1024)
            except Exception as exc:
                from .errors import ReviewError
                if not isinstance(exc,ReviewError) or exc.code!='VERIFICATION_PACKET_TOO_LARGE':raise
                break
            best=(chunk,packet);best_end=high;low=high+1
            if high==len(positions)-1:break
            step*=2;high=min(i+step,len(positions)-1)
        high=low-1 if best_end==len(positions)-1 else min(high-1,len(positions)-1)
        while low<=high:
            mid=(low+high)//2;end=positions[mid];chunk=slice_draft(draft,start,end)
            try:packet=packet_for(chunk,evidence,corpus,index,max_chars-1024)
            except Exception as exc:
                from .errors import ReviewError
                if not isinstance(exc,ReviewError) or exc.code!='VERIFICATION_PACKET_TOO_LARGE':raise
                high=mid-1;continue
            best=(chunk,packet);best_end=mid;low=mid+1
        need(best is not None,'OVERSIZED_VERIFICATION_UNIT',
             'One complete claim/line and its exact source context exceed the budget; split the claim or increase max_chars. Nothing was truncated.',
             {'start_char':start,'next_boundary':positions[i+1],'max_chars':max_chars})
        chunk,packet=best;end=positions[best_end];sid=identifier('verification_shard',[payload_hash(draft),start,end,payload_hash(chunk)])
        shards.append(dict(shard_id=sid,start_char=start,end_char=end,draft_hash=payload_hash(chunk),evidence_refs=sorted(evidence_subset(chunk,evidence))))
        packet['shard_id']=sid;packet['global_range']={'start_char':start,'end_char':end}
        packet['corpus_location']='../corpus';packet['location_resolution']='relative_to_packet_file'
        packet['rules']+=' Offsets in your VerificationSet are LOCAL to this shard. The caller restores global offsets; do not use global offsets in the returned scan.'
        # Added routing metadata is budgeted too.
        need(packet_chars(packet)<=max_chars,'VERIFICATION_PACKET_TOO_LARGE','Routing metadata exceeded budget; increase max_chars slightly')
        packets.append(packet);i=best_end
    plan=envelope('VerificationPlan',dict(target_artifact_id=draft['artifact_id'],target_hash=payload_hash(draft),corpus_hash=payload_hash(index),
        evidence_hashes={eid:payload_hash(ev) for eid,ev in evidence.items()},max_chars=max_chars,shards=shards,context_artifacts=context_artifacts),schema_version='2.0.0')
    validate(plan);destination=Path(out).resolve();need(not destination.exists(),'OUTPUT_CONFLICT','Use a new verification plan directory')
    # Publish plan.json last; interrupted creation is not a valid checkpoint.
    destination.mkdir(parents=True);write_json(destination/'target.json',draft)
    members=['corpus.json','coverage.json','references.json']+[d['snapshot_path'] for d in index['payload']['documents']]
    for name in members:atomic_bytes(destination/'corpus'/name,safe_path(corpus,name).read_bytes())
    for eid,ev in evidence.items():write_json(destination/'evidence'/(identifier('ev',eid)+'.json'),ev)
    for packet in packets:
        # A relocating pointer does not change source bytes or target hashes.
        need(packet_chars(packet)<=max_chars,'VERIFICATION_PACKET_TOO_LARGE','Checkpoint path overhead exceeds budget')
        write_json(destination/'packets'/(packet['shard_id']+'.json'),packet)
    for n,a in enumerate(context_artifacts):write_json(destination/'context'/f'{n:03}.json',a)
    write_json(destination/'plan.json',plan)
    return plan_status(destination)


def load_plan(directory):
    root=Path(directory);plan=read_json(root/'plan.json');validate(plan)
    need(plan['artifact_type']=='VerificationPlan','WRONG_ARTIFACT_TYPE','Expected VerificationPlan')
    draft=read_json(root/'target.json');validate(draft)
    need(draft['artifact_id']==plan['payload']['target_artifact_id'] and payload_hash(draft)==plan['payload']['target_hash'],
         'STALE_VERIFICATION','Checkpoint target changed')
    index=load_corpus(root/'corpus');need(payload_hash(index)==plan['payload']['corpus_hash'],'SOURCE_VERSION_MISMATCH','Checkpoint sources changed')
    for n,a in enumerate(plan['payload']['context_artifacts']):
        need(read_json(root/'context'/f'{n:03}.json')==a,'STALE_RESEARCH_CONTEXT','Checkpoint research context changed')
    evidence={}
    for p in (root/'evidence').glob('*.json'):
        ev=read_json(p);validate(ev);need(ev['artifact_type']=='Evidence','WRONG_ARTIFACT_TYPE','Checkpoint contains non-Evidence');evidence[ev['payload']['evidence_id']]=ev
    need({eid:payload_hash(ev) for eid,ev in evidence.items()}==plan['payload']['evidence_hashes'],'STALE_EVIDENCE','Checkpoint evidence changed')
    for s in plan['payload']['shards']:
        chunk=slice_draft(draft,s['start_char'],s['end_char'])
        expected=packet_for(chunk,evidence,root/'corpus',index,plan['payload']['max_chars'])
        expected.update(shard_id=s['shard_id'],global_range={'start_char':s['start_char'],'end_char':s['end_char']},
            corpus_location='../corpus',location_resolution='relative_to_packet_file')
        expected['rules']+=' Offsets in your VerificationSet are LOCAL to this shard. The caller restores global offsets; do not use global offsets in the returned scan.'
        need(read_json(root/'packets'/(s['shard_id']+'.json'))==expected,'VERIFICATION_PACKET_CHANGED','Checkpoint packet changed after creation')
    return plan,draft,evidence,index


def component_check(draft,evidence,corpus,index,shard,verification):
    chunk=slice_draft(draft,shard['start_char'],shard['end_char'])
    need(payload_hash(chunk)==shard['draft_hash'],'STALE_VERIFICATION','Shard no longer matches target')
    subset=evidence_subset(chunk,evidence)
    need(sorted(subset)==shard['evidence_refs'],'STALE_EVIDENCE','Shard evidence selection changed')
    need(verification['payload']['verification_method']!='independent_model_sharded_review','INVALID_VERIFICATION_PROOF','Nested sharded proofs are not supported')
    gate(chunk,subset,corpus,index,verification)
    return chunk


def submit_verification(directory,shard_id,verification):
    plan,draft,evidence,index=load_plan(directory)
    shard=next((s for s in plan['payload']['shards'] if s['shard_id']==shard_id),None)
    need(shard is not None,'TASK_MISMATCH','Unknown verification shard')
    component_check(draft,evidence,Path(directory)/'corpus',index,shard,verification)
    path=Path(directory)/'records'/(shard_id+'.json')
    if path.exists():need(read_json(path)==verification,'OUTPUT_CONFLICT','Accepted verifier records are immutable; create a revision plan')
    else:write_json(path,verification)
    return {'status':'accepted','shard_id':shard_id,'quality':'component_passed; assembly_audit_pending'}


def plan_status(directory):
    plan,draft,evidence,index=load_plan(directory);complete=[];pending=[]
    for shard in plan['payload']['shards']:
        path=Path(directory)/'records'/(shard['shard_id']+'.json')
        if path.exists():
            component_check(draft,evidence,Path(directory)/'corpus',index,shard,read_json(path));complete.append(shard['shard_id'])
        else:pending.append({'shard_id':shard['shard_id'],'packet_path':str((Path(directory)/'packets'/(shard['shard_id']+'.json')).resolve())})
    return {'plan_id':plan['artifact_id'],'plan_hash':payload_hash(plan),'shards_total':len(plan['payload']['shards']),
        'accepted':complete,'pending':pending,'quality':'unverified','next_step':'verify_pending_shards' if pending else 'independent_assembly_audit'}


def assembly_packet(directory):
    plan,draft,evidence,index=load_plan(directory);progress=plan_status(directory)
    need(not progress['pending'],'INCOMPLETE_VERIFICATION','Finish all source-review shards first',progress['pending'])
    p=draft['payload'];outline=[{'start_char':line['start_char'],'heading':line['text'].strip()} for line in lines_to_scan(p['text']) if line['text'].startswith('#')]
    return {'target_artifact_id':draft['artifact_id'],'target_hash':payload_hash(draft),'plan_hash':payload_hash(plan),
        'target_path':str((Path(directory)/'target.json').resolve()),'corpus_location':str((Path(directory)/'corpus').resolve()),
        'context_paths':[str((Path(directory)/'context'/f'{n:03}.json').resolve()) for n in range(len(plan['payload']['context_artifacts']))],
        'outline':outline,'claims_total':len(p['claims']),'nonempty_lines_total':len(lines_to_scan(p['text'])),
        'accepted_shards':progress['accepted'],'writer_context':draft.get('producer',{}).get('context_id'),
        'verifier_contexts':[read_json(Path(directory)/'records'/(s+'.json')).get('producer',{}).get('context_id') for s in progress['accepted']],
        'required_checks':['coverage','citation_consistency','scope','counterevidence','question_coverage'],
        'rules':'Use a new actual task context distinct from writer and source verifiers. Source support was checked by all listed shards. Independently inspect the target and ALL context artifacts in bounded reads; check whole-report scope, source versions, retained counterevidence, answered/unresolved questions and cross-section consistency. Return AssemblyAudit v2 with exact target/plan hashes, concrete reasons for every check and typed issues. Do not claim passed if you cannot inspect the necessary context.'}


def audit_check(plan,draft,records,audit):
    validate(audit);need(audit['artifact_type']=='AssemblyAudit','WRONG_ARTIFACT_TYPE','Expected AssemblyAudit')
    p=audit['payload'];need(p['target_artifact_id']==draft['artifact_id'] and p['target_hash']==payload_hash(draft) and p['plan_hash']==payload_hash(plan),
        'STALE_ASSEMBLY_AUDIT','Assembly audit refers to a different plan or report')
    context=audit.get('producer',{}).get('context_id')
    used={draft.get('producer',{}).get('context_id')}|{r.get('producer',{}).get('context_id') for r in records.values()}
    need(context and context not in used,'INDEPENDENT_CONTEXT_REQUIRED','Assembly auditor must use a new actual task context')
    need(not p['issues'] and all(c['status']=='passed' for c in p['checks'].values()),'ASSEMBLY_AUDIT_FAILED','Assembly checks contain unresolved issues')


def assemble_record(plan,draft,evidence,records,audit):
    audit_check(plan,draft,records,audit);verdicts=[];scans=[];seen=set();end=0
    for s in plan['payload']['shards']:
        need(s['start_char']==end,'INCOMPLETE_VERIFICATION','Verification shards have gaps/overlaps');end=s['end_char']
        v=records[s['shard_id']]['payload']
        for verdict in v['verdicts']:
            need(verdict['claim_id'] not in seen,'DUPLICATE_VERDICT','A claim was split across verification contexts')
            seen.add(verdict['claim_id']);verdicts.append(copy.deepcopy(verdict))
        scans.extend([dict(x,start_char=x['start_char']+s['start_char'],end_char=x['end_char']+s['start_char']) for x in v['scan_findings']])
    need(end==len(draft['payload']['text']),'INCOMPLETE_VERIFICATION','Verification shards do not cover the report end')
    result=envelope('VerificationSet',dict(target_artifact_id=draft['artifact_id'],target_hash=payload_hash(draft),
        evidence_hashes={eid:payload_hash(ev) for eid,ev in evidence.items()},locator_checks=[],verdicts=verdicts,issues=[],scan_completed=True,
        scan_findings=scans,verification_method='independent_model_sharded_review',
        sharded_proof={'plan':plan,'records':records,'assembly_audit':audit}),producer=copy.deepcopy(audit.get('producer',{})))
    validate(result);return result


def merge_verifications(directory,audit):
    plan,draft,evidence,index=load_plan(directory);progress=plan_status(directory)
    need(not progress['pending'],'INCOMPLETE_VERIFICATION','Cannot merge missing shards')
    records={s['shard_id']:read_json(Path(directory)/'records'/(s['shard_id']+'.json')) for s in plan['payload']['shards']}
    result=assemble_record(plan,draft,evidence,records,audit)
    gate(draft,evidence,Path(directory)/'corpus',index,result)
    return result


def validate_sharded_proof(draft,evidence,corpus,index,verification):
    proof=verification['payload'].get('sharded_proof');need(isinstance(proof,dict),'INVALID_VERIFICATION_PROOF','Missing sharded verification proof')
    plan=proof.get('plan');validate(plan)
    need(plan['artifact_type']=='VerificationPlan','WRONG_ARTIFACT_TYPE','Expected VerificationPlan')
    p=plan['payload'];need(p['target_hash']==payload_hash(draft) and p['target_artifact_id']==draft['artifact_id'] and p['corpus_hash']==payload_hash(index),
        'STALE_VERIFICATION','Sharded proof targets different report or corpus')
    need(set(p['evidence_hashes'])<=set(evidence) and all(payload_hash(evidence[eid])==h for eid,h in p['evidence_hashes'].items()),'STALE_EVIDENCE','Sharded proof evidence changed')
    evidence={eid:evidence[eid] for eid in p['evidence_hashes']}
    records=proof.get('records',{});need(set(records)=={s['shard_id'] for s in p['shards']},'INCOMPLETE_VERIFICATION','Proof is missing shard records')
    for s in p['shards']:component_check(draft,evidence,corpus,index,s,records[s['shard_id']])
    reconstructed=assemble_record(plan,draft,evidence,records,proof['assembly_audit'])
    need(reconstructed['payload']==verification['payload'] and reconstructed.get('producer')==verification.get('producer'),
        'INVALID_VERIFICATION_PROOF','Merged verdicts/scans differ from component proofs')
