"""Independent semantic verification packets and fail-closed publication gates."""
import csv
import io
from pathlib import Path
import re
from .artifacts import canonical, digest, envelope, identifier, read_json, atomic_bytes, write_json
from .contracts import validate
from .errors import ReviewError
from .sources.evidence import check_evidence
from .verification import inspect_draft
from .workflow import need,payload_hash,FIELDS,status,job_plan


def read_jsonl(path):
    return [__import__('json').loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def draft_from_sections(sections,context_id,scope='corpus_only'):
    """Build exact claim mappings from structured prose; never infer mappings."""
    need(bool(context_id),'PROVENANCE_REQUIRED','Writer context ID is required')
    lines=[];claims=[];mappings=[];offset=0;paper_sections={}
    for section in sections:
        heading=section.get('heading','')
        if heading:
            heading='## '+heading+'\n\n';lines.append(heading);offset+=len(heading)
        begin=offset
        for item in section.get('claims',[]):
            validate({'schema_version':'1.0.0','artifact_type':'Claim','artifact_id':'external','payload':item})
            need(item['claim_id'] not in {c['claim_id'] for c in claims},'DUPLICATE_ID','Claim ID appears more than once; use new claim IDs for reformulations')
            text=item['text'];refs=item['evidence_refs']
            mappings.append(dict(claim_id=item['claim_id'],start_char=offset,end_char=offset+len(text)))
            suffix=(' '+ ' '.join('{{evidence:'+eid+'}}' for eid in refs)) if refs else ''
            line=text+suffix+'\n\n';lines.append(line);offset+=len(line);claims.append(item)
        if section.get('paper_id'):
            need(section['paper_id'] not in paper_sections,'DUPLICATE_ID','Only one appendix section per paper')
            paper_sections[section['paper_id']]={'start_char':begin,'end_char':offset}
    draft=envelope('ReviewDraft',dict(text=''.join(lines),claims=claims,claim_mappings=mappings,citation_map={},scan_status='not_checked',
        paper_sections=paper_sections,scope=scope),producer={'context_id':context_id,'role':'writer'})
    validate(draft)
    return draft


def lines_to_scan(text):
    records=[];cursor=0
    for line in text.splitlines(keepends=True):
        if line.strip():
            records.append(dict(start_char=cursor,end_char=cursor+len(line),text=line))
        cursor+=len(line)
    return records


def verification_packet(draft,evidence,corpus_dir,index,max_chars=100000):
    validate(draft)
    need(draft['artifact_type']=='ReviewDraft','WRONG_ARTIFACT_TYPE','Expected ReviewDraft')
    from .sources import source_bytes
    source_context={}
    for eid,ev in evidence.items():
        check_evidence(corpus_dir,index,ev)
        for span in ev['payload']['spans']:
            blocks=[b for b in index['payload']['blocks'] if b['document_id']==span['document_id']]
            for n,block in enumerate(blocks):
                if span['start_byte']<block['end_byte'] and span['end_byte']>block['start_byte']:
                    for neighbor in blocks[max(0,n-1):n+2]:
                        if neighbor['block_id'] not in source_context:
                            doc=next(d for d in index['payload']['documents'] if d['document_id']==span['document_id'])
                            raw=source_bytes(corpus_dir,doc)
                            source_context[neighbor['block_id']]={key:neighbor[key] for key in ('block_id','document_id','kind','section_path','start_byte','end_byte')}
                            source_context[neighbor['block_id']]['text']=raw[neighbor['start_byte']:neighbor['end_byte']].decode()
    packet={'target_artifact_id':draft['artifact_id'],'target_hash':payload_hash(draft),'draft':draft,
        'evidence':list(evidence.values()),'evidence_hashes':{eid:payload_hash(ev) for eid,ev in evidence.items()},
        'source_context':list(source_context.values()),'lines_to_scan':lines_to_scan(draft['payload']['text']),
        'mechanical_findings':inspect_draft(draft,set(evidence)),
        'rules':'Independently read every draft line and source context. Judge support, negation, numeric attribution, scope, secondary-source status and synthesis counterevidence. Inspect undeclared facts, including headings. Do not use writer rationales. Return VerificationSet with verdicts for every claim; scan_findings one classification per nonempty line; classifications factual / non_factual. A factual line requires mapped claim_ids. Mark unsupported/contradicted/uncertain if context is insufficient. Include evidence_hashes, producer.context_id and target_hash exactly.'}
    packet['source_inventory']=[{k:doc[k] for k in ('document_id','paper_id','metadata','content_hash','source_gaps','snapshot_path')} for doc in index['payload']['documents']]
    packet['corpus_location']=str(Path(corpus_dir).resolve())
    need(len(canonical(packet))<=max_chars,'VERIFICATION_PACKET_TOO_LARGE',
        'Split the draft into independently verified sections, then verify the assembled report; do not truncate context',{'characters':len(canonical(packet)),'budget':max_chars})
    return packet


def gate(draft,evidence,corpus_dir,index,verification=None,require_full_job=None,comparison=None,comparison_verification=None):
    issues=inspect_draft(draft,set(evidence))
    blockers=[i for i in issues if i['severity']=='blocker']
    for ev in evidence.values():
        check_evidence(corpus_dir,index,ev)
    need(not blockers,'STRUCTURAL_GATE_FAILED','Draft has structural blockers',blockers)
    need(verification is not None,'SEMANTIC_GATE_UNAVAILABLE','An independent VerificationSet is required')
    validate(verification)
    need(verification['artifact_type']=='VerificationSet','WRONG_ARTIFACT_TYPE','Expected VerificationSet')
    v=verification['payload'];d=draft['payload']
    if v['verification_method']=='independent_model_sharded_review':
        from .sharding import validate_sharded_proof
        validate_sharded_proof(draft,evidence,corpus_dir,index,verification)
    need(v['target_artifact_id']==draft['artifact_id'] and v['target_hash']==payload_hash(draft),
        'STALE_VERIFICATION','Verification targets another report version')
    writer=draft.get('producer',{}).get('context_id');verifier=verification.get('producer',{}).get('context_id')
    need(writer and verifier and writer!=verifier,'INDEPENDENT_CONTEXT_REQUIRED','Writer and verifier must declare different context IDs; provenance is an attestation, not authentication')
    declared=v.get('evidence_hashes',{});available={eid:payload_hash(ev) for eid,ev in evidence.items()}
    used={eid for claim in d['claims'] for eid in claim['evidence_refs']}
    need(isinstance(declared,dict) and used<=set(declared)<=set(available) and all(available[eid]==h for eid,h in declared.items()),
        'STALE_EVIDENCE','Verification evidence fingerprints differ or omit a cited source; additional caller materials do not expand verification scope')
    need(v['scan_completed'],'INCOMPLETE_SCAN','Independent whole-report claim scan is required')
    need(not v['issues'],'VERIFICATION_ISSUES','Resolve verifier issues before publication',v['issues'])
    verdicts={item['claim_id']:item for item in v['verdicts']}
    claims={c['claim_id']:c for c in d['claims']}
    need(len(verdicts)==len(v['verdicts']) and set(verdicts)==set(claims),'INCOMPLETE_VERIFICATION','Every delivered claim needs exactly one independent verdict')
    for cid,claim in claims.items():
        verdict=verdicts[cid]
        need(verdict['status']=='supported','UNSUPPORTED_CLAIM','Only fully supported claims may be published',{'claim_id':cid,'status':verdict['status']})
        need(set(verdict['evidence_refs'])==set(claim['evidence_refs']),'VERDICT_EVIDENCE_MISMATCH','Verifier evidence set differs from claim evidence',cid)
    expected=lines_to_scan(d['text'])
    findings=v['scan_findings']
    pairs={(x.get('start_char'),x.get('end_char')):x for x in findings}
    need(len(pairs)==len(findings) and set(pairs)=={(x['start_char'],x['end_char']) for x in expected},
        'INCOMPLETE_SCAN','Every nonempty report line, including headings, needs exactly one scan finding')
    for line in expected:
        item=pairs[(line['start_char'],line['end_char'])]
        need(item.get('classification') in ('factual','non_factual') and item.get('reason'),
             'INVALID_SCAN_FINDING','Each line requires classification and a reason')
        if item['classification']=='factual':
            cids=item.get('claim_ids',[])
            need(cids and set(cids)<=set(claims),'UNDECLARED_FACT','Factual line must identify its declared claims',line)
            mapped=[m for m in d['claim_mappings'] if m['claim_id'] in cids and m['start_char']<line['end_char'] and m['end_char']>line['start_char']]
            need(set(m['claim_id'] for m in mapped)==set(cids),'INVALID_SCAN_FINDING','Factual line cites claims mapped elsewhere')
    if require_full_job:
        progress=status(require_full_job)
        need(progress['execution']=='complete','INCOMPLETE_COVERAGE','Full-corpus analysis must finish',progress)
        papers={doc['paper_id'] for doc in index['payload']['documents']}
        sections=d.get('paper_sections',{})
        need(set(sections)==papers,'MISSING_PAPER_APPENDIX','Every paper requires an appendix section')
        for pid,section in sections.items():
            need(0<=section['start_char']<section['end_char']<=len(d['text']),'INVALID_PAPER_APPENDIX','Appendix is empty or outside report',pid)
            # Every appendix needs a mapped statement, including explicit corpus gaps.
            need(any(section['start_char']<=m['start_char']<m['end_char']<=section['end_char'] for m in d['claim_mappings']),
                 'INVALID_PAPER_APPENDIX','Each appendix must contain a verified mapped statement',pid)
        need(comparison is not None,'MISSING_MATRIX','Full-corpus publication requires a ComparisonSet')
        validate(comparison);matrix=comparison['payload']
        need(comparison['artifact_type']=='ComparisonSet','WRONG_ARTIFACT_TYPE','Expected ComparisonSet')
        expected_cells={(pid,dim) for pid in papers for dim in matrix['dimensions']}
        cells=matrix['cells']
        need(len(cells)==len(expected_cells) and {(c['paper_id'],c['dimension']) for c in cells}==expected_cells,
             'MISSING_MATRIX_CELL','Every paper and dimension requires exactly one matrix cell')
        if comparison['schema_version']=='2.0.0':
            need(set(matrix['paper_ids'])==papers,'MISSING_MATRIX_CELL','Comparison paper IDs differ from the corpus')
            from .comparison import comparison_gate
            comparison_gate(comparison,evidence,corpus_dir,index,comparison_verification)
        else:
            # Legacy compatibility: v1 matrices remain tied to report claims.
            for cell in cells:
                need(cell['verification_status']=='verified','UNVERIFIED_MATRIX','All delivered matrix cells need verification')
                need(cell['material_refs'] and set(cell['material_refs'])<=set(claims),
                    'UNVERIFIED_MATRIX','Matrix cells must reference claims included in this verified report')
                need(cell['conditions']=='\n'.join(claims[cid]['text'] for cid in cell['material_refs']),
                    'UNVERIFIED_MATRIX','Matrix prose must exactly mirror its verified claims; new comparisons need their own report claim')
    return {'quality':'passed','verification_method':v['verification_method'],'manual_review':'not_performed',
        'scope':'provided_text_only','semantic_support':'independent_model_attestation','claim_count':len(claims)}


def _deliver_staged(root,draft,evidence,verification,comparison,out,comparison_verification=None,field_assessments=None,research_bundle=None):
    from .rendering import render
    plan,index=job_plan(root)
    result=gate(draft,evidence,Path(root)/'corpus',index,verification,root,comparison,comparison_verification)
    if research_bundle:
        from .research import check_review_bundle
        result['research_coverage']=check_review_bundle(research_bundle,root,evidence,draft,verification)
    destination=Path(out)
    need(not destination.exists(),'OUTPUT_CONFLICT','Delivery directory already exists')
    text,ledger=render(draft,evidence,Path(root)/'corpus',index,True,verification)
    destination.mkdir(parents=True)
    atomic_bytes(destination/'review.md',text.encode())
    from .evidence_view import evidence_cards
    atomic_bytes(destination/'evidence_catalog.md',evidence_cards(draft['payload']['claims'],evidence,Path(root)/'corpus',index,True).encode())
    write_json(destination/'review.json',draft);write_json(destination/'verification.json',verification)
    write_json(destination/'comparison.json',comparison)
    if comparison_verification is not None:
        write_json(destination/'comparison_verification.json',comparison_verification)
    atomic_bytes(destination/'citation_ledger.jsonl',(''.join(canonical(c)+'\n' for c in ledger['ledger'])).encode())
    matrix=io.StringIO();columns=['paper_id','dimension','status','material_refs','verification_status','conditions']
    if comparison['schema_version']=='2.0.0':columns+=['cell_id','proposition','value','study_conditions','comparability','counterevidence_refs','reason']
    writer=csv.DictWriter(matrix,fieldnames=columns);writer.writeheader()
    for cell in comparison['payload']['cells']:
        row={key:(canonical(cell[key]) if isinstance(cell[key],(list,dict)) else cell[key]) for key in writer.fieldnames}
        if comparison['schema_version']=='2.0.0':row['verification_status']='verified'
        writer.writerow(row)
    atomic_bytes(destination/'evidence_matrix.csv',matrix.getvalue().encode())
    for paper,section in draft['payload']['paper_sections'].items():
        # Use hashed filenames for user-controlled logical IDs.
        filename=identifier('paper',paper)+'.md'
        appendix=draft['payload']['text'][section['start_char']:section['end_char']]
        appendix=re.sub(r'\{\{evidence:([^{}]+)\}\}',lambda m:'['+', '.join(str(ref['number']) for ref in ledger['references'] if ref['document_id'] in {s['document_id'] for s in evidence[m[1]]['payload']['spans']})+']',appendix)
        atomic_bytes(destination/'paper_reviews'/filename,('<!-- paper_id: '+paper.replace('--','')+' -->\n'+appendix).encode())
    write_json(destination/'run_manifest.json',dict(plan,result=result,progress=status(root)))
    from .workflow import assemble
    assemble(root,destination/'analysis')
    coverage=read_json(destination/'analysis/coverage.json')
    coverage['payload']['quality']='passed'
    write_json(destination/'coverage.json',coverage)
    raw_analyses={a['payload']['paper_id']:a for a in read_jsonl(destination/'analysis/paper_analyses.jsonl')}
    from .capabilities import apply_assessments
    for assessment in field_assessments or []:
        validate(assessment)
        need(assessment['artifact_type']=='FieldAssessmentSet','WRONG_ARTIFACT_TYPE','Expected FieldAssessmentSet')
        matches=[pid for pid,a in raw_analyses.items() if a['artifact_id']==assessment['payload']['target_artifact_id']]
        need(len(matches)==1,'STALE_ASSESSMENT','Field assessment does not target the current assembled paper version')
        pid=matches[0];raw_analyses[pid]=apply_assessments(raw_analyses[pid],assessment)
        write_json(destination/'analysis/field_assessments'/(identifier('assessment',assessment['artifact_id'])+'.json'),assessment)
    final_analyses=[]
    for pid,section in draft['payload']['paper_sections'].items():
        ids={m['claim_id'] for m in draft['payload']['claim_mappings'] if section['start_char']<=m['start_char']<m['end_char']<=section['end_char']}
        selected=[c for c in draft['payload']['claims'] if c['claim_id'] in ids]
        import copy
        analysis=copy.deepcopy(raw_analyses[pid]['payload'])
        selected_ids=[c['claim_id'] for c in selected]
        analysis['publication_selection']={'selected_claim_refs':selected_ids,
            'raw_claim_dispositions':[{'claim_id':cid,
                'status':'selected_exact' if cid in selected_ids else ('derived_in_report' if any(cid in c.get('derived_from_claim_refs',[]) for c in selected) else 'not_mapped_to_report'),
                'report_claim_refs':[c['claim_id'] for c in selected if c['claim_id']==cid or cid in c.get('derived_from_claim_refs',[])]} for cid in analysis['claim_refs']],
            'verification_artifact_id':verification['artifact_id'],
            'verification_scope':'Only selected appendix claims; the complete raw extraction is not independently approved.'}
        final_analyses.append(envelope('PaperAnalysis',analysis,schema_version='2.0.0'))
    atomic_bytes(destination/'paper_analyses.jsonl',(''.join(canonical(a)+'\n' for a in final_analyses)).encode())
    from .handoff import summary
    extraction_materials=[envelope('Claim',c) for c in read_jsonl(destination/'analysis/claims.jsonl')]+read_jsonl(destination/'analysis/evidence.jsonl')
    for analysis in final_analyses:
        cids=set(analysis['payload']['claim_refs'])
        eids={e for a in extraction_materials if a['artifact_type']=='Claim' and a['payload']['claim_id'] in cids for e in a['payload']['evidence_refs']}
        local=[a for a in extraction_materials if (a['artifact_type']=='Claim' and a['payload']['claim_id'] in cids) or
               (a['artifact_type']=='Evidence' and a['payload']['evidence_id'] in eids)]
        atomic_bytes(destination/'paper_analysis_readings'/(identifier('paper',analysis['payload']['paper_id'])+'.md'),summary(analysis,local,index).encode())
    write_json(destination/'references.json',read_json(Path(root)/'corpus/references.json'))
    from .handoff import summary
    atomic_bytes(destination/'comparison-summary.md',summary(comparison,list(evidence.values()),index).encode())
    atomic_bytes(destination/'verification-summary.md',summary(verification).encode())
    atomic_bytes(destination/'delivery-summary.md',(
        '# 交付摘要\n\n範圍：僅提供文本。\n\n全文閱讀執行：complete。\n\n報告品質：passed（獨立模型聲明，非人工保證）。\n\n'
        '原始逐篇擷取：仍為 unverified；只有報告選入的主張經對應驗證。\n\n'
        '完整逐篇分析閱讀版位於 paper_analysis_readings/；原始組裝版本位於 analysis/；正式逐篇附錄位於 paper_reviews/。\n\n'
        '來源缺漏見 issues.jsonl；比較矩陣的驗證範圍見 comparison_verification.json（v2）或報告主張（v1）。\n').encode())
    atomic_bytes(destination/'issues.jsonl',(''.join(canonical({'kind':'source_gap',**gap})+'\n' for gap in status(root)['source_gaps'])).encode())
    # Public sources + artifacts are sufficient after deleting the queue DB.
    shutil_copy=__import__('shutil').copytree
    shutil_copy(Path(root)/'corpus',destination/'sources')
    atomic_bytes(destination/'evidence.jsonl',(''.join(canonical(ev)+'\n' for ev in evidence.values())).encode())
    if research_bundle:
        from .research import save_research_bundle
        save_research_bundle(research_bundle,destination,index)
        from .workflow import export_reading_checkpoint
        export_reading_checkpoint(root,destination/'reading_checkpoint')
    return dict(result,path=str(destination))


def deliver(root,draft,evidence,verification,comparison,out,comparison_verification=None,field_assessments=None,research_bundle=None):
    """Publish only a complete staged delivery directory, never partial success."""
    import os
    import shutil
    import tempfile
    destination=Path(out).resolve()
    need(not destination.exists(),'OUTPUT_CONFLICT','Delivery directory already exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.delivery-pending-',dir=destination.parent))
    work=stage/'bundle'
    try:
        result=_deliver_staged(root,draft,evidence,verification,comparison,work,comparison_verification,field_assessments,research_bundle)
        # Copy validated evidence hashes and original snapshots into the same
        # atomic directory commit as the report and all ledgers.
        need(not destination.exists(),'OUTPUT_CONFLICT','Output appeared during delivery')
        os.rename(work,destination)
        return dict(result,path=str(destination))
    finally:
        shutil.rmtree(stage,ignore_errors=True)
