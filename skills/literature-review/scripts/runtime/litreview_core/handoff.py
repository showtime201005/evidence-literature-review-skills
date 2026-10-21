"""Human views and self-contained handoffs generated from one source of truth."""
import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
from .artifacts import atomic_bytes,canonical,digest,read_json,write_json
from .contracts import validate
from .errors import ReviewError

LABELS={'research_question':'研究問題','contributions':'貢獻','method':'方法','evaluation':'評估方式','results':'結果',
        'limitations':'限制','conditions':'適用條件','relevance':'研究問題關聯','unexpected_findings':'其他重要發現'}
STATES={'reported':'已擷取','not_extracted':'尚未擷取，不能據此判定原文未報告','not_reported':'閱讀者判定原文未報告（非獨立語意保證）',
        'not_applicable':'不適用','source_missing':'缺少來源','not_checked':'未檢查','parse_error':'解析失敗'}


def plain(value):
    return str(value).replace('|','\\|').replace('\r',' ').replace('\n','<br>')


def summary(artifact,materials=None,source_index=None):
    validate(artifact);p=artifact['payload'];kind=artifact['artifact_type']
    lines=['# '+kind,'',f"產物：{artifact['artifact_id']}",'',
        '本頁由結構化資料產生；格式通過、全文覆蓋與語意驗證是不同狀態。除非另有匹配的獨立驗證紀錄，不代表內容已通過查核。','']
    if kind=='PaperAnalysis':
        lines += ['論文：'+p['paper_id'],'','論文類型：'+p.get('paper_type','unknown'),'']
        for name,field in p['fields'].items():
            lines += ['## '+LABELS.get(name,name),'',STATES.get(field['status'],field['status']),'',field.get('text',''),'',
                      '判定說明：'+field.get('reason','舊版未提供理由'),'','主張：'+', '.join(field['claim_refs']),'']
        if 'publication_selection' in p:
            lines += ['## 報告選入範圍','',json.dumps(p['publication_selection'],ensure_ascii=False,indent=2),'']
    elif kind=='ComparisonSet':
        lines += ['比較問題：'+p['question'],'','| 論文／維度 | 待判斷命題 | 觀察結果 | 關係 | 可比性 |','| --- | --- | --- | --- | --- |']
        for c in p['cells']:
            lines += ['| '+' | '.join(plain(v) for v in [c['paper_id']+' / '+c['dimension'],c.get('proposition','舊版未指定'),
                c.get('value',c['conditions']),c['status'],c.get('comparability',{}).get('status','unknown')])+' |']
        for c in p['cells']:
            lines += ['', '## '+c.get('cell_id',c['paper_id']+'/'+c['dimension']),'',
                '理由：'+c.get('reason','舊版未提供'),'','條件：'+c['conditions'],'',
                '結構化條件：'+json.dumps(c.get('study_conditions',{}),ensure_ascii=False),'',
                '可比性說明：'+c.get('comparability',{}).get('reason','unknown'),'','主張：'+', '.join(c['material_refs']),
                '','反證：'+', '.join(c.get('counterevidence_refs',[])),'']
        lines += ['','## 未解問題','']+[str(x) for x in p['unknowns']]
        lines += ['','## 分歧候選','']+[json.dumps(x,ensure_ascii=False) for x in p['contradiction_candidates']]
    elif kind=='ReviewDraft':
        lines += ['## 綜述草稿（保留原始證據標記）','',p['text'],'']
    elif kind=='VerificationSet':
        lines += ['查核方式：'+p['verification_method'],'','完整掃描：'+str(p['scan_completed']),'']
        for v in p['verdicts']:
            lines += ['## '+v['claim_id'],'',v['status']+'：'+v['reason'],'','查核證據：'+', '.join(v['evidence_refs']),'']
        lines += ['## 問題','']+[json.dumps(x,ensure_ascii=False) for x in p['issues']]
    elif kind=='ComparisonVerification':
        lines += ['比較目標：'+p['target_artifact_id'],'',summary(p['review_verification'],materials,source_index)]
    elif kind=='TaskResult':
        lines += ['執行狀態：'+p['status'],'','品質狀態：'+p.get('quality','unverified'),'']
        for i in p['issues']:
            lines += ['## '+i.get('code','unknown'),'',i.get('message',''),'',
                '需要補充：'+', '.join(i.get('required_input',[])),'','負責者：'+i.get('owner','unknown'),
                '','可重試：'+str(i.get('retryable',False)),'']
    else:
        lines += ['```json',json.dumps(p,ensure_ascii=False,indent=2),'```','']
    records={a['artifact_id']:a for a in (materials or [])}
    claims={}
    for a in [artifact]+list(records.values()):
        if a['artifact_type']=='Claim':claims[a['payload']['claim_id']]=a['payload']
        for c in a['payload'].get('claims',[]):claims[c['claim_id']]=c
    if claims:
        lines += ['','## 主張對照','']
        for cid,c in claims.items():lines += [cid+'：'+c['text'],'','證據：'+', '.join(c['evidence_refs']),'']
    for a in records.values():
        if a['artifact_type']=='Evidence':
            lines += ['## 原文依據 '+a['payload']['evidence_id'],'']
            for span in a['payload']['spans']:
                docs=(source_index or {}).get('payload',{}).get('documents',[])
                doc=next((d for d in docs if d['document_id']==span['document_id']),{})
                name=doc.get('metadata',{}).get('title') or (Path(doc['source_path']).name if doc.get('source_path') else span['document_id'])
                blocks=(source_index or {}).get('payload',{}).get('blocks',[])
                section=next(('/'.join(b['section_path']) for b in blocks if b['document_id']==span['document_id'] and b['start_byte']<=span['start_byte']<b['end_byte']),'章節未知')
                lines += [f"來源：{name}；章節：{section}；UTF-8 bytes [{span['start_byte']}, {span['end_byte']})",'',
                    '```text',span['excerpt'],'```','']
    return '\n'.join(lines).rstrip()+'\n'


def write_handoff(artifact,out,materials=None,corpus=None):
    validate(artifact);materials=materials or []
    for item in materials:validate(item)
    destination=Path(out).resolve()
    if destination.exists():raise ReviewError('OUTPUT_CONFLICT','Use a new handoff directory',str(destination))
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.handoff-',dir=destination.parent));work=stage/'bundle';work.mkdir()
    try:
        write_json(work/'artifact.json',artifact)
        source_index=None
        if corpus:
            from .sources import load_corpus
            from .sources.evidence import check_evidence
            source_index=load_corpus(corpus)
            for item in [artifact]+materials:
                if item['artifact_type']=='Evidence':check_evidence(corpus,source_index,item)
        atomic_bytes(work/'summary.md',summary(artifact,materials,source_index).encode())
        if source_index and artifact['payload'].get('claims'):
            from .evidence_view import evidence_cards
            ev={a['payload']['evidence_id']:a for a in materials if a['artifact_type']=='Evidence'}
            required={eid for c in artifact['payload']['claims'] for eid in c['evidence_refs']}
            if required<=set(ev):
                atomic_bytes(work/'evidence_catalog.md',evidence_cards(artifact['payload']['claims'],ev,corpus,source_index,source_prefix='corpus').encode())
        entries=[];seen={artifact['artifact_id']:artifact}
        for item in materials:
            aid=item['artifact_id']
            if aid in seen:
                if item!=seen[aid]:raise ReviewError('DUPLICATE_ID','Conflicting handoff artifacts',aid)
                continue
            seen[aid]=item
            relative='materials/'+digest(aid.encode())+'.json'
            write_json(work/relative,item)
            entries.append({'artifact_id':aid,'artifact_type':item['artifact_type'],'path':relative})
        if corpus:
            from .sources import load_corpus
            from .artifacts import safe_path
            index=load_corpus(corpus)
            # Export only validated corpus members, never unrelated adjacent files.
            members=['corpus.json','coverage.json','references.json']+[d['snapshot_path'] for d in index['payload']['documents']]
            for relative in members:atomic_bytes(work/'corpus'/relative,safe_path(corpus,relative).read_bytes())
        # Make missing references explicit instead of claiming a portable bundle is complete.
        provided={a['artifact_id'] for a in seen.values()}
        for a in seen.values():
            if a['artifact_type']=='Claim':provided.add(a['payload']['claim_id'])
            if a['artifact_type']=='Evidence':provided.add(a['payload']['evidence_id'])
            provided.update(c['claim_id'] for c in a['payload'].get('claims',[]))
        required=set()
        for a in seen.values():
            p=a['payload'];required.update(p.get('claim_refs',[]))
            if p.get('assessment_ref'):required.add(p['assessment_ref'])
            required.update(p.get('coverage_refs',[]))
            if a['artifact_type']=='CoverageRecord':provided.add(p['coverage_id'])
            if a['artifact_type']=='CoverageSet':provided.update(r['coverage_id'] for r in p['records'])
            for c in p.get('claims',[]):required.update(c['evidence_refs'])
            if a['artifact_type']=='Claim':required.update(p['evidence_refs'])
            if a['artifact_type']=='VerificationSet':
                required.add(p['target_artifact_id'])
                required.update(p.get('evidence_hashes',{}))
                for verdict in p['verdicts']:required.update(verdict['evidence_refs'])
            if a['artifact_type']=='FieldAssessmentSet':required.add(p['target_artifact_id'])
        unresolved=sorted(required-provided)
        source_ids=sorted({s['document_id'] for a in seen.values() if a['artifact_type']=='Evidence' for s in a['payload']['spans']})
        hashes={str(p.relative_to(work)):digest(p.read_bytes()) for p in sorted(work.rglob('*')) if p.is_file()}
        manifest={'handoff_format':'0.4.0','artifact_id':artifact['artifact_id'],'payload_hash':digest(canonical(artifact['payload']).encode()),
            'schema_version':artifact['schema_version'],'primary':'artifact.json','human_view':'summary.md','materials':entries,
            'files':hashes,'unresolved_refs':unresolved,'source_snapshot_included':bool(corpus),
            'missing_source_document_ids':source_ids if not corpus else [],
            'readiness':'needs_materials' if unresolved else ('needs_sources' if source_ids and not corpus else 'structurally_packaged'),
            'quality':'unverified','edit_policy':'Do not edit generated projections. Import a human edit as a new report and independently reverify it.'}
        write_json(work/'manifest.json',manifest)
        os.rename(work,destination)
        return {'path':str(destination),'manifest':manifest,'quality':'unverified'}
    finally:shutil.rmtree(stage,ignore_errors=True)


def check_handoff(path):
    root=Path(path).resolve();manifest=read_json(root/'manifest.json');bad=[]
    for name,expected in manifest['files'].items():
        from .artifacts import safe_path
        target=safe_path(root,name)
        if not target.is_file() or digest(target.read_bytes())!=expected:bad.append(name)
    if bad:raise ReviewError('PROJECTION_CHANGED','Generated JSON/Markdown/materials changed; create a new revision',bad)
    return {'status':'passed','files_checked':len(manifest['files']),'quality':'unverified',
            'unresolved_refs':manifest['unresolved_refs']}
