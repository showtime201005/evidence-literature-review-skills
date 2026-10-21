"""Mapped report sections and comparison cells for hierarchical native reviews.

All scientific prose is a claim. Runtime derives line/claim inventories from
rendered content, rather than trusting a model's declaration of what was covered.
"""
from __future__ import annotations

from hashlib import sha256
import copy
import json
from collections import Counter
from typing import Literal
from pydantic import Field, ValidationError

from .scientific_records import StrictModel
from .task_store import canonical

CARD_MAX_CLAIMS = 12
CARD_MAX_TEXT_CHARACTERS = 3000


class DraftClaim(StrictModel):
    local_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    question_ids: list[str]
    attribution: Literal['source_finding','analyst_inference']
    scope: Literal['individual','subset','corpus']
    population_paper_ids: list[str] = Field(min_length=1)
    premise_claim_ids: list[str] = Field(default_factory=list)


class RetentionDisposition(StrictModel):
    obligation_id: str
    status: Literal['included','excluded']
    claim_ids: list[str]
    reason: str = Field(min_length=1)


class ComparisonCell(StrictModel):
    paper_id: str
    dimension: str
    claim_ids: list[str] = Field(min_length=1)


class DraftSubmission(StrictModel):
    claims: list[DraftClaim] = Field(min_length=1)
    retention: list[RetentionDisposition]
    cells: list[ComparisonCell]


def source_units(packets):
    units = {}
    for packet in packets:
        raw = b''.join(p['text'].encode('utf-8') for p in packet['parts'])
        if sha256(raw).hexdigest() != packet['source_sha256']:
            raise ValueError('Original source digest mismatch')
        for part in packet['parts']:
            key = packet['paper_id'] + '/' + part['part_id']
            if key in units:
                raise ValueError('Duplicate source unit IDs')
            if raw[part['start_byte']:part['end_byte']].decode('utf-8') != part['text']:
                raise ValueError('Source unit offset mismatch')
            units[key] = {'paper_id':packet['paper_id'], 'source_sha256':packet['source_sha256'],
                          'part_id':part['part_id'], 'start_byte':part['start_byte'],
                          'end_byte':part['end_byte'], 'text':part['text']}
    return units


def draft_packet(kind, packets, records, questions, *, dimensions=(), premises=(),include_reader_findings=False):
    if kind not in ('paper_card','comparison','synthesis'):
        raise ValueError('Unknown draft kind')
    papers = [p['paper_id'] for p in packets]
    if not papers or len(set(papers)) != len(papers):
        raise ValueError('Unique nonempty paper membership required')
    if kind == 'paper_card' and len(papers) != 1:
        raise ValueError('A paper card belongs to exactly one paper')
    units = source_units(packets)
    obligations = []
    reader_context=[]
    for record in records:
        if record['paper_id'] not in papers:
            raise ValueError('Record is outside the assigned corpus')
        matched = next(p for p in packets if p['paper_id']==record['paper_id'])
        if matched['source_sha256'] != record['source_sha256']:
            raise ValueError('Record source version changed')
        evidence = {e['id']:e for e in record.get('evidence',[])}
        if include_reader_findings:
            findings={f['local_id']:f for f in record['findings']}
            if len(findings)!=len(record['findings']):raise ValueError('Duplicate reader finding IDs')
            if any(o['finding_id'] not in findings for o in record['obligations']):
                raise ValueError('A retention obligation needs its actual complete reader finding')
            rows={}
            for fid,finding in findings.items():
                refs=[record['paper_id']+'/'+evidence[eid]['part_id'] for eid in finding['evidence_refs']]
                if not refs or not set(refs)<=set(units):raise ValueError('Reader finding is outside its actual source version')
                rows[fid]={'finding':copy.deepcopy(finding),'source_refs':list(dict.fromkeys(refs))}
            reader_context.append({'paper_id':record['paper_id'],'source_sha256':record['source_sha256'],
                'execution_id':record['execution_id'],'record_sha256':sha256(canonical(record)).hexdigest(),
                'findings':rows})
        for obligation in record['obligations']:
            refs = [record['paper_id']+'/'+evidence[ref]['part_id']
                    for ref in obligation.get('evidence_refs',[])]
            if not refs or not set(refs) <= set(units):
                raise ValueError('Every retained qualification needs original source units')
            obligations.append({**{k:v for k,v in obligation.items() if k!='evidence_refs'},
                                'reader_evidence_ids':list(obligation.get('evidence_refs',[])),
                                'source_refs':list(dict.fromkeys(refs))})
    ids = [o['id'] for o in obligations]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate retention obligations')
    result={'schema':'review-draft-packet/1', 'kind':kind, 'paper_ids':papers,
            'questions':questions, 'dimensions':list(dimensions),
            'sources':units, 'obligations':obligations, 'premises':list(premises)}
    if include_reader_findings:
        result.update(reader_context_profile='reader-finding-context/1',reader_findings=reader_context)
    return result


def premise_obligations(sections):
    """Derive each synthesis responsibility from actual direct premise prose.

    Original reader obligations remain independently checked at source leaves.
    This ledger does not certify their dispositions or replace that closure.
    """
    obligations, seen = [], set()
    for section in sections:
        for claim in section['claims']:
            premise_id = section['section_id'] + '/' + claim['local_id']
            if premise_id in seen:
                raise ValueError('Duplicate scientific premise claim')
            seen.add(premise_id)
            obligations.append({'id': 'premise/' + premise_id,
                'kind': 'premise_retention', 'premise_claim_id': premise_id,
                'text': claim['text'],
                'source_refs': list(dict.fromkeys(claim['evidence_refs'])),
                'question_ids': list(claim['question_ids']),
                'population_paper_ids': list(claim['population_paper_ids'])})
    if not obligations:
        raise ValueError('Synthesis requires actual scientific premise claims')
    return obligations


def inference_packet(sections, packets, records, questions, *, kind='synthesis', dimensions=()):
    """Bounded derived input: actual premises and source metadata, not raw corpus.

    Publication still requires the original-source proof closure; this function
    grants no scientific approval to the supplied premise sections.
    """
    if kind not in ('comparison', 'synthesis'):
        raise ValueError('Derived packets must be comparison or synthesis')
    if kind == 'comparison' and (not sections or any(s['kind'] != 'paper_card' for s in sections)):
        raise ValueError('Derived comparison requires actual paper-card premises')
    if kind == 'comparison':
        members=[p for s in sections for p in s['paper_ids']]
        if any(len(s['paper_ids']) != 1 for s in sections) or len(members) != len(set(members)):
            raise ValueError('Derived comparison requires exactly one card per paper')
    if {p for s in sections for p in s['paper_ids']} != {p['paper_id'] for p in packets}:
        raise ValueError('Derived premises must represent every and only assigned paper')
    result = draft_packet(kind,packets,records,questions,dimensions=dimensions,premises=sections)
    result['obligations'] = premise_obligations(sections)
    # Every scientific reference in an actual premise or retained qualification
    # stays available. Unreferenced part metadata is not scientific evidence;
    # complete original bytes remain in the independent source-proof closure.
    required = {ref for section in sections for claim in section['claims']
                for ref in claim['evidence_refs']}
    required.update(ref for obligation in result['obligations'] for ref in obligation['source_refs'])
    if not required <= set(result['sources']):
        raise ValueError('A scientific premise or retention obligation references a source outside the assigned corpus')
    result['sources'] = {key:{**{k:v for k,v in unit.items() if k!='text'},
                            'text_sha256':sha256(unit['text'].encode('utf-8')).hexdigest()}
                         for key,unit in result['sources'].items() if key in required}
    result['premises'] = [{'section_id':s['section_id'],'kind':s['kind'],'paper_ids':s['paper_ids'],
                          'claims':copy.deepcopy(s['claims']), 'retention':copy.deepcopy(s['retention'])}
                         for s in sections]
    return result


class DraftInventoryError(ValueError):
    """All actionable structural inventory gaps from one submission attempt."""
    code = 'DRAFT_INVENTORY_INCOMPLETE'

    def __init__(self, details):
        self.details = details
        super().__init__('Draft inventory problems (complete missing/unknown IDs): ' +
                         json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def _draft_submission(packet, value):
    """Collect independent inventory gaps before raising; never fill content."""
    schema_errors = []
    try:
        submission = DraftSubmission.model_validate(value)
    except ValidationError as exc:
        submission = None
        schema_errors = exc.errors(include_url=False, include_context=False, include_input=False)
    raw = value.model_dump() if isinstance(value, DraftSubmission) else value
    raw = raw if isinstance(raw, dict) else {}

    def rows(key):
        return [item for item in raw.get(key, []) if isinstance(item, dict)] if isinstance(raw.get(key), list) else []

    def strings(values):
        return [item for item in values if isinstance(item, str)] if isinstance(values, list) else []

    def differences(actual, expected):
        counts = Counter(actual)
        delta = {'missing': sorted(set(expected) - set(actual)),
                 'unknown': sorted(set(actual) - set(expected)),
                 'duplicates': sorted(key for key, n in counts.items() if n > 1)}
        return {key: items for key, items in delta.items() if items}

    claims, retention, cells = rows('claims'), rows('retention'), rows('cells')
    claim_ids = strings([c.get('local_id') for c in claims])
    questions = {q.get('id', q.get('question_id')) for q in packet['questions']}
    # A question may be answered by multiple claims. Only coverage, not overlap,
    # is constrained here; per-claim duplicate question IDs remain compatible.
    supplied_questions = {qid for c in claims for qid in strings(c.get('question_ids'))}
    details = {}
    if packet['kind'] == 'paper_card':
        text_characters=sum(len(c.get('text','')) for c in claims if isinstance(c.get('text'),str))
        if len(claims)>CARD_MAX_CLAIMS or text_characters>CARD_MAX_TEXT_CHARACTERS:
            details['card_size']={'claims':len(claims),'maximum_claims':CARD_MAX_CLAIMS,
                'text_characters':text_characters,'maximum_text_characters':CARD_MAX_TEXT_CHARACTERS,
                'correction':'Rewrite the complete concise card; retain material results, uncertainty, counterevidence and applicability. Do not truncate. Explain exclusions in retention.'}
    question_delta = {'missing': sorted(questions - supplied_questions),
                      'unknown': sorted(supplied_questions - questions)}
    if any(question_delta.values()):
        details['questions'] = {k: v for k, v in question_delta.items() if v}
    retention_delta = differences(strings([r.get('obligation_id') for r in retention]),
                                  [o['id'] for o in packet['obligations']])
    if retention_delta:
        details['retention'] = retention_delta
    expected_cells = {(p, d) for p in packet['paper_ids'] for d in packet['dimensions']} if packet['kind'] == 'comparison' else set()
    actual_cells = [(c.get('paper_id'), c.get('dimension')) for c in cells
                    if isinstance(c.get('paper_id'), str) and isinstance(c.get('dimension'), str)]
    cell_delta = differences(actual_cells, expected_cells)
    if cell_delta:
        details['cells'] = cell_delta
    duplicate_claims = sorted(cid for cid, n in Counter(claim_ids).items() if n > 1)
    if duplicate_claims:
        details['duplicate_claim_ids'] = duplicate_claims
    unknown_refs = []
    for key, items, id_key in (('retention', retention, 'obligation_id'), ('cells', cells, 'paper_id')):
        for item in items:
            unknown = set(strings(item.get('claim_ids'))) - set(claim_ids)
            if unknown:
                unknown_refs.append({'inventory': key, 'id': item.get(id_key), 'unknown_claim_ids': sorted(unknown)})
    if unknown_refs:
        details['unknown_claim_references'] = unknown_refs
    invalid_sources = [{'claim_id': c.get('local_id'),
        'unknown': sorted(set(strings(c.get('evidence_refs'))) - set(packet['sources']))}
        for c in claims if set(strings(c.get('evidence_refs'))) - set(packet['sources'])]
    if invalid_sources:
        details['source_references'] = {'invalid': invalid_sources,
            'required_format': 'Use exact paper_id/part_id source locators, never reader evidence IDs.',
            'allowed': sorted(packet['sources'])}
    if schema_errors:
        details['schema_errors'] = schema_errors
    if details:
        raise DraftInventoryError(details)
    return submission


def validate_draft(packet, value, *, execution_id):
    if not execution_id:
        raise ValueError('Runtime writer identity required')
    submission = _draft_submission(packet, value)
    ids = [c.local_id for c in submission.claims]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate claim IDs')
    questions = {q.get('id',q.get('question_id')) for q in packet['questions']}
    premises = {s['section_id']+'/'+c['local_id']:c for s in packet['premises'] for c in s['claims']}
    for claim in submission.claims:
        if not set(claim.evidence_refs) <= set(packet['sources']):
            raise ValueError(f'{claim.local_id}: source reference outside the assigned version')
        if not set(claim.question_ids) <= questions:
            raise ValueError('Unknown research question')
        population = set(claim.population_paper_ids)
        if len(population)!=len(claim.population_paper_ids) or not population <= set(packet['paper_ids']):
            raise ValueError('Claim population has duplicate or unknown members')
        if claim.scope=='individual' and len(population)!=1:
            raise ValueError('Individual claim must declare exactly one paper')
        if claim.scope=='corpus' and population!=set(packet['paper_ids']):
            raise ValueError('Corpus-wide statement must declare the entire assigned membership')
        supported_members = {packet['sources'][ref]['paper_id'] for ref in claim.evidence_refs}
        if not population <= supported_members:
            raise ValueError('Every member of the declared claim population requires source evidence')
        if not set(claim.premise_claim_ids) <= set(premises):
            raise ValueError('Unknown scientific premise')
        if packet['premises'] and not claim.premise_claim_ids:
            raise ValueError('Hierarchical synthesis must identify its actual scientific premises')
        if packet['premises']:
            inherited = {r for cid in claim.premise_claim_ids for r in premises[cid]['evidence_refs']}
            if not set(claim.evidence_refs) <= inherited:
                raise ValueError('Synthesis cannot introduce source evidence outside its declared premises')
            inherited_population = {p for cid in claim.premise_claim_ids
                                    for p in premises[cid]['population_paper_ids']}
            if not population <= inherited_population:
                raise ValueError('Synthesis population exceeds its declared scientific premises')
        # Renderer owns layout and citations; scientific headings cannot bypass
        # the claim inventory by hiding in Markdown/HTML supplied by the writer.
        if '\n' in claim.text or '\r' in claim.text:
            raise ValueError('Write one plain paragraph per claim, without line breaks')
    if {q for c in submission.claims for q in c.question_ids} != questions:
        raise ValueError('Every assigned research question needs an explicit delivered answer or scoped unresolved statement')
    obligations_by_id = {o['id']: o for o in packet['obligations']}
    required = set(obligations_by_id)
    retained = [r.obligation_id for r in submission.retention]
    if set(retained) != required or len(retained) != len(required):
        raise ValueError('Every retention obligation requires exactly one disposition')
    for item in submission.retention:
        if not set(item.claim_ids) <= set(ids):
            raise ValueError('Retention references unknown claims')
        if item.status == 'included' and not item.claim_ids:
            raise ValueError('Included obligation needs actual delivered claims')
        if item.status == 'excluded' and item.claim_ids:
            raise ValueError('Excluded obligation cannot claim delivered coverage')
        obligation = obligations_by_id[item.obligation_id]
        premise_id = obligation.get('premise_claim_id')
        if premise_id and item.status == 'included' and not any(
                premise_id in claim.premise_claim_ids
                for claim in submission.claims if claim.local_id in item.claim_ids):
            raise ValueError('Included premise obligation must bind a claim that uses that actual premise')
    expected = {(p,d) for p in packet['paper_ids'] for d in packet['dimensions']} if packet['kind']=='comparison' else set()
    cells = [(c.paper_id,c.dimension) for c in submission.cells]
    if set(cells) != expected or len(cells) != len(expected):
        raise ValueError('Comparison cells must cover exactly every assigned paper/dimension')
    if any(not set(c.claim_ids) <= set(ids) for c in submission.cells):
        raise ValueError('Comparison cell references unknown claims')
    by_id = {c.local_id:c for c in submission.claims}
    for cell in submission.cells:
        if not any(packet['sources'][ref]['paper_id']==cell.paper_id
                   for cid in cell.claim_ids for ref in by_id[cid].evidence_refs):
            raise ValueError('Every comparison cell must bind its own paper source')
    paper_coverage = {packet['sources'][ref]['paper_id'] for c in submission.claims for ref in c.evidence_refs}
    if paper_coverage != set(packet['paper_ids']):
        raise ValueError('Every assigned paper needs actual source-linked representation')
    payload = {'schema':'review-section/1','kind':packet['kind'], 'paper_ids':packet['paper_ids'],
               'question_ids':sorted(questions),'dimensions':list(packet['dimensions']),
               'obligations':copy.deepcopy(packet['obligations']),
               'premise_section_ids':[s['section_id'] for s in packet['premises']],
               'source_versions':{u['paper_id']:u['source_sha256'] for u in packet['sources'].values()},
               'writer_execution_id':execution_id, 'packet_sha256':sha256(canonical(packet)).hexdigest(),
               'verification_status':'unverified', **submission.model_dump()}
    if 'reader_context_profile' in packet:
        if packet['reader_context_profile']!='reader-finding-context/1' or not packet.get('reader_findings'):
            raise ValueError('Unknown or missing reader finding context')
        payload['reader_context_profile']=packet['reader_context_profile']
    payload['section_id'] = 's_' + sha256(canonical(payload)).hexdigest()[:24]
    return payload


def escape_markdown(text):
    # Preserve visible scientific text while preventing injected headings,
    # images, links or raw HTML from escaping the mapped claim paragraph.
    for char in ('\\','`','*','_','{','}','[',']','<','>','#','|','!'):
        text = text.replace(char,'\\'+char)
    return text


def render_section(section):
    labels = {'paper_card':'論文證據卡','comparison':'研究比較','synthesis':'綜整'}
    title = labels[section['kind']]
    if section['kind']=='paper_card':
        title += '：' + escape_markdown(section['paper_ids'][0])
    lines = ['## ' + title, '']
    inventory, claims = [], {}
    offset = len('\n'.join(lines)) + 1
    for claim in section['claims']:
        global_id = section['section_id'] + '/' + claim['local_id']
        # Tokens are rendered from actual bound source IDs, never a model's
        # invented bibliography. Portable delivery resolves them to sources.
        refs = ' '.join('[來源 ' + escape_markdown(ref) + ']' for ref in claim['evidence_refs'])
        line = escape_markdown(claim['text']) + ' ' + refs
        line_id = section['section_id'] + '/line/' + str(len(lines)+1)
        inventory.append({'id':line_id,'start_char':offset,'end_char':offset+len(line),
                          'text':line,'claim_ids':[global_id]})
        claims[global_id] = claim
        lines.extend([line,''])
        offset += len(line) + 2
    text = '\n'.join(lines)
    # Include even neutral headings in scan coverage so no factual heading can
    # escape the independent full-line scan.
    inventory.insert(0,{'id':section['section_id']+'/line/1','start_char':0,
                        'end_char':len(lines[0]),'text':lines[0],'claim_ids':[]})
    for item in inventory:
        if text[item['start_char']:item['end_char']] != item['text']:
            raise AssertionError('Rendered line mapping mismatch')
    return {'schema':'review-section-render/1','section_id':section['section_id'],
            'text':text,'text_sha256':sha256(text.encode('utf-8')).hexdigest(),
            'claims':claims,'lines':inventory}
