"""Readable claim-to-source cards generated from validated original bytes."""
import re
from urllib.parse import quote
from .artifacts import safe_path
from .sources.evidence import check_evidence


def evidence_cards(claims,evidence,corpus,index,verified=False,source_prefix='sources'):
    docs={d['document_id']:d for d in index['payload']['documents']};blocks=index['payload']['blocks']
    referenced={eid for c in claims for eid in c['evidence_refs']}
    for eid in referenced:check_evidence(corpus,index,evidence[eid])
    state='已通過匹配的獨立來源查核；未經人工審查' if verified else '來源定位有效；語意支持尚未獨立查核'
    lines=['# 主張與原文證據','',state+'。','',
        '每張卡片保留完整主張、原文摘錄、章節、行號、版本及原文連結。行號供閱讀；UTF-8 bytes 與 hash 供精確重驗。','']
    for n,c in enumerate(claims,1):
        lines += [f'## C{n}：'+c['text'],'',f"主張 ID：`{c['claim_id']}`；類型：{c['claim_type']}",'']
        if not c['evidence_refs']:
            lines += ['範圍／流程聲明，未引用研究結果。' if c['claim_type']=='scope_statement' else '本主張未附證據，尚未可查核。',''];continue
        for eid in dict.fromkeys(c['evidence_refs']):
            ev=evidence[eid];lines += [f'### 證據 `{eid}`','',f"來源角色：{ev['payload']['source_role']}",'']
            for span in ev['payload']['spans']:
                doc=docs[span['document_id']];raw=safe_path(corpus,doc['snapshot_path']).read_bytes()
                start,end=span['start_byte'],span['end_byte'];first=raw[:start].count(b'\n')+1;last=raw[:max(start,end-1)].count(b'\n')+1
                section=next(('/'.join(b['section_path']) for b in blocks if b['document_id']==span['document_id'] and b['start_byte']<=start<b['end_byte']),'章節未提供')
                title=str(doc['metadata'].get('title') or doc['source_path']).replace('\n',' ').replace('[','\\[').replace(']','\\]')
                target=quote(source_prefix+'/'+doc['snapshot_path'],safe='/')
                lines += [f'來源：[{title}]({target})；章節：{section}；行 {first}–{last}。','',
                    f"版本 SHA-256：`{span['content_hash']}`；UTF-8 bytes [{start}, {end})。",'']
                longest=max([len(x) for x in re.findall(r'`+',span['excerpt'])]+[2]);fence='`'*(longest+1)
                lines += [fence+'text',span['excerpt'].rstrip('\n'),fence,'']
    return '\n'.join(lines).rstrip()+'\n'
