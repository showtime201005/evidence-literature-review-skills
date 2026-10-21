"""Portable, immutable deliveries of the exact hierarchically reviewed text.

Export always re-runs the native proof gate against current bytes and actual
RuntimeIdentity objects. Saved identity JSON is an unauthenticated provenance
snapshot, never a source of runtime trust. No model calls or prose rewrites.
"""
from __future__ import annotations

import copy
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
from urllib.parse import quote

from .hierarchical_proof import ProofError, RuntimeIdentity, payload_hash, verify_proof
from .scientific_records import source_packet
from .review_artifacts import escape_markdown
from .task_store import canonical


class DeliveryError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _identity_data(identity):
    if type(identity) is not RuntimeIdentity:
        raise DeliveryError('UNTRUSTED_IDENTITY', 'Only actual RuntimeIdentity objects may be exported')
    return {'execution_id': identity.execution_id, 'context_id': identity.context_id,
            'role': identity.role, 'input_hashes': dict(identity.input_hashes),
            'dependency_hashes': dict(identity.dependency_hashes),
            'delivered_dependency_receipt_hashes': dict(identity.delivered_dependency_receipt_hashes),
            'output_hashes': dict(identity.output_hashes),
            'ancestor_context_ids': list(identity.ancestor_context_ids),
            'run_id': identity.run_id, 'task_call_id': identity.task_call_id,
            'parent_context_id': identity.parent_context_id}


def _snapshot(result):
    if not isinstance(result, dict):
        raise DeliveryError('INVALID_RESULT', 'Pass the workflow result or a partial result dictionary')
    identities = {key: RuntimeIdentity(**_identity_data(identity))
                  for key, identity in result.get('identities', {}).items()}
    return {'bundle': copy.deepcopy(result.get('bundle')),
            'nodes': copy.deepcopy(result.get('nodes', {})), 'identities': identities,
            'records': copy.deepcopy(result.get('records', [])),
            'source_quote_witness_required': result.get('source_quote_witness_required', False),
            'proof_submissions': copy.deepcopy(result.get('proof_submissions', {})),
            'sections': copy.deepcopy(result.get('sections', []))}


def _gate(snapshot):
    bundle = snapshot['bundle']
    if not bundle:
        raise DeliveryError('PROOF_NOT_COMPILED', 'No compiled proof bundle exists')
    if not isinstance(bundle, dict) or not {'plan', 'materials'} <= set(bundle):
        raise DeliveryError('PROOF_BUNDLE_INCOMPLETE', 'Compiled proof materials or plan are incomplete')
    receipt=verify_proof(bundle['plan'], snapshot['nodes'], bundle['materials'], snapshot['identities'])
    if snapshot['source_quote_witness_required']:
        from .source_witness_audit import verify_source_witness_audits
        try:
            witness_audit=verify_source_witness_audits(bundle,snapshot['nodes'],snapshot['proof_submissions'])
        except (ValueError,KeyError,TypeError) as exc:
            raise DeliveryError('SOURCE_WITNESS_AUDIT_FAILED',str(exc)) from exc
        receipt={**receipt,'source_witness_audit':witness_audit}
    return receipt


def _check_lines(render):
    text = render['text']
    actual, offset = [], 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip('\r\n')
        if body.strip():
            actual.append((offset, body))
        offset += len(line)
    if actual != [(line['start_char'], line['text']) for line in render['lines']]:
        raise DeliveryError('INVALID_LINE_MAP', 'Rendered text has missing or additional nonempty lines')
    for line in render['lines']:
        if text[line['start_char']:line['end_char']] != line['text']:
            raise DeliveryError('INVALID_LINE_MAP', 'Character offsets do not map the exact rendered text')


def _renders(bundle):
    materials, scope = bundle['materials'], bundle['materials']['review/scope']
    if payload_hash(materials['delivery/render']) != scope['delivery_sha256']:
        raise DeliveryError('RENDER_HASH_MISMATCH', 'Final text differs from the scope reviewed by the root auditor')
    renders = {}
    expected = []
    for sid in scope['section_ids']:
        value = materials['render/' + quote(sid, safe='')]
        section = materials['section/' + quote(sid, safe='')]
        if (value['section_id'] != sid or value['text_sha256'] != payload_hash(value['text'].encode('utf-8'))
                or payload_hash(section) != scope['section_hashes'][sid]):
            raise DeliveryError('SECTION_HASH_MISMATCH', 'Section or exact section rendering differs from reviewed material')
        _check_lines(value)
        renders[sid] = value
        expected.append(value['text'] + '\n\n')
    full = materials['delivery/render']
    _check_lines(full)
    if full['text'] != ''.join(expected):
        raise DeliveryError('RENDER_PROJECTION_MISMATCH', 'Delivery is not the exact reviewed section concatenation')
    main_text, main_lines, offset = [], [], 0
    for sid in scope['root_section_ids']:
        value = renders[sid]
        main_text.append(value['text'] + '\n\n')
        main_lines.extend({**line, 'section_id': sid,
                           'start_char': offset + line['start_char'],
                           'end_char': offset + line['end_char']} for line in value['lines'])
        offset += len(value['text']) + 2
    main = {'schema': 'mapped-review-root-projection/1',
            'text': ''.join(main_text), 'lines': main_lines,
            'root_section_ids': scope['root_section_ids']}
    _check_lines(main)
    return renders, full, main


def _source_index(bundle, renders):
    materials, scope = bundle['materials'], bundle['materials']['review/scope']
    originals, parts, evidence = {}, {}, {}
    for pid in scope['paper_ids']:
        raw = materials['original/' + quote(pid, safe='')]
        if not isinstance(raw, bytes) or sha256(raw).hexdigest() != scope['source_versions'][pid]:
            raise DeliveryError('SOURCE_HASH_MISMATCH', 'Original source differs from the reviewed version')
        path = 'sources/' + sha256(raw).hexdigest() + '.md'
        originals[pid] = {'path': path, 'sha256': sha256(raw).hexdigest(), 'size_bytes': len(raw)}
        packet = source_packet(pid, raw, list(scope['questions'].values()))
        for part in packet['parts']:
            ref = pid + '/' + part['part_id']
            parts[ref] = {key: part[key] for key in ('part_id', 'start_byte', 'end_byte')}
            parts[ref].update(paper_id=pid, source_path=path, source_sha256=packet['source_sha256'],
                              text_sha256=payload_hash(part['text'].encode('utf-8')))
        reader = materials['reader/' + quote(pid, safe='')]
        for item in reader['evidence']:
            excerpt = raw[item['start_byte']:item['end_byte']]
            if (item['paper_id'] != pid or item['source_sha256'] != packet['source_sha256']
                    or excerpt != item['quote'].encode('utf-8')):
                raise DeliveryError('EVIDENCE_OFFSET_MISMATCH', 'Reader quote no longer matches its exact original bytes')
            evidence[item['id']] = {key: item[key] for key in
                                   ('paper_id', 'part_id', 'source_sha256', 'start_byte', 'end_byte')}
            evidence[item['id']].update(source_path=path, quote_sha256=sha256(excerpt).hexdigest())
    claims = {}
    for sid, render in renders.items():
        for cid, claim in render['claims'].items():
            refs = claim['evidence_refs']
            if not set(refs) <= set(parts):
                raise DeliveryError('MISSING_SOURCE_REFERENCE', 'A reviewed claim references a nonexistent source part')
            claims[cid] = {'section_id': sid, 'source_refs': refs,
                           'population_paper_ids': claim['population_paper_ids'],
                           'premise_claim_ids': claim['premise_claim_ids']}
    return {'schema': 'review-source-span-index/1',
            'offset_unit': 'UTF-8 bytes in the unmodified original file; end exclusive',
            'sources': originals, 'parts': parts, 'reader_evidence': evidence,
            'claims': claims,
            'note': 'Mechanical reference index. It adds no scientific verdict or new source.'}


def _comparison_csv(bundle):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(['section_id', 'paper_id_json', 'dimension_json', 'claims_json'])
    scope = bundle['materials']['review/scope']
    for sid in scope['section_ids']:
        section = bundle['materials']['section/' + quote(sid, safe='')]
        if section['kind'] != 'comparison':
            continue
        by_local = {c['local_id']: c for c in section['claims']}
        for cell in section['cells']:
            claims = [{'claim_id': sid + '/' + cid, 'text': by_local[cid]['text'],
                       'source_refs': by_local[cid]['evidence_refs']} for cid in cell['claim_ids']]
            writer.writerow([sid, json.dumps(cell['paper_id'], ensure_ascii=False),
                             json.dumps(cell['dimension'], ensure_ascii=False),
                             json.dumps(claims, ensure_ascii=False, separators=(',', ':'))])
    return stream.getvalue().encode('utf-8')


def _comparison_markdown(bundle, source_index):
    """Readable mechanical projection of the same independently reviewed cells."""
    lines=['# 研究比較表','']
    mapping=[]
    count=0
    for sid in bundle['materials']['review/scope']['section_ids']:
        section=bundle['materials']['section/'+quote(sid,safe='')]
        if section['kind']!='comparison':
            continue
        count+=1
        dimensions=section['dimensions']
        by_id={claim['local_id']:claim for claim in section['claims']}
        by_cell={(cell['paper_id'],cell['dimension']):cell for cell in section['cells']}
        lines.extend(['## 比較表 '+str(count),'',
            '| 論文 | '+' | '.join(escape_markdown(d) for d in dimensions)+' |',
            '| --- | '+' | '.join('---' for _ in dimensions)+' |'])
        for pid in section['paper_ids']:
            cells=[]
            for dimension in dimensions:
                cell=by_cell[(pid,dimension)]
                paragraphs=[]
                for cid in cell['claim_ids']:
                    claim=by_id[cid]
                    refs=['['+escape_markdown(ref)+']('+source_index['parts'][ref]['source_path']+')'
                          for ref in claim['evidence_refs']]
                    paragraphs.append(escape_markdown(claim['text'])+' （'+ '、'.join(refs)+'）')
                cells.append('<br><br>'.join(paragraphs))
                mapping.append({'section_id':sid,'paper_id':pid,'dimension':dimension,
                    'claim_ids':[sid+'/'+cid for cid in cell['claim_ids']]})
            lines.append('| '+escape_markdown(pid)+' | '+' | '.join(cells)+' |')
        lines.append('')
    return '\n'.join(lines).encode('utf-8'),{'schema':'review-comparison-projection/1','cells':mapping}


def _card_projection(bundle, renders):
    chunks,entries,offset=[],[],0
    for sid in bundle['materials']['review/scope']['section_ids']:
        section=bundle['materials']['section/'+quote(sid,safe='')]
        if section['kind']!='paper_card':
            continue
        text=renders[sid]['text']
        entries.append({'section_id':sid,'paper_id':section['paper_ids'][0],
            'start_char':offset,'end_char':offset+len(text),'text_sha256':renders[sid]['text_sha256']})
        chunks.append(text+'\n\n')
        offset+=len(text)+2
    return ''.join(chunks).encode('utf-8'),{'schema':'review-card-projection/1',
        'offset_unit':'Unicode code points in evidence-cards.md; end exclusive','cards':entries}


def _write(snapshot, output_path, *, receipt, publication_verified):
    # All validation and projections precede creation of any delivery directory.
    bundle = snapshot['bundle']
    renders = full = main = source_index = projection_error = None
    if bundle:
        try:
            renders, full, main = _renders(bundle)
            source_index = _source_index(bundle, renders)
        except (DeliveryError, KeyError, TypeError, ValueError) as exc:
            if publication_verified:
                raise
            renders = full = main = source_index = None
            projection_error = {'code': getattr(exc, 'code', 'INCOMPLETE_PROJECTION'), 'message': str(exc)}
    root = Path(output_path).expanduser().resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(exist_ok=False)
    files = {}

    def put(path, data):
        if path in files:
            if files[path]['sha256'] != sha256(data).hexdigest():
                raise DeliveryError('CONTENT_ADDRESS_COLLISION', 'Two values map to the same export file')
            return
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as handle:
            handle.write(data)
        files[path] = {'sha256': sha256(data).hexdigest(), 'size_bytes': len(data)}

    def put_json(path, value):
        put(path, canonical(value))

    put_json('proof/nodes.json', snapshot['nodes'])
    put_json('proof/submissions.json', snapshot['proof_submissions'])
    put_json('proof/supplemental-requirements.json', {
        'source_quote_witness_required':snapshot['source_quote_witness_required'],
        'semantic_entailment_proven_by_literal_matching':False})
    put_json('proof/runtime-identities.json', {
        'schema': 'runtime-identity-export/1',
        'trust': 'Host provenance snapshot; not authenticated and never automatically trusted from JSON',
        'identities': {key: _identity_data(identity) for key, identity in snapshot['identities'].items()}})
    put_json('proof/gate.json', receipt)
    if bundle:
        put_json('proof/plan.json', bundle.get('plan'))
        put_json('proof/task-specs.json', bundle.get('node_specs', {}))
        material_index = {}
        for mid, value in bundle.get('materials', {}).items():
            digest = payload_hash(value)
            binary = isinstance(value, bytes)
            path = ('sources/' + digest + '.md') if binary else ('materials/' + digest + '.json')
            put(path, value if binary else canonical(value))
            material_index[mid] = {'path': path, 'sha256': digest, 'kind': 'raw_bytes' if binary else 'canonical_json'}
        put_json('materials/index.json', material_index)
        put_json('bundle.json', {'schema': 'review-delivery-bundle/1',
            'root_section_ids': bundle.get('root_section_ids', []), 'root_node_id': bundle.get('root_node_id'),
            'paper_ids': bundle.get('paper_ids', []), 'question_ids': bundle.get('question_ids', []),
            'material_index': 'materials/index.json', 'plan': 'proof/plan.json',
            'nodes': 'proof/nodes.json', 'node_specs': 'proof/task-specs.json'})
    if renders is not None:
        prefix = '' if publication_verified else 'draft-'
        put(prefix + 'review.md', full['text'].encode('utf-8'))
        put_json(prefix + 'review-lines.json', {'schema': 'review-line-map/1', 'lines': full['lines'],
            'offset_unit': 'Unicode code points in the exact UTF-8 decoded review; end exclusive'})
        put(prefix + 'main-review.md', main['text'].encode('utf-8'))
        put_json(prefix + 'main-review-lines.json', {key: value for key, value in main.items() if key != 'text'})
        section_index = {}
        for sid, render in renders.items():
            path = 'sections/' + payload_hash(render['text'].encode('utf-8')) + '.md'
            put(path, render['text'].encode('utf-8'))
            section_index[sid] = {'path': path, 'text_sha256': render['text_sha256']}
        put_json('sections/index.json', section_index)
        put_json('source-spans.json', source_index)
        put('comparison-cells.csv', _comparison_csv(bundle))
        table,table_map=_comparison_markdown(bundle,source_index)
        put(prefix+'comparison-table.md',table)
        put_json(prefix+'comparison-table-map.json',table_map)
        cards,card_map=_card_projection(bundle,renders)
        put(prefix+'evidence-cards.md',cards)
        put_json(prefix+'evidence-cards-index.json',card_map)
        title='文獻回顧' if publication_verified else '未完成的文獻回顧'
        status='已完成獨立模型查核。' if publication_verified else '本目錄保留未通過完整查核的草稿。'
        readme='# '+title+'\n\n'+status+'\n\n'+ '\n'.join([
            '- [主報告]('+prefix+'main-review.md)',
            '- ['+str(len(card_map['cards']))+' 篇證據卡]('+prefix+'evidence-cards.md)',
            '- [比較表]('+prefix+'comparison-table.md)',
            '- [比較表資料](comparison-cells.csv)',
            '- [來源與引用定位](source-spans.json)',
            '- [完整章節]('+prefix+'review.md)'])+'\n'
        put('README.md',readme.encode('utf-8'))
    if not bundle or projection_error:
        put_json('partial-artifacts.json', {'records': snapshot['records'], 'sections': snapshot['sections']})
    if projection_error:
        put_json('projection-error.json', projection_error)
    # Re-read every file before the final acceptance manifest is written.
    for path, info in files.items():
        raw = (root / path).read_bytes()
        if len(raw) != info['size_bytes'] or sha256(raw).hexdigest() != info['sha256']:
            raise DeliveryError('EXPORT_BYTES_CHANGED', 'An export file changed before finalization')
    manifest = {'schema': 'literature-review-delivery/1',
        'status': 'publication_verified' if publication_verified else 'unpublished_attempt',
        'publication_verified': publication_verified, 'gate': receipt,
        'files': files, 'proof_method': 'independent_model_hierarchical_review',
        'limitations': ['Model attestations are not human review or proof of comprehension.',
                        'Hash checks detect changes relative to this bundle; the bundle is not digitally signed.'],
        'projections': {'review.md': 'Exact planned delivery text; no added citations or prose.',
                        'main-review.md': 'Exact root section texts in declared order.',
                        'evidence-cards.md': 'Exact reviewed card section texts, with source-bound offsets in the card index.',
                        'comparison-table.md': 'Mechanical table of the reviewed cell bindings and exact claim text; links resolve existing original sources.',
                        'comparison-cells.csv': 'Mechanical cell-to-reviewed-claim projection; no new scientific text.'}}
    # Last write: a partial directory can never carry a successful manifest.
    with (root / 'manifest.json').open('xb') as handle:
        handle.write(canonical(manifest))
    return {**manifest, 'output_path': str(root), 'manifest_path': str(root / 'manifest.json')}


def export_review(result, output_path):
    """Create a new portable directory only after a fresh native proof pass.

    Ignores the caller's cached ``gate``. Existing output paths are never
    overwritten. Exceptions leave no publication_verified acceptance manifest.
    """
    snapshot = _snapshot(result)
    receipt = _gate(snapshot)
    return _write(snapshot, output_path, receipt=receipt, publication_verified=True)


def save_review_attempt(result, output_path):
    """Persist failed/incomplete work without claiming verified publication.

    A partial result may have ``bundle=None``. Gate errors and real model
    verdicts are retained. This method never sets publication_verified=True.
    """
    snapshot = _snapshot(result)
    try:
        receipt = _gate(snapshot)
    except (ProofError, DeliveryError) as exc:
        receipt = {'status': 'rejected', 'error': {'code': exc.code, 'message': str(exc),
                   'details': getattr(exc, 'details', None)}}
    return _write(snapshot, output_path, receipt=receipt, publication_verified=False)
