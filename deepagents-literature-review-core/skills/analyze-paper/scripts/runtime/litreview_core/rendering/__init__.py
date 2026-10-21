"""Stable numbered draft renderer. Metadata is never completed by inference."""
import re
import json
from ..artifacts import digest
from ..errors import ReviewError
from ..sources.evidence import check_evidence
from ..verification import inspect_draft


def _text(value):
    if isinstance(value,list):
        return '; '.join(_text(v) for v in value)
    return str(value).replace('\r',' ').replace('\n',' ').replace('[','\\[').replace(']','\\]')


def _authors(value):
    # The dependency-free frontmatter reader can retain flow arrays as text.
    # Normalize only unambiguous JSON string arrays for display; retain source
    # metadata and hashes, and never guess malformed or richer YAML syntax.
    if isinstance(value,str):
        try:
            parsed=json.loads(value)
        except ValueError:
            parsed=None
        if isinstance(parsed,list) and parsed and all(isinstance(x,str) for x in parsed):
            value=parsed
    return _text(value)


def render(draft,evidence,corpus_dir,index,final=False,verification=None):
    if final:
        from ..review import gate
        gate(draft,evidence,corpus_dir,index,verification)
    issues=inspect_draft(draft,set(evidence))
    blockers=[i for i in issues if i['severity']=='blocker']
    if blockers:
        raise ReviewError('STRUCTURAL_GATE_FAILED','Draft has structural blockers',blockers)
    for value in evidence.values():
        check_evidence(corpus_dir,index,value)
    docs={d['document_id']:d for d in index['payload']['documents']}
    numbers={}
    used_evidence=[]
    ledger=[]

    def cite(eid):
        if eid not in evidence:
            raise ReviewError('UNKNOWN_EVIDENCE','Cannot render unknown evidence',eid)
        used_evidence.append(eid)
        selected=[]
        for span in evidence[eid]['payload']['spans']:
            docid=span['document_id']
            if docid not in numbers:
                numbers[docid]=len(numbers)+1
            if numbers[docid] not in selected:
                selected.append(numbers[docid])
        return '['+', '.join(map(str,selected))+']'

    text=draft['payload']['text']
    # Native placeholders are the only renderable references in v0.1.
    # External bibliographies map to source refs for inspection, never silently
    # reinterpret their IDs as program-validated Evidence.
    if re.search(r'\[\d+(?:\s*[-–,]\s*\d+)*\]|[（(][^()（）\n]{1,100}?[,，]\s*(?:19|20)\d{2}[a-z]?[）)]',text):
        raise ReviewError('EXTERNAL_REFERENCES_REQUIRE_NORMALIZATION','Replace imported reference tokens with validated evidence placeholders before rendering')
    text=re.sub(r'\{\{evidence:([^{}]+)\}\}',lambda m:cite(m[1]),text)
    def compact(match):
        values=list(dict.fromkeys(re.findall(r'\d+',match[0])))
        return '['+', '.join(values)+']'
    # Keep every exact evidence link in the ledger; collapse repeated document
    # numbers only within adjacent citation runs for readable prose.
    text=re.sub(r'\[\d+(?:, \d+)*\](?:[ \t]+\[\d+(?:, \d+)*\])+',compact,text)
    for claim in draft['payload']['claims']:
        for eid in claim['evidence_refs']:
            if eid not in used_evidence:
                raise ReviewError('UNRENDERED_CITATION','Claim evidence is not represented by a report placeholder',eid)
        ledger.append({'claim_id':claim['claim_id'],'text':claim['text'],'evidence_refs':claim['evidence_refs'],
                       'locator_status':'valid','semantic_status':'not_checked'})
    front='> 草稿：僅分析提供的文本（corpus-only）。引用定位經程式檢查；語意支持與全文分析尚未驗收。外部書目與出版狀態未查證。\n\n'
    if final:
        front='> 僅分析提供文本（corpus-only）。所有交付主張經獨立模型任務驗證；尚未人工複核。外部書目與出版狀態未查證。\n\n'
        for item in ledger:
            item['semantic_status']='supported'
    references=[]
    for docid,number in numbers.items():
        doc=docs[docid]
        meta=doc['metadata']
        fields=[_authors(meta.get('authors','作者未提供')),_text(meta.get('year','年份未提供')),
                _text(meta.get('title','標題未提供'))]
        if meta.get('doi'):
            fields.append('DOI: '+_text(meta['doi']))
        fields.append('來源: '+_text(doc['source_path']))
        fields.append('版本 SHA-256: '+doc['content_hash'])
        fields.append('書目未經外部查證')
        references.append(f'[{number}] '+'. '.join(fields)+'.')
    locations=[]
    for eid in dict.fromkeys(used_evidence):
        for span in evidence[eid]['payload']['spans']:
            locations.append(f"- {eid}: {span['document_id']}, UTF-8 bytes [{span['start_byte']}, {span['end_byte']})")
    output=front+text.rstrip()+'\n\n## References\n\n'+'\n\n'.join(references)+'\n\n## Evidence locations\n\n'+'\n'.join(locations)+'\n'
    return output,{'schema_version':'1.0.0','draft_artifact_id':draft['artifact_id'],
        'draft_hash':digest(draft['payload']['text'].encode()),'quality':'passed' if final else 'unverified',
        'ledger':ledger,'issues':issues,'references':[{'number':n,'document_id':d} for d,n in numbers.items()]}
