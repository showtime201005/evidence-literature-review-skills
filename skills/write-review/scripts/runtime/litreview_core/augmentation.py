"""Evidence-backed report supplements; preserve unverified original content."""
import copy
from pathlib import Path
import re
import shutil
import tempfile
import os
from .artifacts import atomic_bytes,canonical,digest,envelope,identifier,read_json,write_json
from .contracts import validate
from .review import draft_from_sections,gate
from .sources import load_corpus
from .sources.evidence import check_evidence
from .workflow import need,payload_hash
from .research import request_from_spec,check_research_coverage,check_context_binding,save_research_bundle

CONDITIONS=('dataset','population','metric','unit','baseline','timepoint','sample_size','version')


def make_plan(report_text,specs,context_id='unknown'):
    need(isinstance(specs,list) and specs and all(isinstance(s,dict) for s in specs),'SCHEMA_INVALID','Gap specifications must be a nonempty array of objects')
    gaps=[]
    for spec in specs:
        need({'anchor','gap_id','question','terms'}<=set(spec),'SCHEMA_INVALID','Each gap needs anchor, gap_id, question and terms')
        anchor=spec['anchor'];starts=[];cursor=0
        need(isinstance(anchor,str) and bool(anchor),'INVALID_REPORT_ANCHOR','Gap anchor must be nonempty exact text')
        while (found:=report_text.find(anchor,cursor))!=-1:
            starts.append(found);cursor=found+1
        if 'start_char' in spec:
            start=spec['start_char'];need(type(start) is int,'SCHEMA_INVALID','start_char must be an integer')
        else:
            need(len(starts)==1,'AMBIGUOUS_REPORT_ANCHOR','Anchor missing or repeated; supply an exact start_char',anchor)
            start=starts[0]
        req={k:'' for k in CONDITIONS};req.update(spec.get('requirements',{}))
        gaps.append(dict(gap_id=spec['gap_id'],start_char=start,end_char=start+len(anchor),anchor=anchor,
            operation=spec.get('operation','replace'),question=spec['question'],terms=spec['terms'],requirements=req,
            expects_numeric=spec.get('expects_numeric',bool(req['metric'] or req['unit']))))
    plan=envelope('AugmentationPlan',dict(report_text=report_text,report_hash=digest(report_text.encode('utf-8')),gaps=gaps),
        producer={'context_id':context_id},schema_version='2.0.0');validate(plan);return plan


def augment_request(plan,index):
    validate(plan)
    return request_from_spec(dict(mode='augment',augmentation_plan_ref=plan['artifact_id'],augmentation_plan_hash=payload_hash(plan),
        questions=[dict(question_id=g['gap_id'],text=g['question'],terms=g['terms']) for g in plan['payload']['gaps']]),index)


def check_resolutions(plan,resolutions,evidence,index):
    validate(plan);validate(resolutions)
    need(plan['artifact_type']=='AugmentationPlan' and resolutions['artifact_type']=='GapResolutionSet','WRONG_ARTIFACT_TYPE','Expected augmentation plan and gap resolutions')
    p=resolutions['payload'];need(p['plan_id']==plan['artifact_id'] and p['plan_hash']==payload_hash(plan),'STALE_AUGMENTATION_PLAN','Resolution targets another report/gap version')
    need(p['corpus_hash']==payload_hash(index),'SOURCE_VERSION_MISMATCH','Resolution targets another corpus')
    gaps={g['gap_id']:g for g in plan['payload']['gaps']};rows={g['gap_id']:g for g in p['resolutions']}
    need(len(rows)==len(p['resolutions']) and set(rows)==set(gaps),'INCOMPLETE_GAP_COVERAGE','Every report gap needs exactly one resolution')
    claims={c['claim_id']:c for c in p['claims']};need(len(claims)==len(p['claims']),'DUPLICATE_ID','Duplicate supplement claim ID')
    used=set()
    for c in claims.values():
        need(c['claim_type']!='scope_statement' and c['evidence_refs'],'MISSING_CITATION','Supplement findings require primary source evidence')
        need(set(c['evidence_refs'])<=set(evidence),'UNKNOWN_EVIDENCE','Unknown supplement evidence')
    for gid,row in rows.items():
        need(set(row['claim_refs'])<=set(claims),'UNKNOWN_CLAIM','Gap refers to unknown supplement claims',gid);used.update(row['claim_refs'])
        if row['status'] in ('filled','partially_filled'):need(row['claim_refs'],'MISSING_CITATION','Filled/partial gaps need source-linked claims',gid)
        if row['status']=='filled' and gaps[gid]['expects_numeric']:need(row['data_points'],'MISSING_NUMERIC_DATA','A numeric gap needs explicit reported data points',gid)
        refs={e for cid in row['claim_refs'] for e in claims[cid]['evidence_refs']}
        for point in row['data_points']:
            need(set(point['evidence_refs'])<=refs,'UNKNOWN_EVIDENCE','A data point must use the gap claims evidence',gid)
            value=point['value_text']
            need(re.fullmatch(r'[+-]?(?:\d+(?:[.,]\d+)*|\.\d+)(?:[eE][+-]?\d+)?[%％]?',value),
                 'UNREPORTED_NUMBER','Data points accept reported numeric strings, not invented values/formulas',value)
            for eid in point['evidence_refs']:
                excerpt=evidence[eid]['payload']['excerpt']
                need(re.search(r'(?<![\d.])'+re.escape(value)+r'(?![\d.])',excerpt),'UNREPORTED_NUMBER','Reported value is absent from the exact source quote',value)
            if row['status']=='filled':
                for key,required in gaps[gid]['requirements'].items():
                    if required:
                        need(point['conditions'][key].casefold()==required.casefold(),'GAP_CONDITION_MISMATCH',
                             'Do not fill a gap using another dataset, population, metric or unit',{'gap_id':gid,'condition':key,'required':required,'actual':point['conditions'][key]})
    need(used==set(claims),'UNMAPPED_CLAIM','Every supplement claim must belong to a declared gap')
    return rows,claims


def patch_text(gap,row,claims):
    if row['status']!='filled':return gap['anchor']
    text='；'.join(claims[cid]['text'] for cid in row['claim_refs'])+'〔補證:'+gap['gap_id']+'〕'
    return gap['anchor']+'\n'+text if gap['operation']=='insert_after' else text


def augmentation_draft(plan,resolutions,evidence,index):
    rows,claims=check_resolutions(plan,resolutions,evidence,index);sections=[{'heading':'Supplement source claims','claims':copy.deepcopy(list(claims.values()))}]
    for gap in plan['payload']['gaps']:
        row=rows[gap['gap_id']];refs=sorted({e for cid in row['claim_refs'] for e in claims[cid]['evidence_refs']})
        meta={'gap':gap,'original_context_unverified':plan['payload']['report_text'][max(0,gap['start_char']-160):gap['end_char']+160],
            'resolution':row,'proposed_patch':patch_text(gap,row,claims),
            'scope':'Original report context is quoted as an unverified target, not endorsed as a scientific result. Unfilled gaps remain unchanged.'}
        sections.append({'heading':'Gap '+gap['gap_id'],'claims':[dict(claim_id=identifier('gap_assessment',meta),text=canonical(meta),
            claim_type='synthesis' if refs else 'scope_statement',evidence_refs=refs,support_status='unverified')]})
    context=resolutions.get('producer',{}).get('context_id');need(context,'PROVENANCE_REQUIRED','Supplement writer needs an actual context ID')
    return draft_from_sections(sections,context)


def build_patch(plan,resolutions):
    p=plan['payload'];rows={r['gap_id']:r for r in resolutions['payload']['resolutions']};claims={c['claim_id']:c for c in resolutions['payload']['claims']}
    chunks=[];edits=[];cursor=0;length=0
    for gap in sorted(p['gaps'],key=lambda g:g['start_char']):
        row=rows[gap['gap_id']]
        if row['status']!='filled':continue
        prefix=p['report_text'][cursor:gap['start_char']];chunks.append(prefix);length+=len(prefix)
        replacement=patch_text(gap,row,claims);start=length;chunks.append(replacement);length+=len(replacement)
        edits.append(dict(gap_id=gap['gap_id'],operation=gap['operation'],original_start_char=gap['start_char'],original_end_char=gap['end_char'],
            original_text=gap['anchor'],replacement=replacement,patched_start_char=start,patched_end_char=length))
        cursor=gap['end_char']
    chunks.append(p['report_text'][cursor:]);return ''.join(chunks),edits


def supplement_markdown(plan,resolutions,evidence,index):
    rows={r['gap_id']:r for r in resolutions['payload']['resolutions']};claims={c['claim_id']:c for c in resolutions['payload']['claims']}
    docs={d['document_id']:d for d in index['payload']['documents']};numbers={};lines=['# 文獻補證說明','',
        '> 本補證的新增主張及缺口處置已依提供文本獨立查核；原報告既有文字未因此獲得整份驗證。','']
    def citations(refs):
        out=[]
        for eid in refs:
            for span in evidence[eid]['payload']['spans']:
                did=span['document_id']
                if did not in numbers:numbers[did]=len(numbers)+1
                token='補'+str(numbers[did])
                if token not in out:out.append(token)
        return '['+', '.join(out)+']' if out else ''
    for gap in plan['payload']['gaps']:
        row=rows[gap['gap_id']];lines+=['## 補證 '+gap['gap_id']+'：'+gap['question'],'','狀態：'+row['status'],'',row['reason'],'']
        for cid in row['claim_refs']:
            c=claims[cid];lines+=[c['text']+' '+citations(c['evidence_refs']),'']
        for point in row['data_points']:lines+=['條件：'+canonical(point['conditions'])+'；原文數值：'+point['value_text'],'']
    lines+=['## 補充來源','']
    for did,n in numbers.items():
        d=docs[did];m=d['metadata'];lines+=[f"[補{n}] {m.get('authors','作者未提供')}；{m.get('year','年份未提供')}；{m.get('title',Path(d['source_path']).name)}。版本 SHA-256：{d['content_hash']}。書目未經外部查證。",'']
    lines+=['## 原文與定位','']
    for eid,ev in evidence.items():
        lines+=['### '+eid,'']
        for span in ev['payload']['spans']:
            name=docs[span['document_id']]['metadata'].get('title') or Path(docs[span['document_id']]['source_path']).name
            fence='`'*max(3,max((len(m[0])+1 for m in re.finditer(r'`+',span['excerpt'])),default=3))
            lines += [f"{name}；UTF-8 bytes [{span['start_byte']}, {span['end_byte']})",'',fence+'text',span['excerpt'],fence,'']
    return '\n'.join(lines).rstrip()+'\n'


def deliver_augmentation(report_text,plan,resolutions,request,search,mapping,job,evidence,verification,out):
    validate(plan);need(digest(report_text.encode('utf-8'))==plan['payload']['report_hash'],'STALE_REPORT','Original report changed after gap planning')
    index=load_corpus(Path(job)/'corpus');draft=augmentation_draft(plan,resolutions,evidence,index)
    need(request['payload']['mode']=='augment' and request['payload'].get('augmentation_plan_ref')==plan['artifact_id'] and request['payload'].get('augmentation_plan_hash')==payload_hash(plan),
        'STALE_AUGMENTATION_PLAN','Research request targets another gap plan')
    expected={g['gap_id']:(g['question'],g['terms']) for g in plan['payload']['gaps']}
    need({q['question_id']:(q['text'],q['terms']) for q in request['payload']['questions']}==expected,'QUESTION_SCOPE_MISMATCH','Research request questions differ from report gaps')
    coverage=check_research_coverage(request,search,mapping,job,evidence)
    check_context_binding(verification,[plan,resolutions,request,search,mapping])
    gate(draft,evidence,Path(job)/'corpus',index,verification)
    for ev in evidence.values():check_evidence(Path(job)/'corpus',index,ev)
    body,edits=build_patch(plan,resolutions);supplement=supplement_markdown(plan,resolutions,evidence,index)
    disclaimer='> 本文件保留原報告內容並加入文獻補證。只有新增補證及其處置經查核；原報告既有內容未全面重新驗證。未補足欄位仍保留。\n\n'
    augmented=disclaimer+body+'\n\n'+supplement
    dest=Path(out).resolve();need(not dest.exists(),'OUTPUT_CONFLICT','Use a new augmentation delivery directory');dest.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.augmentation-',dir=dest.parent));work=stage/'bundle';work.mkdir()
    try:
        atomic_bytes(work/'original_report.md',report_text.encode('utf-8'));atomic_bytes(work/'augmented_report.md',augmented.encode('utf-8'))
        atomic_bytes(work/'supplement.md',supplement.encode('utf-8'))
        from .evidence_view import evidence_cards
        atomic_bytes(work/'evidence_catalog.md',evidence_cards(resolutions['payload']['claims'],evidence,Path(job)/'corpus',index,True).encode())
        for name,a in [('augmentation_plan.json',plan),('gap_resolutions.json',resolutions),('supplement_draft.json',draft),('verification.json',verification)]:write_json(work/name,a)
        save_research_bundle({'request':request,'search':search,'mapping':mapping},work,index)
        from .workflow import assemble,export_reading_checkpoint
        assemble(job,work/'analysis')
        export_reading_checkpoint(job,work/'reading_checkpoint')
        from .artifacts import safe_path
        for relative in ['corpus.json','coverage.json','references.json']+[d['snapshot_path'] for d in index['payload']['documents']]:
            atomic_bytes(work/'sources'/relative,safe_path(Path(job)/'corpus',relative).read_bytes())
        atomic_bytes(work/'evidence.jsonl',(''.join(canonical(ev)+'\n' for ev in evidence.values())).encode())
        manifest={'original_hash':plan['payload']['report_hash'],'patched_body_hash':digest(body.encode()),'augmented_file_hash':digest(augmented.encode()),
            'projection_hash':payload_hash(draft),'original_report_quality':'not_audited','supplement_quality':'passed',
            'offset_unit':'Unicode code points; patched offsets refer to body before generated disclaimer/appendix',
            'edits':edits,'unresolved_gaps':[r for r in resolutions['payload']['resolutions'] if r['status']!='filled'],'coverage':coverage}
        write_json(work/'patch_manifest.json',manifest)
        atomic_bytes(work/'delivery-summary.md',('# 報告補證交付\n\n新增補證：通過獨立查核。原報告：未全面查核。\n\n'
            f"已補：{len(edits)}；保留未解／部分／衝突：{len(manifest['unresolved_gaps'])}。\n\n原報告保存在 original_report.md；修改範圍見 patch_manifest.json。\n").encode())
        need(not dest.exists(),'OUTPUT_CONFLICT','Output appeared during augmentation delivery');os.rename(work,dest)
        return {'path':str(dest),'supplement_quality':'passed','original_report_quality':'not_audited','filled_gaps':len(edits),'unresolved_gaps':len(manifest['unresolved_gaps'])}
    finally:shutil.rmtree(stage,ignore_errors=True)


def augmentation_invariants(artifact):
    p=artifact['payload']
    if artifact['artifact_type']=='AugmentationPlan':
        need(digest(p['report_text'].encode('utf-8'))==p['report_hash'],'STALE_REPORT','Gap plan report hash differs')
        need(len({g['gap_id'] for g in p['gaps']})==len(p['gaps']),'DUPLICATE_ID','Duplicate gap IDs')
        end=0
        for g in sorted(p['gaps'],key=lambda x:x['start_char']):
            need(end<=g['start_char']<g['end_char']<=len(p['report_text']) and p['report_text'][g['start_char']:g['end_char']]==g['anchor'],
                'INVALID_REPORT_ANCHOR','Report gap anchors overlap or differ from exact target text')
            end=g['end_char']
