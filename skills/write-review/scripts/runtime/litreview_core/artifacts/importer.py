"""Normalize external files. Imported material never acquires semantic approval."""
import csv
import io
from pathlib import Path
import re
from . import digest, envelope
from ..contracts import validate
from ..errors import ReviewError


def citation_tokens(text):
    """Return exact char positions. Author/year resolution requires explicit aliases."""
    pattern=r'\[(?:\d+(?:\s*[-–,]\s*\d+)*)\]|\{\{evidence:[^{}]+\}\}|[（(][^()（）\n]{1,100}?[,，]\s*(?:19|20)\d{2}[a-z]?[）)]'
    return [{'token':m[0],'start_char':m.start(),'end_char':m.end()} for m in re.finditer(pattern,text)]


def _number_labels(token):
    if not re.fullmatch(r'\[\d+(?:\s*[-–,]\s*\d+)*\]',token):
        return [token]
    labels=[]
    for item in token[1:-1].split(','):
        item=item.strip()
        if not re.fullmatch(r'\d+(?:\s*[-–]\s*\d+)?',item):
            raise ReviewError('INVALID_CITATION_RANGE','Malformed citation range',token)
        if re.search('[-–]',item):
            left,right=map(int,re.split('[-–]',item))
            if right<left or right-left>100:
                raise ReviewError('INVALID_CITATION_RANGE','Invalid or excessive citation range',token)
            labels.extend(str(n) for n in range(left,right+1))
        else:
            labels.append(str(int(item)))
    return labels


def resolve_citations(text,bibliography):
    """Bibliography: list of {label, source_ref, aliases?}; ambiguity is explicit."""
    mapping={}
    for record in bibliography:
        if not isinstance(record,dict) or not isinstance(record.get('source_ref'),str) or not record['source_ref']:
            raise ReviewError('INVALID_BIBLIOGRAPHY','Each entry requires a nonempty source_ref')
        aliases=record.get('aliases',[])
        if not isinstance(aliases,list) or any(not isinstance(a,str) for a in aliases):
            raise ReviewError('INVALID_BIBLIOGRAPHY','aliases must be an array of strings')
        for alias in [str(record.get('label',''))]+aliases:
            if alias:
                mapping.setdefault(alias,[]).append(record['source_ref'])
    results=[]
    for item in citation_tokens(text):
        labels=_number_labels(item['token'])
        candidates=[]
        unresolved=[]
        ambiguous=[]
        for label in labels:
            found=sorted(set(mapping.get(label,[])))
            candidates.extend(found)
            if not found:
                unresolved.append(label)
            if len(found)>1:
                ambiguous.append(label)
        status='ambiguous_reference' if ambiguous else ('needs_source' if unresolved else 'mapped_unverified')
        results.append(dict(item,status=status,source_refs=sorted(set(candidates)),unresolved=unresolved,ambiguous=ambiguous))
    return results


def import_artifact(path,kind='native',bibliography=None):
    path=Path(path)
    raw=path.read_bytes()
    if kind=='native':
        from . import read_json
        return validate(read_json(path))
    try:
        text=raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ReviewError('ENCODING_ERROR','External material must be UTF-8') from exc
    if kind=='report':
        references=resolve_citations(text,bibliography or [])
        citation_map={}
        for item in references:
            if item['status']=='mapped_unverified':
                citation_map[item['token']]=item['source_refs']
        result=envelope('ReviewDraft',dict(text=text,claims=[],claim_mappings=[],citation_map=citation_map,
            reference_candidates=references,scan_status='not_checked'))
    else:
        if kind=='csv':
            reader=csv.DictReader(io.StringIO(text))
            if not reader.fieldnames or 'source_id' not in reader.fieldnames:
                raise ReviewError('SOURCE_ID_REQUIRED','CSV requires a source_id column')
            rows=list(reader)
            if any(None in row or any(v is None for v in row.values()) for row in rows):
                raise ReviewError('INVALID_CSV','Row length does not match CSV headers')
            if any(not row.get('source_id') for row in rows):
                raise ReviewError('SOURCE_ID_REQUIRED','Every CSV row needs a source_id')
            materials=[dict(row,verification_status='unverified') for row in rows]
        elif kind=='notes':
            materials=[{'text':text,'origin_file':path.name,'content_hash':digest(raw),'verification_status':'unverified'}]
        elif kind=='bibliography':
            from . import read_json
            materials=read_json(path)
            if not isinstance(materials,list) or any(not isinstance(x,dict) for x in materials):
                raise ReviewError('INVALID_BIBLIOGRAPHY','Bibliography must be an array of objects')
        else:
            raise ReviewError('UNKNOWN_IMPORT_KIND','Unsupported import kind',kind)
        result=envelope('ExternalMaterials',dict(materials=materials,verification_status='unverified',input_kind=kind))
    validate(result)
    return result
