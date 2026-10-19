"""Conservative Markdown block scanner with byte-exact, exhaustive partitioning."""
import os
from pathlib import Path
import re
import shutil
import tempfile
from ..artifacts import digest, envelope, identifier, read_json, safe_path, write_json
from ..contracts import validate, validate_object
from ..errors import ReviewError

REFERENCE_HEADINGS = {'references','bibliography','參考文獻','参考文献','參考資料'}
EXCLUDED_NAMES = {'skill.md','readme.md','report.md','review.md','manifest.md','research_request.md'}


def scan(raw, document_id):
    """Every original byte belongs to exactly one block, including whitespace.

    Recognizes ATX headings, fenced code, $$ equations, pipe tables, captions,
    frontmatter and reference sections. Unrecognized Markdown remains body.
    This is a locator scanner, not a CommonMark rendering implementation.
    """
    try:
        text=raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ReviewError('ENCODING_ERROR','Source must be valid UTF-8') from exc
    lines=text.splitlines(keepends=True)
    starts=[0]
    for line in lines:
        starts.append(starts[-1]+len(line.encode('utf-8')))
    sections=[]
    reference_level=None
    blocks=[]
    content_hash=digest(raw)
    i=0
    while i<len(lines):
        start=i
        stripped=lines[i].strip()
        heading=re.match(r'^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$',lines[i].rstrip('\r\n'))
        fence=re.match(r'^ {0,3}(`{3,}|~{3,})',lines[i])
        if i==0 and stripped=='---' and any(x.strip() in ('---','...') for x in lines[1:]):
            i+=1
            while i<len(lines) and lines[i].strip() not in ('---','...'):
                i+=1
            i+=1
            kind='metadata'
        elif heading:
            level=len(heading[1])
            title=heading[2]
            sections=[s for s in sections if s[0]<level]+[(level,title)]
            if reference_level is not None and level<=reference_level:
                reference_level=None
            if title.casefold() in REFERENCE_HEADINGS:
                reference_level=level
            kind='references' if reference_level is not None else 'heading'
            i+=1
        elif not stripped:
            kind='format'
            i+=1
            while i<len(lines) and not lines[i].strip():
                i+=1
        elif fence:
            marker=fence[1][0]
            size=len(fence[1])
            i+=1
            while i<len(lines):
                closing=re.fullmatch(r' {0,3}'+re.escape(marker)+'{'+str(size)+r',}\s*',lines[i].rstrip('\r\n'))
                i+=1
                if closing:
                    break
            kind='references' if reference_level is not None else 'code'
        elif stripped.startswith('$$'):
            i+=1
            if stripped=='$$':
                while i<len(lines):
                    closed=lines[i].strip()=='$$'
                    i+=1
                    if closed:
                        break
            kind='references' if reference_level is not None else 'equation'
        elif '|' in stripped and i+1<len(lines) and re.match(r'^\s*\|?\s*:?-{3,}',lines[i+1]):
            i+=2
            while i<len(lines) and '|' in lines[i] and lines[i].strip():
                i+=1
            kind='references' if reference_level is not None else 'table'
        else:
            kind='references' if reference_level is not None else ('caption' if re.match(r'^(Figure|Fig\.|Table|圖|表)\s*\d',stripped,re.I) else 'body')
            i+=1
            while i<len(lines) and lines[i].strip():
                if re.match(r'^ {0,3}(#{1,6})\s|^ {0,3}(`{3,}|~{3,})|^\s*\$\$',lines[i]):
                    break
                if i+1<len(lines) and '|' in lines[i] and re.match(r'^\s*\|?\s*:?-{3,}',lines[i+1]):
                    break
                i+=1
        begin,end=starts[start],starts[i]
        block_hash=digest(raw[begin:end])
        blocks.append(dict(block_id=identifier('block',[document_id,begin,end,block_hash]),
            document_id=document_id,content_hash=content_hash,hash=block_hash,kind=kind,
            section_path=[s[1] for s in sections],start_byte=begin,end_byte=end,
            start_line=start+1,end_line=i))
    return blocks


def extract_metadata(raw,blocks):
    """Only explicit basic frontmatter scalars and the first H1; no title guessing."""
    result={}
    provenance={}
    for block in blocks:
        text=raw[block['start_byte']:block['end_byte']].decode('utf-8')
        if block['kind']=='metadata':
            for key,value in re.findall(r'^(title|authors|year|doi):\s*(.+)$',text,re.M):
                value=value.strip().strip('"\'')
                if value:
                    result[key]=value
                    provenance[key]={'origin':'provided_text','block_id':block['block_id'],'external_verification':'not_checked'}
        if block['kind']=='heading' and text.lstrip().startswith('# ') and 'title' not in result:
            result['title']=text.lstrip()[2:].strip().rstrip('#').strip()
            provenance['title']={'origin':'provided_text','block_id':block['block_id'],'external_verification':'not_checked'}
    return result,provenance


def source_bytes(corpus_dir, document):
    path=safe_path(corpus_dir,document['snapshot_path'])
    if not path.is_file():
        raise ReviewError('SOURCE_MISSING','Source snapshot is missing',document['document_id'])
    raw=path.read_bytes()
    if digest(raw)!=document['content_hash'] or len(raw)!=document['size_bytes']:
        raise ReviewError('SOURCE_VERSION_MISMATCH','Source snapshot hash or length changed',document['document_id'])
    return raw


def load_corpus(root, check=True):
    index=validate(read_json(Path(root)/'corpus.json'))
    if index['artifact_type']!='CorpusIndex':
        raise ReviewError('WRONG_ARTIFACT_TYPE','Expected CorpusIndex')
    if check:
        docs=index['payload']['documents']
        by_id={d['document_id']:d for d in docs}
        if len(by_id)!=len(docs):
            raise ReviewError('DUPLICATE_ID','Duplicate document ID')
        if index['payload']['logical_paper_count']!=len({d['paper_id'] for d in docs}):
            raise ReviewError('CORPUS_INVALID','Logical paper count mismatch')
        blocks=index['payload']['blocks']
        if len({b['block_id'] for b in blocks})!=len(blocks):
            raise ReviewError('DUPLICATE_ID','Duplicate block ID')
        for block in blocks:
            if block['document_id'] not in by_id:
                raise ReviewError('SOURCE_MISSING','Block points to unknown document')
        for doc in docs:
            raw=source_bytes(root,doc)
            expected=scan(raw,doc['document_id'])
            actual=[b for b in blocks if b['document_id']==doc['document_id']]
            if expected!=actual:
                raise ReviewError('BLOCK_INDEX_MISMATCH','Block index does not match the frozen source',doc['document_id'])
    return index


def prepare(input_dir, output, manifest=None, max_papers=100):
    root=Path(input_dir).resolve()
    out=Path(output).resolve()
    if not root.is_dir():
        raise ReviewError('INPUT_MISSING','Input directory does not exist')
    if out.is_relative_to(root):
        raise ReviewError('RECURSIVE_OUTPUT','Output must be outside the corpus input directory')
    if not isinstance(max_papers,int) or not 1<=max_papers<=100:
        raise ReviewError('PAPER_LIMIT','max_papers must be between 1 and 100')
    dispositions=[]
    if manifest:
        data=read_json(manifest)
        validate_object('Manifest',data)
        entries=data['documents']
        selected={Path(e['path']).as_posix() for e in entries}
        for path in sorted(root.rglob('*.md')):
            relative=path.relative_to(root).as_posix()
            if relative not in selected:
                dispositions.append({'path':relative,'status':'excluded_not_in_manifest'})
    else:
        entries=[]
        for path in sorted(root.rglob('*.md')):
            relative=path.relative_to(root).as_posix()
            if path.name.casefold() in EXCLUDED_NAMES:
                dispositions.append({'path':relative,'status':'excluded_reserved_name','needs_manifest_to_include':True})
            else:
                entries.append({'path':relative,'paper_id':identifier('paper',relative)})
    if not entries:
        raise ReviewError('EMPTY_CORPUS','No selected Markdown sources')
    paper_count=len({e['paper_id'] for e in entries})
    if paper_count>max_papers:
        raise ReviewError('PAPER_LIMIT','Logical paper limit exceeded',{'actual':paper_count,'maximum':max_papers})
    if out.exists():
        raise ReviewError('OUTPUT_CONFLICT','Corpus output already exists; use a new snapshot directory')
    out.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.corpus-pending-',dir=out.parent))
    docs=[]
    all_blocks=[]
    seen_paths=set()
    seen_hashes={}
    try:
        (stage/'sources').mkdir()
        for entry in entries:
            path=safe_path(root,entry['path'])
            if path.suffix.casefold()!='.md' or not path.is_file():
                raise ReviewError('INPUT_MISSING','Manifest path must name a local Markdown file',entry['path'])
            if path in seen_paths:
                raise ReviewError('DUPLICATE_SOURCE','One source path may appear only once',entry['path'])
            seen_paths.add(path)
            raw=path.read_bytes()
            if not raw.strip():
                raise ReviewError('EMPTY_SOURCE','Source contains no content',entry['path'])
            content_hash=digest(raw)
            doc_id=identifier('document',[entry['paper_id'],entry['path'],content_hash])
            blocks=scan(raw,doc_id)
            metadata,origin=extract_metadata(raw,blocks)
            for key,value in entry.get('metadata',{}).items():
                metadata[key]=value
                origin[key]={'origin':'user_manifest','external_verification':'not_checked'}
            gaps=[]
            text=raw.decode('utf-8')
            for image in re.findall(r'!\[[^\]]*\]\(([^)]+)\)',text):
                remote=bool(re.match(r'^(https?:)?//',image))
                gaps.append({'kind':'remote_image_not_fetched' if remote else 'image_not_interpreted','target':image})
            for target in re.findall(r'(?<!!)\[[^\]]+\]\((https?://[^)]+)\)',text):
                gaps.append({'kind':'external_link_not_fetched','target':target})
            doc=dict(document_id=doc_id,paper_id=entry['paper_id'],content_hash=content_hash,encoding='utf-8',
                source_path=entry['path'],snapshot_path='sources/'+content_hash+'.md',size_bytes=len(raw),
                metadata=metadata,metadata_provenance=origin,source_gaps=gaps,
                role=entry.get('role','main'),version=entry.get('version','not_reported'))
            if content_hash in seen_hashes:
                doc['duplicate_of']=seen_hashes[content_hash]
            seen_hashes.setdefault(content_hash,doc_id)
            (stage/doc['snapshot_path']).write_bytes(raw)
            docs.append(doc)
            all_blocks.extend(blocks)
            dispositions.append({'path':entry['path'],'status':'imported','document_id':doc_id})
        index=envelope('CorpusIndex',dict(documents=docs,blocks=all_blocks,dispositions=dispositions,
            logical_paper_count=paper_count,policy='corpus_only',external_lookup=False))
        validate(index)
        write_json(stage/'corpus.json',index)
        coverage=envelope('CoverageSet',dict(records=[dict(coverage_id=identifier('coverage',b['block_id']),
            block_id=b['block_id'],task_id='not_assigned',artifact_refs=[],layer='analysis',status='pending')
            for b in all_blocks if b['kind']!='format'],execution='partial',quality='unverified'))
        validate(coverage)
        write_json(stage/'coverage.json',coverage)
        write_json(stage/'references.json',{'schema_version':'1.0.0','source_policy':'corpus_only',
            'documents':[{'document_id':d['document_id'],'paper_id':d['paper_id'],'metadata':d['metadata'],
                          'metadata_provenance':d['metadata_provenance']} for d in docs]})
        # Directory rename publishes all snapshots and indexes together.
        if out.exists():
            raise ReviewError('OUTPUT_CONFLICT','Output appeared during prepare')
        os.rename(stage,out)
        return index
    finally:
        if stage.exists():
            shutil.rmtree(stage)
