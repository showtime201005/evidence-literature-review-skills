"""Experimental single-reviewer paper contract; never authorizes publication.

The host checks provenance, literal source bindings and complete inventories.
Semantic support, omissions and integration remain model judgments. No v1 gate
or workflow is changed, and no identity can be imported from JSON here.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field

from .hierarchical_proof import RuntimeIdentity, payload_hash
from .proof_planner import _reader_records
from .review_artifacts import draft_packet, render_section, validate_draft
from .scientific_records import StrictModel, source_packet
from .review_minimum_units import minimum_claim_units
from .paper_review_v2_wire import compact_paper_wire_v21, expand_paper_wire_v21
from .task_store import canonical
from .review_observation_selectors import (QUOTES, WHOLE_UNITS, WIRE_SCHEMA,
    validate_observation_mode, selector_wire, restore_selector_wire, replay_selection_attestation)


class ReviewV2Error(ValueError):
    pass


class SourceObservationV2(StrictModel):
    source_ref: str
    quote: str = Field(min_length=1)


class MinimumUnitCheckV2(StrictModel):
    minimum_unit_id: str
    observations: list[SourceObservationV2]
    source_relation: Literal['direct', 'association', 'causal', 'conditional',
                             'not_reported', 'contradicted', 'uncertain']
    claim_relation: str = Field(min_length=1)
    qualification_check: str = Field(min_length=1)
    conclusion: Literal['supported', 'needs_revision', 'unresolved']
    reason: str = Field(min_length=1)


class UnitReviewV2(StrictModel):
    unit_id: str
    status: Literal['supported', 'needs_revision', 'unresolved']
    reason: str = Field(min_length=1)
    claim_checks: list[MinimumUnitCheckV2] = Field(default_factory=list)


class ReviewIssueV2(StrictModel):
    unit_ids: list[str] = Field(min_length=1)
    description: str = Field(min_length=1)
    correction: str = Field(min_length=1)


class OmissionV2(StrictModel):
    source_refs: list[str] = Field(min_length=1)
    description: str = Field(min_length=1)
    importance: str = Field(min_length=1)
    affected_target_ids: list[str]


class PaperReviewSubmissionV2(StrictModel):
    unit_verdicts: list[UnitReviewV2]
    new_omissions: list[OmissionV2]
    issues: list[ReviewIssueV2]

_TEXT_KEYS = {'text', 'quote', 'note', 'reason', 'description', 'importance'}


def project_paper_review_v2(payload, *, compose_render=False, encoding='paper-review-wire/2.1'):
    """Lossless single text table with a continuous readable actual render.

    Full source parts are stored once; identical reader quotes reuse them.
    The complete render is deliberately repeated as plain continuous text for
    scientific readability. Optional composition is a sizing experiment only.
    """
    table, inverse = {}, {}

    def intern(text):
        if text not in inverse:
            # Native JSON sorts keys; padding preserves source paragraph order.
            key = 't' + str(len(table) + 1).zfill(6)
            table[key], inverse[text] = text, key
        return {'$text': inverse[text]}

    def text_value(text, compose=False):
        if text in inverse:
            return intern(text)
        if compose:
            # Longest literal matches first; no normalization or semantic edit.
            candidates = sorted((s for s in inverse if len(s) >= 8 and s in text),
                                key=lambda s: (-len(s), s))
            pieces, cursor = [], 0
            while cursor < len(text):
                matches = [(text.find(s, cursor), s) for s in candidates if text.find(s, cursor) >= 0]
                if not matches:
                    pieces.append(intern(text[cursor:]))
                    break
                start, found = min(matches, key=lambda item: (item[0], -len(item[1]), item[1]))
                if start > cursor:
                    pieces.append(intern(text[cursor:start]))
                pieces.append(intern(found))
                cursor = start + len(found)
            if pieces:
                return {'$concat': pieces}
        return intern(text)

    def encode(value, key='', compose=False):
        if isinstance(value, dict):
            return {k: encode(v, k, compose) for k, v in value.items()}
        if isinstance(value, list):
            return [encode(v, key, compose) for v in value]
        if isinstance(value, str) and key in _TEXT_KEYS:
            return text_value(value, compose)
        return copy.deepcopy(value)

    # Explicit traversal preserves all values and gives render access to claims.
    objects = {key: encode(value) for key, value in payload.items() if key != 'render'}
    objects['render'] = encode({k:v for k,v in payload['render'].items() if k!='text'}, compose=compose_render)
    objects['render']['text'] = (text_value(payload['render']['text'], compose=True) if compose_render
                                 else payload['render']['text'])
    legacy = {'schema': 'paper-review-wire/2', 'text_table': table, 'objects': objects}
    if encoding == 'paper-review-wire/2.1':
        return compact_paper_wire_v21(legacy)
    if encoding == 'paper-review-wire/2':
        return legacy
    raise ReviewV2Error('Unknown paper-review wire encoding')


def restore_paper_review_v2(wire):
    if isinstance(wire, dict) and wire.get('schema') == WIRE_SCHEMA:
        return restore_selector_wire(wire, kind='paper', restore_base=restore_paper_review_v2)
    if isinstance(wire, dict) and wire.get('schema') == 'paper-review-wire/2.1':
        wire = expand_paper_wire_v21(wire)
    if not isinstance(wire, dict) or set(wire) != {'schema', 'text_table', 'objects'} or wire['schema'] != 'paper-review-wire/2':
        raise ReviewV2Error('Invalid v2 wire envelope')
    table = wire['text_table']
    if not isinstance(table, dict) or any(not isinstance(v, str) for v in table.values()):
        raise ReviewV2Error('Invalid text table')
    used = set()

    def decode(value):
        if isinstance(value, dict):
            if set(value) == {'$text'}:
                key = value['$text']
                if key not in table:
                    raise ReviewV2Error('Unknown text reference')
                used.add(key)
                return table[key]
            if set(value) == {'$concat'}:
                parts = value['$concat']
                if not isinstance(parts, list) or not parts:
                    raise ReviewV2Error('Empty or invalid concatenation')
                strings = [decode(v) for v in parts]
                if any(not isinstance(s, str) for s in strings):
                    raise ReviewV2Error('Concatenation contains non-text')
                return ''.join(strings)
            return {key: decode(v) for key, v in value.items()}
        if isinstance(value, list):
            return [decode(v) for v in value]
        return copy.deepcopy(value)

    restored = decode(wire['objects'])
    if used != set(table):
        raise ReviewV2Error('Unreferenced wire text could hide unreviewed material')
    return restored


def _logical_payload(source, reader, card):
    raw = b''.join(part['text'].encode('utf-8') for part in source['parts'])
    rebuilt_source = source_packet(source['paper_id'], raw, source['questions'])
    if canonical(rebuilt_source) != canonical(source):
        raise ReviewV2Error('Source bytes, parts or version cannot be reconstructed')
    _reader_records([reader], {source['paper_id']: source})
    profile=card.get('reader_context_profile')
    if profile not in (None,'reader-finding-context/1'):
        raise ReviewV2Error('Unknown paper card reader context profile')
    packet = draft_packet('paper_card', [source], [reader], source['questions'],
                          include_reader_findings=profile is not None)
    rebuilt_card = validate_draft(packet, {k: card[k] for k in ('claims', 'retention', 'cells')},
                                  execution_id=card['writer_execution_id'])
    if canonical(rebuilt_card) != canonical(card):
        raise ReviewV2Error('Card version, citations or original context changed')
    units = []
    minimum_units = minimum_claim_units(card['claims'])
    for claim in card['claims']:
        units.append({'unit_id': 'u' + str(len(units) + 1), 'kind': 'claim_support',
                      'claim_id': claim['local_id'], 'source_refs': list(claim['evidence_refs']),
                      'minimum_unit_ids': [u['minimum_unit_id'] for u in minimum_units if u['claim_id']==claim['local_id']]})
    for obligation in reader['obligations']:
        units.append({'unit_id': 'u' + str(len(units) + 1), 'kind': 'raw_retention',
                      'obligation_id': obligation['id']})
    for kind in ('full_source_omissions', 'render_integration'):
        units.append({'unit_id': 'u' + str(len(units) + 1), 'kind': kind})
    return {'schema': 'paper-review-logical/2.1', 'publication_allowed': False,
            'source': copy.deepcopy(source), 'reader': copy.deepcopy(reader),
            'card': copy.deepcopy(card), 'render': render_section(card), 'required_units': units,
            'minimum_unit_contract': 'review-minimum-units/1', 'minimum_units': minimum_units,
            'minimum_unit_semantic_atomicity_proven': False}


def plan_paper_review_v2(source, reader, card, *, wire_counter=None,
                         max_wire_tokens=120000, max_wire_bytes=800000,
                         wire_encoding='paper-review-wire/2.1', observation_mode=QUOTES):
    validate_observation_mode(observation_mode)
    payload = _logical_payload(source, reader, card)
    wire = project_paper_review_v2(payload, encoding=wire_encoding)
    if observation_mode == WHOLE_UNITS:
        wire = selector_wire(payload, wire, 'paper')
    if canonical(restore_paper_review_v2(wire)) != canonical(payload):
        raise ReviewV2Error('Projection roundtrip failed')
    count = wire_counter(wire) if wire_counter else None
    if len(canonical(wire)) > max_wire_bytes or (count is not None and count > max_wire_tokens):
        raise ReviewV2Error('OVERSIZED_PAPER_REVIEW: split writing or use an explicit bounded review design; no truncation')
    digest = payload_hash(payload)
    return {'schema': 'paper-review-bundle/2', 'review_id': 'pr2_' + digest[:24],
            'payload': payload, 'payload_sha256': digest, 'wire': wire,
            'wire_sha256': payload_hash(wire), 'diagnostics': {
                'logical_bytes': len(canonical(payload)), 'wire_bytes': len(canonical(wire)),
                'packet_token_estimate': count, 'counter_identity': getattr(wire_counter, 'identity', None),
                'required_verdict_count': len(payload['required_units']),
                'minimum_unit_count': len(payload['minimum_units']), 'wire_encoding': wire_encoding,
                'complete_request_budget_checked': False, 'publication_verified': False}}


def validate_paper_bundle_v2(bundle):
    p = bundle['payload']
    rebuilt = _logical_payload(p['source'], p['reader'], p['card'])
    if (bundle.get('schema') != 'paper-review-bundle/2' or canonical(rebuilt) != canonical(p)
            or payload_hash(p) != bundle['payload_sha256']
            or bundle['review_id'] != 'pr2_' + payload_hash(p)[:24]
            or payload_hash(bundle['wire']) != bundle['wire_sha256']
            or canonical(restore_paper_review_v2(bundle['wire'])) != canonical(p)):
        raise ReviewV2Error('Stale or tampered paper-review bundle')
    return p


def check_submission_v2(bundle, value):
    """Validate literals and declared coverage, not scientific entailment."""
    p = validate_paper_bundle_v2(bundle)
    s = PaperReviewSubmissionV2.model_validate(value)
    ids = [u.unit_id for u in s.unit_verdicts]
    required = {u['unit_id']: u for u in p['required_units']}
    counts = Counter(ids)
    errors = {'missing': sorted(set(required) - set(ids)), 'unknown': sorted(set(ids) - set(required)),
              'duplicates': sorted(uid for uid, count in counts.items() if count > 1)}
    if any(errors.values()):
        raise ReviewV2Error('Verdict inventory mismatch: ' + json.dumps(errors, ensure_ascii=False))
    parts = {p['source']['paper_id'] + '/' + part['part_id']: part['text'] for part in p['source']['parts']}
    claims = {c['local_id']: c for c in p['card']['claims']}
    minimum_errors = {}
    for verdict in s.unit_verdicts:
        unit = required[verdict.unit_id]
        if unit['kind'] != 'claim_support':
            continue
        checked_ids = [c.minimum_unit_id for c in verdict.claim_checks]
        counts = Counter(checked_ids)
        expected = set(unit['minimum_unit_ids'])
        problems = {'missing': sorted(expected-set(checked_ids)), 'unknown': sorted(set(checked_ids)-expected),
                    'duplicates': sorted(uid for uid,count in counts.items() if count>1)}
        if any(problems.values()): minimum_errors[verdict.unit_id] = problems
    if minimum_errors:
        raise ReviewV2Error('Minimum-unit inventory mismatch: '+json.dumps(minimum_errors,ensure_ascii=False))
    for verdict in s.unit_verdicts:
        if not verdict.reason.strip():
            raise ReviewV2Error('Unit reason cannot be whitespace')
        unit = required[verdict.unit_id]
        if unit['kind'] != 'claim_support':
            if verdict.claim_checks:
                raise ReviewV2Error('Clause checks belong only to claim-support units')
            continue
        claim = claims[unit['claim_id']]
        for check_index, check in enumerate(verdict.claim_checks):
            for observation_index, observation in enumerate(check.observations):
                location = (f'unit={verdict.unit_id}, minimum_unit={check.minimum_unit_id}, '
                            f'claim_checks[{check_index}].observations[{observation_index}]')
                if observation.source_ref not in unit['source_refs']:
                    raise ReviewV2Error('Cannot borrow support from undeclared own source parts: '+location)
                if not observation.quote.strip() or observation.quote not in parts[observation.source_ref]:
                    raise ReviewV2Error('Literal quote does not match the declared original part: '+location+
                        '; source_ref='+observation.source_ref+'; copy exact text from this assigned part without paraphrasing')
            if check.conclusion == 'supported' and (not check.observations or check.source_relation in ('contradicted', 'uncertain')):
                raise ReviewV2Error('Supported clause needs literal own-source observations and a consistent relation')
            if any(not getattr(check, name).strip() for name in ('reason', 'claim_relation', 'qualification_check')):
                raise ReviewV2Error('Source-first scientific explanation cannot be whitespace')
        if verdict.status == 'supported' and any(c.conclusion != 'supported' for c in verdict.claim_checks):
            raise ReviewV2Error('Supported claim contradicts a negative minimum-unit judgment')
    if any(not set(issue.unit_ids) <= set(required) for issue in s.issues):
        raise ReviewV2Error('Issue references an unknown duty')
    if any(not issue.description.strip() or not issue.correction.strip() for issue in s.issues):
        raise ReviewV2Error('Issue description/correction cannot be whitespace')
    for omission in s.new_omissions:
        if not set(omission.source_refs) <= set(parts) or not set(omission.affected_target_ids) <= set(claims):
            raise ReviewV2Error('Omission references unknown source or target')
        if not omission.description.strip() or not omission.importance.strip():
            raise ReviewV2Error('Omission explanation cannot be whitespace')
    data = s.model_dump()
    statuses = [v.status for v in s.unit_verdicts]
    status = ('needs_revision' if s.issues or s.new_omissions or 'needs_revision' in statuses
              else 'unresolved' if 'unresolved' in statuses else 'passed')
    return data, status


def check_producers_v2(bundle, identities):
    p = validate_paper_bundle_v2(bundle)
    for context, role, artifact in ((p['card']['writer_execution_id'], 'writer', p['card']),
                                     (p['reader']['execution_id'], 'reader', p['reader'])):
        identity = identities.get(context)
        if (not isinstance(identity, RuntimeIdentity) or identity.context_id != context
                or identity.execution_id != context or identity.role != role
                or not identity.task_call_id or not identity.parent_context_id
                or not identity.input_hashes or payload_hash(artifact) not in identity.output_hashes.values()):
            raise ReviewV2Error('Original producer requires its actual trusted SDK execution and exact artifact')


def verify_paper_review_v2(bundle, attestation, *, trusted_identities):
    check_producers_v2(bundle, trusted_identities)
    a = attestation['payload']
    if attestation.get('schema') != 'paper-review-attestation/2' or payload_hash(a) != attestation['payload_sha256']:
        raise ReviewV2Error('Invalid attestation envelope')
    data, status = check_submission_v2(bundle, a['submission'])
    selection = replay_selection_attestation(bundle, a,
        normalize=lambda value:PaperReviewSubmissionV2.model_validate(value).model_dump())
    expected_inputs = {'paper-review-v2.json': bundle['wire_sha256']}
    identity = trusted_identities.get(a['execution_id'])
    if (not isinstance(identity, RuntimeIdentity) or identity.context_id != a['execution_id']
            or identity.role != 'source_verifier' or not identity.task_call_id or not identity.parent_context_id
            or dict(identity.input_hashes) != expected_inputs or identity.dependency_hashes
            or dict(identity.output_hashes) != {bundle['review_id']: attestation['payload_sha256']}):
        raise ReviewV2Error('Attestation is not bound to the actual independent runtime execution')
    producers = {bundle['payload']['card']['writer_execution_id'], bundle['payload']['reader']['execution_id']}
    if producers & ({identity.context_id, identity.parent_context_id} | set(identity.ancestor_context_ids)):
        raise ReviewV2Error('Writer/reader cannot review its own paper context')
    expected = {'review_id': bundle['review_id'], 'bundle_sha256': bundle['payload_sha256'],
                'wire_sha256': bundle['wire_sha256'], 'execution_id': identity.execution_id,
                'status': status, 'submission': data, 'publication_verified': False, **selection}
    if canonical(a) != canonical(expected):
        raise ReviewV2Error('Stale attestation target or invented aggregate verdict')
    return {'schema': 'paper-review-mechanical-gate/2', 'status': status,
            'qualified_for_experiment': status == 'passed', 'publication_verified': False,
            'reviewer_semantics_not_host_proven': True,
            'attestation_sha256': attestation['payload_sha256']}


def save_paper_review_attempt_v2(bundle, attempts, output_path):
    """Content-addressed experiment archive; never publishes a verified report."""
    validate_paper_bundle_v2(bundle)
    archive = {'schema': 'paper-review-attempt/2', 'publication_verified': False,
               'bundle': copy.deepcopy(bundle), 'attempts': copy.deepcopy(attempts),
               'identity_json_is_not_a_trust_registry': True}
    root = Path(output_path)
    root.mkdir(parents=True, exist_ok=True)
    target = root / (payload_hash(archive) + '.json')
    raw = canonical(archive)
    if target.exists() and target.read_bytes() != raw:
        raise ReviewV2Error('Immutable attempt archive changed')
    if not target.exists():
        with target.open('xb') as stream:
            stream.write(raw)
    return target
