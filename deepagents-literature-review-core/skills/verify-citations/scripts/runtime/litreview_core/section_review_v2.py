"""Experimental independent review of complete direct-premise inference.

Host-side dependency bundles retain original provenance. The delivered view is
explicitly a scientific dependency view, not delivery of child proof JSON or
original papers. No v1 gate or publication workflow is changed.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from typing import Literal

from pydantic import Field

from .hierarchical_proof import RuntimeIdentity, payload_hash
from .paper_review_v2 import (ReviewV2Error, ReviewIssueV2, project_paper_review_v2,
    restore_paper_review_v2, verify_paper_review_v2)
from .review_minimum_units import minimum_claim_units
from .review_artifacts import inference_packet, render_section, validate_draft
from .scientific_records import StrictModel
from .task_store import canonical
from .review_observation_selectors import (QUOTES, WHOLE_UNITS, WIRE_SCHEMA,
    validate_observation_mode, selector_wire, restore_selector_wire, replay_selection_attestation)


class PremiseObservationV2(StrictModel):
    premise_claim_id: str
    quote: str = Field(min_length=1)


class InferenceClauseV2(StrictModel):
    minimum_unit_id: str = Field(min_length=1)
    observations: list[PremiseObservationV2]
    premise_relation: Literal['direct', 'association', 'causal', 'conditional',
                              'not_reported', 'contradicted', 'uncertain']
    inference_relation: str = Field(min_length=1)
    qualification_check: str = Field(min_length=1)
    conclusion: Literal['supported', 'needs_revision', 'unresolved']
    reason: str = Field(min_length=1)


class SectionUnitV2(StrictModel):
    unit_id: str
    status: Literal['supported', 'needs_revision', 'unresolved']
    reason: str = Field(min_length=1)
    inference_checks: list[InferenceClauseV2] = Field(default_factory=list)


class SectionReviewSubmissionV2(StrictModel):
    unit_verdicts: list[SectionUnitV2]
    issues: list[ReviewIssueV2]


def _dependencies(children, identities, stack=()):
    if not isinstance(children, list) or not children:
        raise ReviewV2Error('Complete qualified direct dependencies are required')
    sections, views, sources, records, seen = [], [], {}, {}, set()
    for child in children:
        if not isinstance(child, dict) or set(child) != {'bundle', 'attestation'}:
            raise ReviewV2Error('Dependency must contain its exact v2 bundle and attestation')
        bundle, attestation = child['bundle'], child['attestation']
        review_id = bundle.get('review_id')
        if review_id in stack or review_id in seen:
            raise ReviewV2Error('Cyclic or duplicate direct dependency')
        seen.add(review_id)
        if bundle.get('schema') == 'paper-review-bundle/2':
            gate = verify_paper_review_v2(bundle, attestation, trusted_identities=identities)
            section = bundle['payload']['card']
            leaf = [(bundle['payload']['source'], bundle['payload']['reader'])]
        elif bundle.get('schema') == 'section-review-bundle/2':
            gate = verify_section_review_v2(bundle, attestation, trusted_identities=identities,
                                            _stack=(*stack, review_id))
            section = bundle['payload']['section']
            _, _, sub_sources, sub_records = _dependencies(bundle['children'], identities, (*stack, review_id))
            leaf = [(source, sub_records[pid]) for pid, source in sub_sources.items()]
        else:
            raise ReviewV2Error('Only genuine v2 reviews may qualify premises; v1 cannot be upgraded')
        if not gate['qualified_for_experiment'] or gate['status'] != 'passed':
            raise ReviewV2Error('Negative or unresolved dependency cannot qualify a premise')
        if any(s['section_id'] == section['section_id'] for s in sections):
            raise ReviewV2Error('Duplicate direct premise section')
        sections.append(copy.deepcopy(section))
        for source, record in leaf:
            pid = source['paper_id']
            if pid in sources and (canonical(sources[pid]) != canonical(source)
                                   or canonical(records[pid]) != canonical(record)):
                raise ReviewV2Error('Conflicting original source or reader versions in closure')
            sources[pid], records[pid] = source, record
        views.append({'review_id': review_id, 'section_id': section['section_id'],
                      'section_sha256': payload_hash(section),
                      'attestation_sha256': attestation['payload_sha256'],
                      'reviewer_execution_id': attestation['payload']['execution_id'],
                      'source_versions': copy.deepcopy(section['source_versions']),
                      'status': 'passed', 'delivery': 'qualified_scientific_view_not_full_child_proof'})
    return sections, views, sources, records


def section_draft_packet_v2(children, *, trusted_identities, questions,
                             kind='synthesis', dimensions=()):
    """Prepare writer input only after every exact direct child qualifies."""
    sections, _, sources, records = _dependencies(children, trusted_identities)
    ids = sorted(sources)
    return inference_packet(sections, [sources[p] for p in ids], [records[p] for p in ids],
                            questions, kind=kind, dimensions=dimensions)


def _logical(section, children, questions, identities, stack=()):
    sections, views, sources, records = _dependencies(children, identities, stack)
    ids = sorted(sources)
    packet = inference_packet(sections, [sources[p] for p in ids], [records[p] for p in ids],
                              questions, kind=section['kind'], dimensions=section['dimensions'])
    rebuilt = validate_draft(packet, {k: section[k] for k in ('claims', 'retention', 'cells')},
                              execution_id=section['writer_execution_id'])
    if canonical(rebuilt) != canonical(section):
        raise ReviewV2Error('Section does not match complete qualified direct premises and canonical inventory')
    minimum_units = minimum_claim_units(section['claims'])
    units = []
    def add(kind, **fields):
        units.append({'unit_id': 'u'+str(len(units)+1), 'kind': kind, **fields})
    for claim in section['claims']:
        add('new_inference', claim_id=claim['local_id'], premise_claim_ids=list(claim['premise_claim_ids']),
            minimum_unit_ids=[m['minimum_unit_id'] for m in minimum_units if m['claim_id'] == claim['local_id']])
        add('population_scope', claim_id=claim['local_id'])
    for obligation in packet['obligations']:
        add('premise_retention', obligation_id=obligation['id'], premise_claim_id=obligation['premise_claim_id'])
    for index, cell in enumerate(section['cells']):
        add('comparison_cell', cell_index=index, paper_id=cell['paper_id'], dimension=cell['dimension'])
    add('render_integration')
    return {'schema': 'section-review-logical/2', 'publication_allowed': False,
            'questions': copy.deepcopy(questions), 'section': copy.deepcopy(section),
            'render': render_section(section),
            'direct_premises': [{'section': s, 'render': render_section(s)} for s in sections],
            'qualified_dependencies': views, 'source_versions': {p: sources[p]['source_sha256'] for p in ids},
            'source_index': packet['sources'], 'required_units': units, 'minimum_units': minimum_units}


def project_section_review_v2(payload):
    wire = project_paper_review_v2(payload, encoding='paper-review-wire/2')
    wire['schema'] = 'section-review-wire/2'
    # Child renders also remain continuous visible prose, not concatenation refs.
    for actual, encoded in zip(payload['direct_premises'], wire['objects']['direct_premises']):
        encoded['render']['text'] = actual['render']['text']
    # Rebuild the table after preserving child renders to avoid orphan entries.
    used = set()
    def scan(value):
        if isinstance(value, dict):
            if set(value) == {'$text'}: used.add(value['$text'])
            else:
                for v in value.values(): scan(v)
        elif isinstance(value, list):
            for v in value: scan(v)
    scan(wire['objects'])
    wire['text_table'] = {k: v for k, v in wire['text_table'].items() if k in used}
    return wire


def restore_section_review_v2(wire):
    if isinstance(wire, dict) and wire.get('schema') == WIRE_SCHEMA:
        return restore_selector_wire(wire, kind='section', restore_base=restore_section_review_v2)
    if wire.get('schema') != 'section-review-wire/2':
        raise ReviewV2Error('Invalid section-review wire')
    return restore_paper_review_v2({**wire, 'schema': 'paper-review-wire/2'})


def plan_section_review_v2(section, children, *, questions, trusted_identities,
                          wire_counter=None, max_wire_tokens=120000, max_wire_bytes=800000,
                          observation_mode=QUOTES):
    validate_observation_mode(observation_mode)
    payload = _logical(section, children, questions, trusted_identities)
    wire = project_section_review_v2(payload)
    if observation_mode == WHOLE_UNITS:
        wire = selector_wire(payload, wire, 'section')
    if canonical(restore_section_review_v2(wire)) != canonical(payload):
        raise ReviewV2Error('Section wire roundtrip failed')
    count = wire_counter(wire) if wire_counter else None
    if len(canonical(wire)) > max_wire_bytes or (count is not None and count > max_wire_tokens):
        raise ReviewV2Error('OVERSIZED_SECTION_REVIEW: split actual inference; never truncate premises')
    digest = payload_hash(payload)
    return {'schema': 'section-review-bundle/2', 'review_id': 'sr2_'+digest[:24],
            'payload': payload, 'payload_sha256': digest, 'wire': wire, 'wire_sha256': payload_hash(wire),
            'children': copy.deepcopy(children), 'diagnostics': {'packet_token_estimate': count,
                'complete_request_budget_checked': False, 'publication_verified': False}}


def validate_section_bundle_v2(bundle, *, trusted_identities, _stack=()):
    p = bundle['payload']
    rebuilt = _logical(p['section'], bundle['children'], p['questions'], trusted_identities, _stack)
    if (bundle.get('schema') != 'section-review-bundle/2' or canonical(rebuilt) != canonical(p)
            or payload_hash(p) != bundle['payload_sha256']
            or bundle['review_id'] != 'sr2_'+payload_hash(p)[:24]
            or payload_hash(bundle['wire']) != bundle['wire_sha256']
            or canonical(restore_section_review_v2(bundle['wire'])) != canonical(p)):
        raise ReviewV2Error('Tampered section-review bundle, render, closure or delivered view')
    return p


def check_section_producer_v2(bundle, trusted_identities):
    section = bundle['payload']['section']
    context = section['writer_execution_id']
    identity = trusted_identities.get(context)
    role = 'comparer' if section['kind'] == 'comparison' else 'writer'
    if (not isinstance(identity, RuntimeIdentity) or identity.context_id != context
            or identity.execution_id != context or identity.role != role
            or not identity.input_hashes or not identity.task_call_id or not identity.parent_context_id
            or payload_hash(section) not in identity.output_hashes.values()):
        raise ReviewV2Error('Section requires its actual trusted SDK writer and exact output')


def section_writer_contexts_v2(bundle):
    return {bundle['payload']['section']['writer_execution_id'],
            *(p['section']['writer_execution_id'] for p in bundle['payload']['direct_premises'])}


def check_section_submission_v2(bundle, value, *, trusted_identities):
    p = validate_section_bundle_v2(bundle, trusted_identities=trusted_identities)
    submission = SectionReviewSubmissionV2.model_validate(value)
    required = {u['unit_id']: u for u in p['required_units']}
    counts = Counter(v.unit_id for v in submission.unit_verdicts)
    errors = {'missing': sorted(set(required)-set(counts)), 'unknown': sorted(set(counts)-set(required)),
              'duplicates': sorted(k for k, v in counts.items() if v > 1)}
    if any(errors.values()):
        raise ReviewV2Error('Verdict inventory mismatch: '+json.dumps(errors))
    claims = {c['local_id']: c for c in p['section']['claims']}
    premises = {s['section']['section_id']+'/'+c['local_id']: c
                for s in p['direct_premises'] for c in s['section']['claims']}
    for verdict in submission.unit_verdicts:
        if not verdict.reason.strip(): raise ReviewV2Error('Empty scientific reason')
        unit = required[verdict.unit_id]
        if unit['kind'] != 'new_inference':
            if verdict.inference_checks: raise ReviewV2Error('Clause checks belong to inference units')
            continue
        claim = claims[unit['claim_id']]
        counts = Counter(c.minimum_unit_id for c in verdict.inference_checks)
        expected = set(unit['minimum_unit_ids'])
        if set(counts) != expected or any(n != 1 for n in counts.values()):
            raise ReviewV2Error('Minimum-unit inventory mismatch; every assigned ID exactly once')
        for check in verdict.inference_checks:
            for observation in check.observations:
                if observation.premise_claim_id not in claim['premise_claim_ids']:
                    raise ReviewV2Error('Cannot borrow an undeclared scientific premise')
                if not observation.quote.strip() or observation.quote not in premises[observation.premise_claim_id]['text']:
                    raise ReviewV2Error('Premise quote does not match actual declared premise text')
            if check.conclusion == 'supported' and (not check.observations or check.premise_relation in ('contradicted','uncertain')):
                raise ReviewV2Error('Supported inference requires consistent literal premise observations')
            if any(not getattr(check, k).strip() for k in ('inference_relation','qualification_check','reason')):
                raise ReviewV2Error('Empty inference explanation')
        if verdict.status == 'supported' and any(c.conclusion != 'supported' for c in verdict.inference_checks):
            raise ReviewV2Error('Positive aggregate contradicts negative inference clause')
    for issue in submission.issues:
        if not set(issue.unit_ids) <= set(required) or not issue.description.strip() or not issue.correction.strip():
            raise ReviewV2Error('Issue has unknown duties or empty scientific explanation')
    statuses = [v.status for v in submission.unit_verdicts]
    status = ('needs_revision' if submission.issues or 'needs_revision' in statuses else
              'unresolved' if 'unresolved' in statuses else 'passed')
    return submission.model_dump(), status


def verify_section_review_v2(bundle, attestation, *, trusted_identities, _stack=()):
    validate_section_bundle_v2(bundle, trusted_identities=trusted_identities, _stack=_stack)
    check_section_producer_v2(bundle, trusted_identities)
    a = attestation['payload']
    if attestation.get('schema') != 'section-review-attestation/2' or payload_hash(a) != attestation['payload_sha256']:
        raise ReviewV2Error('Invalid section attestation envelope')
    data, status = check_section_submission_v2(bundle, a['submission'], trusted_identities=trusted_identities)
    selection = replay_selection_attestation(bundle, a,
        normalize=lambda value:SectionReviewSubmissionV2.model_validate(value).model_dump())
    identity = trusted_identities.get(a['execution_id'])
    dependencies = {v['review_id']: v['attestation_sha256'] for v in bundle['payload']['qualified_dependencies']}
    if (not isinstance(identity, RuntimeIdentity) or identity.context_id != a['execution_id']
            or identity.execution_id != a['execution_id'] or identity.role != 'source_verifier'
            or not identity.task_call_id or not identity.parent_context_id
            or dict(identity.input_hashes) != {'section-review-v2.json': bundle['wire_sha256']}
            or dict(identity.dependency_hashes) != dependencies
            or dict(identity.output_hashes) != {bundle['review_id']: attestation['payload_sha256']}):
        raise ReviewV2Error('Review is not bound to actual independent SDK execution and qualified child versions')
    if section_writer_contexts_v2(bundle) & ({identity.context_id, identity.parent_context_id} | set(identity.ancestor_context_ids)):
        raise ReviewV2Error('Writer context cannot independently review its inference')
    expected = {'review_id': bundle['review_id'], 'bundle_sha256': bundle['payload_sha256'],
                'wire_sha256': bundle['wire_sha256'], 'execution_id': identity.execution_id,
                'dependency_hashes': dependencies, 'status': status, 'submission': data,
                'publication_verified': False, **selection}
    if canonical(a) != canonical(expected): raise ReviewV2Error('Stale or invented section aggregate')
    return {'schema': 'section-review-mechanical-gate/2', 'status': status,
            'qualified_for_experiment': status == 'passed', 'publication_verified': False,
            'reviewer_semantics_not_host_proven': True, 'source_versions': bundle['payload']['source_versions'],
            'attestation_sha256': attestation['payload_sha256']}

