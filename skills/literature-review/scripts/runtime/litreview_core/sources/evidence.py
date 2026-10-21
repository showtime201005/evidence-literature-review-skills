from ..artifacts import envelope, identifier
from ..contracts import validate
from ..errors import ReviewError
from . import source_bytes

SEPARATOR='\n[…]\n'


def _document(index, document_id):
    matches=[d for d in index['payload']['documents'] if d['document_id']==document_id]
    if len(matches)!=1:
        raise ReviewError('SOURCE_MISSING','Unknown or ambiguous document_id',document_id)
    return matches[0]


def locate(corpus_dir,index,document_id,quote,start_byte=None,end_byte=None):
    doc=_document(index,document_id)
    raw=source_bytes(corpus_dir,doc)
    try:
        needle=quote.encode('utf-8')
    except (AttributeError,UnicodeError) as exc:
        raise ReviewError('INVALID_EXCERPT','Quote must be UTF-8 text') from exc
    if not needle:
        raise ReviewError('INVALID_EXCERPT','Empty quote is not evidence')
    if start_byte is not None or end_byte is not None:
        if start_byte is None or end_byte is None:
            raise ReviewError('INVALID_LOCATOR','Both offsets are required')
        span=dict(document_id=document_id,content_hash=doc['content_hash'],start_byte=start_byte,end_byte=end_byte,excerpt=quote)
        check_span(corpus_dir,index,span)
        return span
    offsets=[]
    cursor=0
    while (found:=raw.find(needle,cursor))!=-1:
        offsets.append(found)
        cursor=found+1
    if not offsets:
        raise ReviewError('EXCERPT_NOT_FOUND','Exact quote not present; approximate matching is not accepted')
    if len(offsets)>1:
        raise ReviewError('AMBIGUOUS_EXCERPT','Specify exact byte offsets for a repeated quote',offsets)
    span=dict(document_id=document_id,content_hash=doc['content_hash'],start_byte=offsets[0],end_byte=offsets[0]+len(needle),excerpt=quote)
    check_span(corpus_dir,index,span)
    return span


def check_span(corpus_dir,index,span):
    from ..contracts import validate_object
    validate_object('Span',span)
    doc=_document(index,span['document_id'])
    if span['content_hash']!=doc['content_hash']:
        raise ReviewError('SOURCE_VERSION_MISMATCH','Evidence uses a different source version')
    raw=source_bytes(corpus_dir,doc)
    start,end=span['start_byte'],span['end_byte']
    if not 0<=start<end<=len(raw):
        raise ReviewError('INVALID_LOCATOR','Byte interval is outside the source')
    try:
        excerpt=raw[start:end].decode('utf-8')
        raw[:start].decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ReviewError('INVALID_LOCATOR','Offset splits a UTF-8 character') from exc
    if excerpt!=span['excerpt']:
        raise ReviewError('EXCERPT_MISMATCH','Excerpt differs from frozen source bytes')
    for block in index['payload']['blocks']:
        if block['document_id']!=doc['document_id']:
            continue
        if block['kind']=='table' and start<block['end_byte'] and end>block['start_byte']:
            if start>block['start_byte'] or end<block['end_byte']:
                raise ReviewError('TABLE_CONTEXT_REQUIRED','Cite the entire table block including headers; add caption/notes as additional spans',block['block_id'])
    return True


def make_evidence(corpus_dir,index,spans,source_role='context'):
    if not spans:
        raise ReviewError('INVALID_EXCERPT','At least one span is required')
    for span in spans:
        check_span(corpus_dir,index,span)
    payload=dict(evidence_id=identifier('evidence',[spans,source_role]),spans=spans,
                 excerpt=SEPARATOR.join(s['excerpt'] for s in spans),source_role=source_role)
    artifact=envelope('Evidence',payload)
    validate(artifact)
    check_evidence(corpus_dir,index,artifact)
    return artifact


def check_evidence(corpus_dir,index,artifact):
    validate(artifact)
    if artifact['artifact_type']!='Evidence':
        raise ReviewError('WRONG_ARTIFACT_TYPE','Expected Evidence')
    for span in artifact['payload']['spans']:
        check_span(corpus_dir,index,span)
        if artifact['payload']['source_role'] in ('author_result','author_limitation'):
            for block in index['payload']['blocks']:
                if block['document_id']==span['document_id'] and block['kind']=='references' and span['start_byte']<block['end_byte'] and span['end_byte']>block['start_byte']:
                    raise ReviewError('SECONDARY_SOURCE_ONLY','A bibliography entry is not a directly read research finding')
    if artifact['payload']['excerpt']!=SEPARATOR.join(s['excerpt'] for s in artifact['payload']['spans']):
        raise ReviewError('EXCERPT_MISMATCH','Combined excerpt differs from its spans')
    return True
