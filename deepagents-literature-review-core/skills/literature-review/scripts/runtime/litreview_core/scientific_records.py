"""Versioned full-source reader handoff with exact evidence and obligations.

Structural validation is not semantic approval. A fresh verifier must inspect
both the original paper and this record to check correctness and omissions.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .task_store import canonical


FIELDS = ('research_question', 'contributions', 'method', 'evaluation', 'results',
          'limitations', 'conditions', 'relevance', 'unexpected_findings')
FieldName = Literal['research_question', 'contributions', 'method', 'evaluation',
                    'results', 'limitations', 'conditions', 'relevance', 'unexpected_findings']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SourceQuote(StrictModel):
    part_id: str
    quote: str | None = Field(default=None, min_length=1,
        description='Prefer null to bind the complete original part without copying it. Optional exact substring only.')
    # Character offset within the original part, only needed for repeated quotes.
    start_char: int | None = Field(default=None, ge=0)


class Finding(StrictModel):
    local_id: str = Field(min_length=1)
    field: FieldName
    text: str = Field(min_length=1)
    attribution: Literal['author_result', 'author_limitation', 'secondary_report', 'context', 'analyst_inference']
    evidence: list[SourceQuote] = Field(min_length=1)
    obligations: list[Literal['adverse_result', 'null_result', 'persistent_failure',
                              'missing_measurement', 'critical_limitation', 'applicability']] = Field(
        description='Required assessment: list all applicable retention categories; use [] only when none apply.')


class Observation(StrictModel):
    part_id: str
    note: str = Field(min_length=1)


class QuestionDisposition(StrictModel):
    question_id: str
    status: Literal['addressed', 'partially_addressed', 'not_addressed', 'unresolved']
    reason: str = Field(min_length=1)
    support: list[str]
    counterevidence: list[str]


class FieldAssessment(StrictModel):
    field: FieldName
    status: Literal['extracted', 'not_reported', 'not_applicable', 'unresolved']
    reason: str = Field(min_length=1)


class ReaderSubmission(StrictModel):
    observations: list[Observation]
    findings: list[Finding]
    fields: list[FieldAssessment]
    questions: list[QuestionDisposition]


def source_packet(paper_id: str, raw: bytes, questions: list[dict]):
    """Preserve exact UTF-8 source bytes; split only at blank-line boundaries.

    Whole paper is one assigned input; oversized papers require future bounded
    packet planning, never silent slicing or preview delivery.
    """
    if not isinstance(paper_id,str) or not paper_id.strip() or any(ord(c)<32 or c=='/' for c in paper_id):
        raise ValueError('Paper ID must be nonempty and contain no controls or slash')
    text = raw.decode('utf-8')
    if not text.strip():
        raise ValueError('Empty paper')
    questions = [{**q, 'id': q.get('id', q.get('question_id'))} for q in questions]
    ids = [q['id'] for q in questions]
    if not ids or any(not q for q in ids) or len(ids) != len(set(ids)):
        raise ValueError('Unique research question IDs required')
    boundaries = [0] + [m.end() for m in re.finditer(r'\r?\n[ \t]*\r?\n', text)]
    if boundaries[-1] != len(text):
        boundaries.append(len(text))
    parts = []
    byte_start = 0
    for start, end in zip(boundaries, boundaries[1:]):
        value = text[start:end]
        size = len(value.encode('utf-8'))
        parts.append({'part_id': f'p{len(parts)+1:04}', 'text': value,
                      'start_byte': byte_start, 'end_byte': byte_start+size})
        byte_start += size
    assert b''.join(p['text'].encode('utf-8') for p in parts) == raw
    return {'schema': 'scientific-source/1', 'paper_id': paper_id,
            'source_sha256': sha256(raw).hexdigest(), 'parts': parts, 'questions': questions}


def validate_reader(packet, value, *, execution_id):
    if not execution_id:
        raise ValueError('Runtime execution identity required')
    raw = b''
    for part in packet['parts']:
        block = part['text'].encode('utf-8')
        if part['start_byte'] != len(raw) or part['end_byte'] != len(raw)+len(block):
            raise ValueError('Noncontiguous original source parts')
        raw += block
    if sha256(raw).hexdigest() != packet['source_sha256']:
        raise ValueError('Original source hash mismatch')
    submission = ReaderSubmission.model_validate(value)
    parts = {p['part_id']: p for p in packet['parts']}
    if len(parts) != len(packet['parts']):
        raise ValueError('Duplicate source part IDs')
    observed = [p.part_id for p in submission.observations]
    if len(observed) != len(set(observed)) or set(observed) != set(parts):
        raise ValueError('Every original source part needs exactly one reading observation')
    ids = [f.local_id for f in submission.findings]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate finding IDs')
    assessed = [a.field for a in submission.fields]
    if len(assessed) != len(set(assessed)) or set(assessed) != set(FIELDS):
        raise ValueError('All nine extraction fields require assessments')
    field_counts = Counter(f.field for f in submission.findings)
    conflicts = []
    for assessment in submission.fields:
        count = field_counts[assessment.field]
        if bool(count) != (assessment.status == 'extracted'):
            conflicts.append({'field':assessment.field, 'status':assessment.status,
                'finding_count':count,
                'finding_ids':[f.local_id for f in submission.findings if f.field==assessment.field],
                'expected_status':['extracted'] if count else ['not_reported','not_applicable','unresolved']})
    if conflicts:
        raise ValueError('Field status contradicts extracted findings: '+
                         json.dumps(conflicts, ensure_ascii=False, separators=(',',':')))
    questions = [q.question_id for q in submission.questions]
    if len(questions) != len(set(questions)) or set(questions) != {q['id'] for q in packet['questions']}:
        raise ValueError('Every research question requires one disposition')
    for question in submission.questions:
        if not set(question.support + question.counterevidence) <= set(ids):
            raise ValueError('Unknown finding reference')
        if question.status == 'addressed' and not (question.support or question.counterevidence):
            raise ValueError('Addressed question needs source-linked findings')
    evidence, findings, obligations = [], [], []
    for finding in submission.findings:
        refs = []
        for quote in finding.evidence:
            part = parts.get(quote.part_id)
            if part is None:
                raise ValueError('Unknown source part')
            text = part['text']
            selected_quote = quote.quote if quote.quote is not None else text
            start = quote.start_char if quote.quote is not None else 0
            if start is None:
                start = text.find(selected_quote)
                if start < 0 or text.find(selected_quote, start+1) >= 0:
                    raise ValueError(f'{finding.local_id}/{quote.part_id}: quote absent or ambiguous. '
                        'Select the correct part_id with quote=null to bind the full source part, '
                        'or copy an exact unique substring. Recheck whether this part supports the assertion.')
            if text[start:start+len(selected_quote)] != selected_quote:
                raise ValueError(f'{finding.local_id}/{quote.part_id}: quote does not match original source at offset {start}')
            begin = part['start_byte'] + len(text[:start].encode('utf-8'))
            item = {'paper_id': packet['paper_id'], 'source_sha256': packet['source_sha256'],
                    'part_id': quote.part_id, 'start_byte': begin,
                    'end_byte': begin + len(selected_quote.encode('utf-8')), 'quote': selected_quote}
            eid = 'e_' + sha256(canonical(item)).hexdigest()[:24]
            if not any(e['id'] == eid for e in evidence):
                evidence.append({'id': eid, **item})
            refs.append(eid)
        item = finding.model_dump(exclude={'evidence'})
        item['evidence_refs'] = refs
        findings.append(item)
        # Structural retention, not host interpretation of scientific importance.
        # Even an omitted model flag must not silently drop an extracted caveat.
        retained = set(finding.obligations)
        if finding.field in ('limitations', 'conditions', 'unexpected_findings'):
            retained.add('extracted_' + finding.field)
        if any(finding.local_id in q.counterevidence for q in submission.questions):
            retained.add('question_counterevidence')
        for obligation in sorted(retained):
            obligations.append({'id': packet['paper_id'] + ':' + finding.local_id + ':' + obligation,
                                'kind': obligation, 'finding_id': finding.local_id,
                                'evidence_refs': refs})
    return {'schema': 'scientific-record/1', 'paper_id': packet['paper_id'],
            'source_sha256': packet['source_sha256'], 'execution_id': execution_id,
            'verification_status': 'unverified', 'observations': [o.model_dump() for o in submission.observations],
            'fields': [a.model_dump() for a in submission.fields],
            'questions': [q.model_dump() for q in submission.questions],
            'findings': findings, 'evidence': evidence, 'obligations': obligations}
