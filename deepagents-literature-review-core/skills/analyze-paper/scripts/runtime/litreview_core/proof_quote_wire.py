"""Experimental unique exact-match adapter; not connected to production.

The model emits ordered exact claim substrings and declared ref + exact quote,
without computing Unicode or byte offsets. This trusted adapter adds coordinates
only when each match is unique, then invokes the strict canonical validator.
Runtime-owned canonical packets and their trusted hashes remain authoritative.

Decode responsibility aliases before calling. The returned wire hash binds the
parsed unmodified submission's canonical serialization, NOT the raw HTTP request.
No native proof, worker identity or semantic entailment is manufactured here.
"""
from __future__ import annotations

import copy
from typing import Literal

from pydantic import Field, StrictStr, ValidationError

from .hierarchical_proof import payload_hash
from .proof_citation_view import build_citation_view
from .proof_quote_witness import (WitnessIssue, WitnessValidationError,
    semantic_negative_detected, validate_source_witness_submission)
from .scientific_records import StrictModel


class QuoteWireWitness(StrictModel):
    ref: StrictStr = Field(min_length=1)
    quote: StrictStr = Field(min_length=1, description='Exact unnormalized substring of this claim own declared original part')


class ClauseWireCheck(StrictModel):
    clause: StrictStr = Field(min_length=1, description='Exact actual-claim substring; clause list order is textual order')
    relation: Literal['explicit_support', 'topic_only', 'not_reported', 'contradicted', 'unresolved']
    witnesses: list[QuoteWireWitness]
    reason: StrictStr = Field(min_length=1)


class UnitWireVerdict(StrictModel):
    unit_id: StrictStr = Field(min_length=1)
    verdict: Literal['passed', 'needs_revision', 'unresolved']
    reason: StrictStr = Field(min_length=1)
    clause_checks: list[ClauseWireCheck] | None = Field(default=None,
        description='Required for assigned claims only; ordered nonoverlapping substrings must cover every nonwhitespace character')


class SourceWitnessWireSubmission(StrictModel):
    checked: dict[StrictStr, list[StrictStr]]
    verdicts: list[UnitWireVerdict]
    status: Literal['passed', 'needs_revision', 'unresolved']
    reason: StrictStr = Field(min_length=1)
    issues: list[WitnessIssue]


def source_witness_tool_schema():
    """Model-facing full contract; use as a JSON-Schema dict, not a BaseModel.

    Installed LangChain passes dict-schema tool arguments to the callable without
    Pydantic validation. The callable must save the entire raw envelope first,
    then call unwrap_source_witness_tool_arguments and the strict adapter. This
    lets malformed scientific negatives reach trusted terminal handling instead
    of disappearing into an automatic pre-tool format retry.
    """
    data_schema=SourceWitnessWireSubmission.model_json_schema()
    definitions=data_schema.pop('$defs',{})
    return {'title':'SourceWitnessToolArguments','type':'object',
        'description':'Submit the complete per-unit scientific result. Runtime validates after preserving raw arguments; never omit a negative to repair formatting.',
        'properties':{'data':data_schema},'required':['data'],'additionalProperties':False,
        '$defs':definitions}


def unwrap_source_witness_tool_arguments(rawargs):
    """Require exactly {'data': dict}; retain full raw/negative on any error.

    No coercion, JSON-string repair, ignored outer extras or schema defaults are
    applied. A JSON-string negative is detected for terminal handling, while its
    incorrect type remains a strict error. The caller already persisted rawargs.
    """
    original=copy.deepcopy(rawargs)
    if not isinstance(rawargs,dict) or set(rawargs)!={'data'} or not isinstance(rawargs.get('data'),dict):
        raise WitnessValidationError('WIRE_TOOL_ARGUMENTS_INVALID',
            'Tool arguments must contain exactly one data field with a JSON object',original,
            {'expected':'exactly {"data": object}; no outer extras or coercion'})
    return copy.deepcopy(rawargs['data'])


def _occurrences(haystack, needle, *, start=0):
    """Include overlapping matches; no normalization and no first-match guess."""
    found = []
    cursor = start
    while True:
        index = haystack.find(needle, cursor)
        if index < 0:
            return found
        found.append(index)
        cursor = index + 1


def adapt_source_witness_wire(packet, value, *, expected_material_hashes=None):
    """Derive strict coordinates, retaining raw negatives on every rejection.

    Quotes: exactly one exact UTF-8 occurrence within the *own declared part*.
    Clauses: exactly one exact codepoint occurrence in the remaining claim after
    the previous clause; supplied order must therefore equal textual order. The
    canonical validator then enforces full nonwhitespace coverage and all existing
    quote/version/verdict constraints. Ambiguous repeated text fails closed;
    a model can use a longer exact clause/quote to make a future input unique.

    Scientific negatives are detected BEFORE schema/adaptation and the original
    wire submission is deep-copied on errors. Future callers must terminate or
    revise on that flag rather than retrying until the negative disappears.
    """
    original = copy.deepcopy(value)

    def reject(code, message, details=None):
        raise WitnessValidationError(code, message, original, details)

    if (not isinstance(packet, dict) or packet.get('schema') != 'hierarchical-proof-task/1'
            or packet.get('kind') != 'source'):
        reject('WIRE_UNSUPPORTED_SCOPE', 'Unique quote matching requires a runtime-owned canonical source packet')
    if 'responsibility_encoding' in packet:
        reject('WIRE_NONCANONICAL_INPUT', 'Decode responsibility aliases before adapting into canonical packet coordinates')
    if expected_material_hashes is not None and expected_material_hashes != packet.get('material_hashes'):
        reject('WIRE_INPUT_BINDING_MISMATCH', 'Delivered materials differ from the trusted expected plan')
    if not isinstance(value, dict):
        reject('WIRE_SCHEMA_INVALID', 'Wire submission must be a JSON object')
    try:
        typed = SourceWitnessWireSubmission.model_validate(value)
    except ValidationError as exc:
        reject('WIRE_SCHEMA_INVALID', 'Wire quote-witness schema is invalid',
               exc.errors(include_input=False, include_url=False))
    try:
        view = build_citation_view(packet)
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
        reject('WIRE_SOURCE_CONTEXT_INVALID', 'Original claim/locator/version context cannot be reconstructed', str(exc))
    coverage = packet.get('coverage')
    if not isinstance(coverage, dict) or not isinstance(coverage.get('claims'), list):
        reject('WIRE_SOURCE_CONTEXT_INVALID', 'Canonical source claim inventory is missing')
    rows = {row['claim_id']: row for row in view['claim_rows']}
    data = typed.model_dump(exclude_none=True)
    clause_count = quote_count = 0
    for verdict in data['verdicts']:
        clauses = verdict.get('clause_checks', [])
        if verdict['unit_id'] not in coverage['claims']:
            if clauses:
                reject('WIRE_CLAUSES_WRONG_SCOPE', 'Only assigned source claims receive clause witnesses', verdict['unit_id'])
            continue
        row = rows.get(verdict['unit_id'])
        if not row or row['availability'] != 'delivered_claim' or not isinstance(row['text'], str):
            reject('WIRE_CLAIM_CONTEXT_UNAVAILABLE', 'The actual assigned claim text is missing', verdict['unit_id'])
        declared = {part['ref']: part for part in row['declared_parts']}
        text, cursor = row['text'], 0
        for clause_index, clause in enumerate(clauses):
            if not clause['clause'].strip():
                reject('WIRE_EMPTY_CLAUSE', 'A clause needs nonwhitespace actual claim text', verdict['unit_id'])
            matches = _occurrences(text, clause['clause'], start=cursor)
            if len(matches) != 1:
                reject('WIRE_CLAUSE_NOT_FOUND' if not matches else 'WIRE_CLAUSE_AMBIGUOUS',
                       'Ordered exact clause must have exactly one remaining claim match',
                       {'unit_id': verdict['unit_id'], 'clause_index': clause_index,
                        'remaining_start_char': cursor, 'match_count': len(matches)})
            start = matches[0]
            cursor = start + len(clause['clause'])
            clause.update(start_char=start, end_char=cursor)
            clause_count += 1
            for witness in clause['witnesses']:
                part = declared.get(witness['ref'])
                if part is None:
                    reject('WIRE_UNDECLARED_REF', 'Ref is not among this actual claim own declared parts',
                           {'unit_id': verdict['unit_id'], 'ref': witness['ref']})
                if part['availability'] != 'delivered_exact_part':
                    reject('WIRE_ORIGINAL_NOT_DELIVERED', 'No original bytes were supplied for this declared part', witness['ref'])
                if not witness['quote'].strip():
                    reject('WIRE_EMPTY_QUOTE', 'A quote needs nonwhitespace exact original text', witness['ref'])
                try:
                    raw_part = part['text'].encode('utf-8')
                    needle = witness['quote'].encode('utf-8')
                except UnicodeError:
                    reject('WIRE_INVALID_UTF8', 'Original quote must encode as exact valid UTF-8', witness['ref'])
                matches = _occurrences(raw_part, needle)
                if len(matches) != 1:
                    reject('WIRE_QUOTE_NOT_FOUND' if not matches else 'WIRE_QUOTE_AMBIGUOUS',
                           'Exact quote must have exactly one occurrence within its own declared part',
                           {'unit_id': verdict['unit_id'], 'ref': witness['ref'], 'match_count': len(matches)})
                start_byte = part['start_byte'] + matches[0]
                witness.update(start_byte=start_byte, end_byte=start_byte + len(needle))
                quote_count += 1
    try:
        validated = validate_source_witness_submission(packet, data, expected_material_hashes=expected_material_hashes)
    except WitnessValidationError as exc:
        # The original *wire* negative remains the terminal record. Coordinate
        # derivation must not replace it with a normalized retryable format error.
        reject(exc.code, str(exc), {'stage':'canonical_validation',
            'canonical_error_details':copy.deepcopy(exc.details), 'derived_canonical_submission':data})
    return {'schema':'source-quote-witness-adaptation/1',
        'coordinates_derived_by':'runtime-unique-exact-match/1',
        'wire_submission':original, 'wire_submission_sha256':payload_hash(original),
        'wire_hash_method':'Canonical serialization of unmodified parsed model submission; not raw HTTP request bytes',
        'canonical_witness_submission':validated['witness_submission'],
        'canonical_witness_submission_sha256':validated['witness_submission_sha256'],
        'literal_validation':validated,
        'semantic_negative_detected':semantic_negative_detected(original),
        'publication_verified':False, 'semantic_entailment_proven':False,
        'uniquely_resolved_clauses':clause_count, 'uniquely_resolved_quotes':quote_count}
