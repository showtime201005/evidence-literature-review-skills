"""Corpus-wide discovery and question coverage; retrieval never replaces reading."""
from pathlib import Path
import re
from .artifacts import atomic_bytes,canonical,envelope,read_json,write_json
from .contracts import validate
from .sources import load_corpus,source_bytes
from .workflow import need,payload_hash,job_plan,load_task,status


def request_from_spec(spec,index):
    p=dict(spec,source_policy='corpus_only',corpus_hash=payload_hash(index),
           paper_ids=sorted({d['paper_id'] for d in index['payload']['documents']}))
    request=envelope('ReviewRequest',p,schema_version='2.0.0');validate(request)
    return request


def check_request(request,index):
    validate(request)
    need(request['artifact_type']=='ReviewRequest','WRONG_ARTIFACT_TYPE','Expected ReviewRequest')
    p=request['payload']
    need(p['corpus_hash']==payload_hash(index),'SOURCE_VERSION_MISMATCH','Research request targets a different corpus')
    need(set(p['paper_ids'])=={d['paper_id'] for d in index['payload']['documents']},'INCOMPLETE_RESEARCH_SCOPE','Research must include every provided logical paper')


def search_corpus(request,corpus,index=None):
    index=index or load_corpus(corpus);check_request(request,index);p=request['payload'];records=[]
    docs=index['payload']['documents'];blocks=index['payload']['blocks']
    raw={d['document_id']:source_bytes(corpus,d) for d in docs}
    for q in p['questions']:
        patterns=[(term,re.compile(re.escape(term),re.IGNORECASE)) for term in q['terms']]
        for pid in p['paper_ids']:
            own=[d for d in docs if d['paper_id']==pid];ids={d['document_id'] for d in own}
            searched=[b for b in blocks if b['document_id'] in ids and b['kind']!='format'];hits=[]
            for block in searched:
                text=raw[block['document_id']][block['start_byte']:block['end_byte']].decode('utf-8')
                for term,pattern in patterns:
                    for m in pattern.finditer(text):
                        start=block['start_byte']+len(text[:m.start()].encode('utf-8'))
                        hits.append(dict(term=term,document_id=block['document_id'],content_hash=block['content_hash'],
                            start_byte=start,end_byte=start+len(m[0].encode('utf-8')),excerpt=m[0]))
            records.append(dict(question_id=q['question_id'],paper_id=pid,document_ids=sorted(ids),blocks_searched=len(searched),hits=hits))
    ledger=envelope('SearchLedger',dict(request_id=request['artifact_id'],request_hash=payload_hash(request),
        corpus_hash=payload_hash(index),records=records),schema_version='2.0.0');validate(ledger)
    return ledger


def checked_parts_by_paper(job):
    plan,index=job_plan(job);parts={pid:set() for pid in {d['paper_id'] for d in index['payload']['documents']}}
    for tid in plan['task_ids']:
        task=load_task(job,tid)['payload'];parts[task['paper_id']].update(p['part_id'] for p in task['parts'])
    return parts


def map_template(request,job):
    _,index=job_plan(job);check_request(request,index);parts=checked_parts_by_paper(job)
    result=envelope('QuestionEvidenceMap',dict(request_id=request['artifact_id'],request_hash=payload_hash(request),
        corpus_hash=payload_hash(index),records=[dict(question_id=q['question_id'],paper_id=pid,status='uncertain',support_refs=[],counter_refs=[],
            reason='MODEL_REVIEW_REQUIRED',checked_part_ids=sorted(parts[pid])) for q in request['payload']['questions'] for pid in request['payload']['paper_ids']]),schema_version='2.0.0')
    result['template']=True
    return result


def check_research_coverage(request,search,mapping,job,evidence):
    _,index=job_plan(job);check_request(request,index);validate(search);validate(mapping)
    need(search['artifact_type']=='SearchLedger' and mapping['artifact_type']=='QuestionEvidenceMap','WRONG_ARTIFACT_TYPE','Expected SearchLedger and QuestionEvidenceMap')
    need(status(job)['execution']=='complete','INCOMPLETE_COVERAGE','Read all supplied texts before claiming question coverage')
    expected=search_corpus(request,Path(job)/'corpus',index)
    need(search['payload']==expected['payload'],'SEARCH_LEDGER_MISMATCH','Search ledger omits or changes corpus/query coverage')
    p=mapping['payload'];r=request['payload']
    need(p['request_id']==request['artifact_id'] and p['request_hash']==payload_hash(request) and p['corpus_hash']==payload_hash(index),
         'STALE_QUESTION_MAP','Question map targets different inputs')
    pairs={(q['question_id'],pid) for q in r['questions'] for pid in r['paper_ids']}
    cells=p['records'];need(len(cells)==len(pairs) and {(c['question_id'],c['paper_id']) for c in cells}==pairs,
        'INCOMPLETE_QUESTION_COVERAGE','Every question and every paper require exactly one disposition')
    need(not mapping.get('template'),'UNREVIEWED_TEMPLATE','Replace the question map template with actual model dispositions')
    expected_parts=checked_parts_by_paper(job)
    from .sources.evidence import check_evidence
    for ev in evidence.values():check_evidence(Path(job)/'corpus',index,ev)
    paper_by_doc={d['document_id']:d['paper_id'] for d in index['payload']['documents']}
    for c in cells:
        need(c['reason'].strip()!='MODEL_REVIEW_REQUIRED','UNREVIEWED_TEMPLATE','Question disposition was not reviewed')
        need(set(c['checked_part_ids'])==expected_parts[c['paper_id']],'INCOMPLETE_QUESTION_COVERAGE','Question disposition must attest the complete paper, including zero keyword hits',c['paper_id'])
        refs=set(c['support_refs']+c['counter_refs'])
        need(refs<=set(evidence),'UNKNOWN_EVIDENCE','Question map references evidence not supplied',sorted(refs-set(evidence)))
        for eid in refs:
            need({paper_by_doc[s['document_id']] for s in evidence[eid]['payload']['spans']}=={c['paper_id']},
                'QUESTION_EVIDENCE_MISMATCH','Question disposition borrows evidence from another logical paper')
    return {'papers':len(r['paper_ids']),'questions':len(r['questions']),'dispositions':len(cells),
            'full_text_reading':'complete','lexical_search':'complete','semantic_dispositions':'model_attestation_not_human_guarantee'}


def check_context_binding(verification,artifacts):
    proof=verification['payload'].get('sharded_proof',{})
    plan=proof.get('plan',{}).get('payload',{})
    attached={(a.get('artifact_type'),a.get('artifact_id'),payload_hash(a)) for a in plan.get('context_artifacts',[])}
    for a in artifacts:
        need((a['artifact_type'],a['artifact_id'],payload_hash(a)) in attached,'UNREVIEWED_RESEARCH_CONTEXT',
             'Assembly audit must target these exact research request, search and disposition versions',a['artifact_type'])


def check_review_bundle(bundle,job,evidence,draft,verification):
    request=bundle['request'];need(request['payload']['mode']=='review','WRONG_REVIEW_MODE','Use augmentation delivery for report gap filling')
    result=check_research_coverage(request,bundle['search'],bundle['mapping'],job,evidence)
    check_context_binding(verification,[request,bundle['search'],bundle['mapping']])
    return result


def save_research_bundle(bundle,destination,source_index=None):
    root=Path(destination)
    for key,name in [('request','research_request.json'),('search','search_ledger.json'),('mapping','question_evidence_map.json')]:write_json(root/name,bundle[key])
    questions={q['question_id']:q['text'] for q in bundle['request']['payload']['questions']}
    lines=['# 逐問題文獻覆蓋','',
        '全庫關鍵字檢索與全文閱讀是不同層次；以下相關性判斷是模型聲明，不是人工學術保證。','',
        '| 問題 | 論文 | 判斷 | 理由 |','| --- | --- | --- | --- |']
    esc=lambda s:str(s).replace('|','\\|').replace('\n','<br>')
    titles={}
    for d in (source_index or {}).get('payload',{}).get('documents',[]):
        titles.setdefault(d['paper_id'],[]).append(d['metadata'].get('title') or d['source_path'])
    for c in bundle['mapping']['payload']['records']:
        name=' / '.join(titles.get(c['paper_id'],[c['paper_id']]))
        lines.append('| '+' | '.join(esc(v) for v in [questions[c['question_id']],name,c['status'],c['reason']])+' |')
    atomic_bytes(root/'research_coverage.md',('\n'.join(lines)+'\n').encode())


def research_invariants(artifact):
    p=artifact['payload'];kind=artifact['artifact_type']
    if kind=='ReviewRequest':
        need(len(set(p['paper_ids']))==len(p['paper_ids']),'CAPABILITY_INVALID','Duplicate paper IDs')
        need(len({q['question_id'] for q in p['questions']})==len(p['questions']),'CAPABILITY_INVALID','Duplicate question IDs')
        if p['mode']=='augment':need(p.get('augmentation_plan_ref'),'CAPABILITY_INVALID','Augment request needs an augmentation plan reference')
    elif kind=='QuestionEvidenceMap':
        for c in p['records']:
            if c['status']=='supporting':need(c['support_refs'],'CAPABILITY_INVALID','Supporting disposition needs evidence')
            if c['status']=='opposing':need(c['counter_refs'],'CAPABILITY_INVALID','Opposing disposition needs counterevidence')
            if c['status']=='mixed':need(c['support_refs'] and c['counter_refs'],'CAPABILITY_INVALID','Mixed disposition needs both sides')
            need(len(c['checked_part_ids'])==len(set(c['checked_part_ids'])),'CAPABILITY_INVALID','Duplicate checked parts')
