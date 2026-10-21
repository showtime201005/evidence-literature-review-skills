"""Independent whole-paper support and omission review for scientific records."""
from __future__ import annotations

from typing import Literal
from pydantic import Field
from .scientific_records import StrictModel
from .task_store import canonical
from hashlib import sha256
import copy


def record_projection(packet, record):
    """Lossless omission of quote copies already present in the original source."""
    view = copy.deepcopy(record)
    for evidence in view['evidence']:
        evidence.pop('quote')
    result = {'encoding':'scientific-record-source-spans/1',
              'record_sha256':sha256(canonical(record)).hexdigest(), 'record':view}
    if canonical(restore_record(packet, result)) != canonical(record):
        raise ValueError('Record projection failed exact roundtrip')
    return result


def restore_record(packet, projection):
    if projection['encoding'] != 'scientific-record-source-spans/1':
        raise ValueError('Unknown record projection encoding')
    raw = b''.join(p['text'].encode('utf-8') for p in packet['parts'])
    if sha256(raw).hexdigest() != packet['source_sha256']:
        raise ValueError('Original source bytes changed')
    record = copy.deepcopy(projection['record'])
    for evidence in record['evidence']:
        begin, end = evidence['start_byte'], evidence['end_byte']
        if not 0 <= begin < end <= len(raw) or evidence['source_sha256'] != packet['source_sha256']:
            raise ValueError('Invalid source span binding')
        evidence['quote'] = raw[begin:end].decode('utf-8')
    if sha256(canonical(record)).hexdigest() != projection['record_sha256']:
        raise ValueError('Reconstructed record hash mismatch')
    return record


class FindingVerdict(StrictModel):
    finding_id: str
    status: Literal['supported','partially_supported','unsupported','contradicted','uncertain']
    reason: str = Field(min_length=1)


class ReviewIssue(StrictModel):
    kind: Literal['source_support','important_omission','question_coverage','incorrect_condition','missing_obligation']
    finding_ids: list[str]
    part_ids: list[str] = Field(min_length=1)
    description: str = Field(min_length=1)
    required_correction: str = Field(min_length=1)


class RecordReviewSubmission(StrictModel):
    verdicts: list[FindingVerdict]
    checked_part_ids: list[str]
    question_ids: list[str]
    omission_check: Literal['passed','needs_revision','unresolved']
    omission_reason: str = Field(min_length=1)
    issues: list[ReviewIssue]


class RecordReviewFailure(ValueError):
    code = 'VERIFICATION_ISSUES'

    def __init__(self, review):
        super().__init__('Independent record review requires revision; retain verdict and issue artifact')
        self.review = review


def validate_record_review(packet, record, value, *, execution_id):
    if not execution_id or execution_id == record['execution_id']:
        raise ValueError('Independent runtime execution identity required')
    if packet['paper_id'] != record['paper_id'] or packet['source_sha256'] != record['source_sha256']:
        raise ValueError('Review source version mismatch')
    submission = RecordReviewSubmission.model_validate(value)
    findings = {v['local_id'] for v in record['findings']}
    ids = [v.finding_id for v in submission.verdicts]
    if set(ids) != findings or len(ids) != len(findings):
        raise ValueError('Exactly one verdict required for every finding')
    parts = {p['part_id'] for p in packet['parts']}
    if set(submission.checked_part_ids) != parts or len(submission.checked_part_ids) != len(parts):
        raise ValueError('Independent omission review must cover the whole source')
    questions = {q['id'] for q in packet['questions']}
    if set(submission.question_ids) != questions or len(submission.question_ids) != len(questions):
        raise ValueError('Every research question must be checked')
    for issue in submission.issues:
        if not set(issue.finding_ids) <= findings or not set(issue.part_ids) <= parts:
            raise ValueError('Issue references unknown findings or source parts')
    passed = all(v.status=='supported' for v in submission.verdicts) and submission.omission_check=='passed' and not submission.issues
    review = {'schema':'scientific-record-review/1','paper_id':record['paper_id'],
              'source_sha256':record['source_sha256'],'record_sha256':sha256(canonical(record)).hexdigest(),
              'writer_execution_id':record['execution_id'],'execution_id':execution_id,
              'status':'passed' if passed else 'needs_revision', **submission.model_dump()}
    if not passed:
        raise RecordReviewFailure(review)
    return review
