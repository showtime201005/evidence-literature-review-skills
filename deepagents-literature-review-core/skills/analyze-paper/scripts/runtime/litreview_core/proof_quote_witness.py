"""Experimental literal quote witnesses; deliberately not wired into workers.

Claim clause start_char/end_char are zero-based half-open Python Unicode
code-point indices in the exact claim text (not UTF-16 units or UTF-8 bytes).
Witness start_byte/end_byte are zero-based half-open absolute UTF-8 byte offsets
in the entire original source, bounded by that declared part's locator.

The caller supplies a runtime-owned canonical node_payload, before responsibility
aliases. Decode model responsibility aliases before calling this module. Original
versions are bound by material hashes and locator source_sha256; the model does
not repeat source hashes. A trusted plan may additionally supply expected hashes.

Successful literal validation proves exact strings/coordinates, NOT entailment,
scientific correctness, full-source reading or publication approval. Valid and
invalid scientific negatives are preserved for a future caller to terminate;
this module never requests a model retry or manufactures a proof/identity.
"""
from __future__ import annotations

from collections import Counter
import copy
import json
from typing import Literal

from pydantic import Field, StrictInt, StrictStr, ValidationError

from .hierarchical_proof import DIMENSIONS, payload_hash
from .proof_citation_view import build_citation_view
from .scientific_records import StrictModel


NEGATIVE_RELATIONS = {'topic_only', 'not_reported', 'contradicted', 'unresolved'}
NEGATIVE_VERDICTS = {'needs_revision', 'unresolved'}


class QuoteWitness(StrictModel):
    ref: StrictStr = Field(min_length=1)
    start_byte: StrictInt = Field(ge=0, description='Absolute zero-based UTF-8 source byte offset, inclusive')
    end_byte: StrictInt = Field(gt=0, description='Absolute zero-based UTF-8 source byte offset, exclusive')
    quote: StrictStr = Field(min_length=1, description='Exact unnormalized original UTF-8 substring')


class ClauseCheck(StrictModel):
    start_char: StrictInt = Field(ge=0, description='Zero-based Unicode code-point index in actual claim, inclusive')
    end_char: StrictInt = Field(gt=0, description='Zero-based Unicode code-point index in actual claim, exclusive')
    clause: StrictStr = Field(min_length=1)
    relation: Literal['explicit_support', 'topic_only', 'not_reported', 'contradicted', 'unresolved']
    witnesses: list[QuoteWitness]
    reason: StrictStr = Field(min_length=1)


class UnitWitnessVerdict(StrictModel):
    unit_id: StrictStr = Field(min_length=1)
    verdict: Literal['passed', 'needs_revision', 'unresolved']
    reason: StrictStr = Field(min_length=1)
    clause_checks: list[ClauseCheck] | None = Field(default=None,
        description='Required nonempty for assigned source claims; absent/empty for other responsibility units')


class WitnessIssue(StrictModel):
    unit_ids: list[StrictStr] = Field(min_length=1)
    description: StrictStr = Field(min_length=1)
    correction: StrictStr = Field(min_length=1)


class SourceWitnessSubmission(StrictModel):
    checked: dict[StrictStr, list[StrictStr]]
    verdicts: list[UnitWitnessVerdict]
    status: Literal['passed', 'needs_revision', 'unresolved']
    reason: StrictStr = Field(min_length=1)
    issues: list[WitnessIssue]


def semantic_negative_detected(value):
    """Conservatively inspect known structured positions before schema checks.

    Reasons are not interpreted by keyword. A malformed witness must not hide a
    negative status/verdict/relation/issue and permit a retry into a passed result.
    """
    # The only nested envelope followed is the documented tool ``data`` field.
    # A complete JSON-string object is inspected structurally, never by searching
    # free-form reasons for negative words. Invalid scalar text stays unknown.
    pending, seen = [(value,0)], {}
    while pending:
        current,depth = pending.pop()
        if depth > 8:
            continue
        if isinstance(current,str):
            try:
                decoded=json.loads(current)
            except (ValueError,TypeError,RecursionError):
                continue
            if isinstance(decoded,dict):
                pending.append((decoded,depth+1))
            continue
        if not isinstance(current,dict) or id(current) in seen:
            continue
        seen[id(current)]=current  # retain parsed objects so IDs cannot be reused
        if isinstance(current.get('status'),str) and current['status'] in NEGATIVE_VERDICTS:
            return True
        if isinstance(current.get('issues'),(list,dict)) and current['issues']:
            return True
        if isinstance(current.get('data'),(dict,str)):
            pending.append((current['data'],depth+1))
        verdicts=current.get('verdicts',[])
        if isinstance(verdicts,dict):
            verdicts=[verdicts]  # malformed singleton still cannot hide a negative
        if not isinstance(verdicts,list):
            continue
        for verdict in verdicts:
            if not isinstance(verdict,dict):
                continue
            if isinstance(verdict.get('verdict'),str) and verdict['verdict'] in NEGATIVE_VERDICTS:
                return True
            checks=verdict.get('clause_checks',[])
            if isinstance(checks,dict):
                checks=[checks]
            if isinstance(checks,list) and any(isinstance(clause,dict)
                    and isinstance(clause.get('relation'),str)
                    and clause['relation'] in NEGATIVE_RELATIONS for clause in checks):
                return True
    return False


class WitnessValidationError(ValueError):
    """Caller can retain the raw negative and terminate rather than retry it."""
    def __init__(self, code, message, original_submission, details=None):
        super().__init__(message)
        self.code, self.details = code, details
        self.original_submission = copy.deepcopy(original_submission)
        self.semantic_negative_detected = semantic_negative_detected(original_submission)

    def as_dict(self):
        return {'code': self.code, 'message': str(self), 'details': copy.deepcopy(self.details),
                'semantic_negative_detected': self.semantic_negative_detected,
                'original_submission': copy.deepcopy(self.original_submission)}


def validate_source_witness_submission(packet, value, *, expected_material_hashes=None):
    """Return full witness data AND the unchanged existing proof submission shape.

    ``proof_submission`` preserves every unit/verdict/reason/issue and only
    separates the supplemental clause_checks. It still needs the existing native
    proof gate; this function seals no proof and assigns no producer identity.
    Any raised error retains a deep raw snapshot and a semantic-negative flag.
    """
    original = copy.deepcopy(value)

    def reject(code, message, details=None):
        raise WitnessValidationError(code, message, original, details)

    if not isinstance(packet, dict) or packet.get('schema') != 'hierarchical-proof-task/1' or packet.get('kind') != 'source':
        reject('WITNESS_UNSUPPORTED_SCOPE', 'Quote witnesses require an actual source node with original material')
    if 'responsibility_encoding' in packet:
        reject('WITNESS_NONCANONICAL_INPUT', 'Use canonical packet coverage and decode output responsibility aliases first')
    if expected_material_hashes is not None and expected_material_hashes != packet.get('material_hashes'):
        reject('WITNESS_INPUT_BINDING_MISMATCH', 'Delivered material hashes differ from the trusted expected plan')
    coverage = packet.get('coverage')
    if (not isinstance(coverage, dict) or set(coverage) != set(DIMENSIONS)
            or any(not isinstance(ids, list) or any(not isinstance(uid, str) or not uid for uid in ids)
                   or len(ids) != len(set(ids)) for ids in coverage.values())):
        reject('WITNESS_INVALID_COVERAGE', 'Canonical packet requires all six unique responsibility inventories')
    try:
        view = build_citation_view(packet)
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
        reject('WITNESS_SOURCE_CONTEXT_INVALID', 'Original source/locator/version cannot be reconstructed', str(exc))
    if not isinstance(value, dict):
        reject('WITNESS_SCHEMA_INVALID', 'Witness submission must be a JSON object')
    try:
        submission = SourceWitnessSubmission.model_validate(value)
    except ValidationError as exc:
        reject('WITNESS_SCHEMA_INVALID', 'Witness submission schema is invalid', exc.errors(include_input=False, include_url=False))
    data = submission.model_dump(exclude_none=True)
    if not submission.reason.strip() or any(not verdict.reason.strip() for verdict in submission.verdicts):
        reject('WITNESS_EMPTY_REASON', 'Every unit and the whole submission need nonblank reasons')
    if set(submission.checked) != set(DIMENSIONS):
        reject('WITNESS_CHECKED_MISMATCH', 'Declare all six checked dimensions')
    for dim in DIMENSIONS:
        ids = submission.checked[dim]
        if len(ids) != len(set(ids)) or set(ids) != set(coverage[dim]):
            reject('WITNESS_CHECKED_MISMATCH', 'Checked IDs differ from assigned coverage', {'dimension': dim})
    required = set(coverage['claims']) | set(coverage['obligations'])
    allowed = {uid for dim in DIMENSIONS for uid in coverage[dim]}
    ids = [verdict.unit_id for verdict in submission.verdicts]
    counts = Counter(ids)
    inventory = {'missing': sorted(required-set(ids)), 'unknown': sorted(set(ids)-allowed),
                 'duplicates': sorted(uid for uid,count in counts.items() if count > 1)}
    if any(inventory.values()):
        reject('WITNESS_VERDICT_INVENTORY', 'Every assigned claim/obligation needs its own verdict; optional verdicts must be assigned', inventory)
    issue_ids = allowed | set(packet['material_hashes'])
    for issue in submission.issues:
        if (not set(issue.unit_ids) <= issue_ids or len(issue.unit_ids) != len(set(issue.unit_ids))
                or not issue.description.strip() or not issue.correction.strip()):
            reject('WITNESS_INVALID_ISSUE', 'Issues must name real units/materials and preserve nonblank descriptions/corrections')
    rows = {row['claim_id']: row for row in view['claim_rows']}
    sources, witness_count, clause_count = {}, 0, 0
    for verdict in submission.verdicts:
        clauses = verdict.clause_checks
        if verdict.unit_id not in set(coverage['claims']):
            if clauses:
                reject('WITNESS_CLAUSES_WRONG_SCOPE', 'Clause witnesses apply only to assigned source claims', verdict.unit_id)
            continue
        row = rows.get(verdict.unit_id)
        if not row or row['availability'] != 'delivered_claim' or not row['text'].strip():
            reject('WITNESS_MISSING_CLAIM_CONTEXT', 'Assigned actual claim text is missing', verdict.unit_id)
        if not clauses:
            reject('WITNESS_MISSING_CLAUSES', 'Every assigned source claim needs nonempty full-text clause checks', verdict.unit_id)
        text = row['text']
        declared = {part['ref']: part for part in row['declared_parts']}
        if any(part['availability'] != 'delivered_exact_part' for part in declared.values()):
            reject('WITNESS_ORIGINAL_NOT_DELIVERED', 'Original bytes and declared part are required for a source quote', verdict.unit_id)
        intervals = []
        for clause in clauses:
            clause_count += 1
            start, end = clause.start_char, clause.end_char
            if end <= start or end > len(text) or text[start:end] != clause.clause:
                reject('WITNESS_CLAUSE_TEXT_MISMATCH', 'Clause coordinates/text differ from actual Unicode claim',
                       {'unit_id': verdict.unit_id, 'start_char': start, 'end_char': end})
            if not clause.clause.strip() or not clause.reason.strip():
                reject('WITNESS_EMPTY_CLAUSE', 'Clause text and reason must contain nonblank content', verdict.unit_id)
            intervals.append((start,end))
            if clause.relation == 'explicit_support' and not clause.witnesses:
                reject('WITNESS_EXPLICIT_WITHOUT_QUOTE', 'Explicit support requires at least one exact declared-ref quote', verdict.unit_id)
            if verdict.verdict == 'passed' and clause.relation != 'explicit_support':
                reject('WITNESS_PASSED_CONTRADICTS_CLAUSE', 'A passed claim cannot contain a negative/unresolved clause', verdict.unit_id)
            seen_quotes = set()
            for witness in clause.witnesses:
                witness_count += 1
                part = declared.get(witness.ref)
                if part is None:
                    reject('WITNESS_UNDECLARED_REF', 'Quote names a locator not declared by this claim',
                           {'unit_id': verdict.unit_id, 'ref': witness.ref})
                if (witness.end_byte <= witness.start_byte or witness.start_byte < part['start_byte']
                        or witness.end_byte > part['end_byte']):
                    reject('WITNESS_BYTE_RANGE', 'Quote escapes its declared original part',
                           {'ref': witness.ref, 'start_byte': witness.start_byte, 'end_byte': witness.end_byte})
                source_id = part['source_material_id']
                raw = packet['materials'][source_id]
                raw = raw.encode('utf-8') if isinstance(raw,str) else raw
                segment = raw[witness.start_byte:witness.end_byte]
                try:
                    decoded = segment.decode('utf-8')
                    encoded_quote = witness.quote.encode('utf-8')
                except UnicodeError:
                    reject('WITNESS_UTF8_BOUNDARY', 'Quote byte range/text is not exact valid UTF-8', witness.ref)
                if not witness.quote.strip() or decoded != witness.quote or segment != encoded_quote:
                    reject('WITNESS_QUOTE_MISMATCH', 'Quote is not an exact unnormalized original substring', witness.ref)
                key = (witness.ref,witness.start_byte,witness.end_byte,witness.quote)
                if key in seen_quotes:
                    reject('WITNESS_DUPLICATE_QUOTE', 'Duplicate witness within one clause', witness.ref)
                seen_quotes.add(key)
                sources[source_id] = packet['material_hashes'][source_id]
        previous = 0
        for start,end in sorted(intervals):
            if start < previous:
                reject('WITNESS_OVERLAPPING_CLAUSES', 'Claim clause code-point intervals must not overlap', verdict.unit_id)
            if any(not char.isspace() for char in text[previous:start]):
                reject('WITNESS_UNCOVERED_CLAIM_TEXT', 'A factual qualifier or other nonblank claim text is not covered',
                       {'unit_id': verdict.unit_id, 'gap_start_char': previous, 'gap_end_char': start})
            previous = end
        if any(not char.isspace() for char in text[previous:]):
            reject('WITNESS_UNCOVERED_CLAIM_TEXT', 'The claim ending contains uncovered nonblank text',
                   {'unit_id': verdict.unit_id, 'gap_start_char': previous, 'gap_end_char': len(text)})
    if submission.status == 'passed' and (submission.issues or any(verdict.verdict != 'passed' for verdict in submission.verdicts)):
        reject('WITNESS_PASSED_CONTRADICTS_NEGATIVE', 'A passed submission cannot contain negative units or issues')
    proof_submission = {key:copy.deepcopy(data[key]) for key in ('checked','status','reason','issues')}
    proof_submission['verdicts'] = [{key:copy.deepcopy(verdict[key]) for key in ('unit_id','verdict','reason')}
                                  for verdict in data['verdicts']]
    return {'schema':'source-quote-witness-validation/1',
            'literal_checks_completed':True,'semantic_entailment_proven':False,
            'publication_verified':False,'semantic_negative_detected':semantic_negative_detected(original),
            'proof_submission':proof_submission,'witness_submission':data,
            'canonical_input_material_hashes':copy.deepcopy(packet['material_hashes']),
            'quoted_source_material_hashes':sources,'witness_submission_sha256':payload_hash(data),
            'claim_count':len(coverage['claims']),'clause_count':clause_count,'witness_count':witness_count}
