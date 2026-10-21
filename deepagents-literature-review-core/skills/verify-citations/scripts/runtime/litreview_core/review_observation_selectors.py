"""Explicit whole-unit observation transport; no semantic decisions are made.

Original text stays in the existing complete input. A selected whole source
part/premise claim is expanded without normalization to the legacy observation.
Scientific reasons, relations, qualifications and every review duty stay intact.
"""
from __future__ import annotations

import copy

from .hierarchical_proof import payload_hash
from .task_store import canonical

QUOTES = 'quotes'
WHOLE_UNITS = 'whole-unit-selectors/1'
WIRE_SCHEMA = 'review-observation-selector-wire/1'
SELECTION_SCHEMA = 'review-observation-selection/1'


def validate_observation_mode(mode):
    if mode not in (QUOTES, WHOLE_UNITS):
        raise ValueError('Observation mode must be quotes or whole-unit-selectors/1')
    return mode


def _index(payload, kind):
    rows, texts = [], {}
    if kind == 'paper':
        source = payload['source']
        for i, part in enumerate(source['parts'], 1):
            sid = 's'+str(i)
            rows.append({'selector_id':sid, 'source_ref':source['paper_id']+'/'+part['part_id'],
                'source_sha256':source['source_sha256'], 'text_sha256':payload_hash(part['text'].encode('utf8')),
                'start_byte':part['start_byte'], 'end_byte':part['end_byte']})
            texts[sid] = part['text']
    elif kind == 'section':
        for item in payload['direct_premises']:
            section = item['section']
            for claim in section['claims']:
                sid = 'p'+str(len(rows)+1)
                rows.append({'selector_id':sid, 'premise_claim_id':section['section_id']+'/'+claim['local_id'],
                    'section_sha256':payload_hash(section), 'text_sha256':payload_hash(claim['text'].encode('utf8')),
                    'start_char':0, 'end_char':len(claim['text'])})
                texts[sid] = claim['text']
    else:
        raise ValueError('Unknown whole-unit observation kind')
    owners = [r.get('source_ref', r.get('premise_claim_id')) for r in rows]
    if len(owners) != len(set(owners)) or not rows:
        raise ValueError('Whole-unit observations require unique nonempty actual owners')
    return rows, texts


def selector_wire(payload, base_wire, kind):
    rows, _ = _index(payload, kind)
    return {'schema':WIRE_SCHEMA, 'mode':WHOLE_UNITS, 'kind':kind,
        'base_wire':copy.deepcopy(base_wire), 'selector_index':rows,
        'selector_index_sha256':payload_hash(rows)}


def restore_selector_wire(wire, *, kind, restore_base):
    expected = {'schema','mode','kind','base_wire','selector_index','selector_index_sha256'}
    if (not isinstance(wire, dict) or set(wire) != expected or wire.get('schema') != WIRE_SCHEMA
            or wire.get('mode') != WHOLE_UNITS or wire.get('kind') != kind
            or not isinstance(wire['base_wire'], dict) or wire['base_wire'].get('schema') == WIRE_SCHEMA):
        raise ValueError('Invalid whole-unit selector wire')
    payload = restore_base(wire['base_wire'])
    rows, _ = _index(payload, kind)
    if canonical(wire['selector_index']) != canonical(rows) or wire['selector_index_sha256'] != payload_hash(rows):
        raise ValueError('Whole-unit selector index does not match actual source/premise bytes and versions')
    return payload


def whole_unit_mode(bundle):
    return bundle['wire'].get('schema') == WIRE_SCHEMA


def selector_tool_schema(schema, kind):
    """Change only the observation transport in the advertised typed schema."""
    result = copy.deepcopy(schema)
    name = 'SourceObservationV2' if kind == 'paper' else 'PremiseObservationV2'
    if name not in result.get('$defs', {}):
        raise ValueError('Typed observation definition is missing')
    result['$defs'][name] = {'title':name, 'type':'object',
        'properties':{'selector_id':{'type':'string','minLength':1}},
        'required':['selector_id'], 'additionalProperties':False}
    return result


def expand_selector_submission(bundle, raw):
    """Expand selector syntax only; never repair a reason, verdict or relation."""
    if not whole_unit_mode(bundle):
        return copy.deepcopy(raw)
    p, wire = bundle['payload'], bundle['wire']
    kind = wire['kind']
    rows, texts = _index(p, kind)
    if canonical(wire['selector_index']) != canonical(rows) or wire['selector_index_sha256'] != payload_hash(rows):
        raise ValueError('Stale or tampered whole-unit selector index')
    if not isinstance(raw,dict) or set(raw) != {'data'} or not isinstance(raw['data'],dict):
        raise ValueError('Submit exactly {data: object}; selector mode does not coerce legacy arguments')
    expanded = copy.deepcopy(raw)
    units = {u['unit_id']:u for u in p['required_units']}
    lookup = {r['selector_id']:r for r in rows}
    check_key = 'claim_checks' if kind == 'paper' else 'inference_checks'
    owner_key = 'source_ref' if kind == 'paper' else 'premise_claim_id'
    owners_key = 'source_refs' if kind == 'paper' else 'premise_claim_ids'
    verdicts = expanded['data'].get('unit_verdicts')
    if not isinstance(verdicts,list):
        raise ValueError('Whole-unit selector submission requires unit_verdicts array')
    for vi, verdict in enumerate(verdicts):
        if not isinstance(verdict,dict):raise ValueError('Invalid selector verdict row')
        checks = verdict.get(check_key, [])
        if not isinstance(checks,list):raise ValueError('Invalid selector check array')
        for ci, check in enumerate(checks):
            if not isinstance(check,dict):raise ValueError('Invalid selector check row')
            observations = check.get('observations')
            if not isinstance(observations,list):raise ValueError('Selector observations must be an array')
            selected = set()
            for oi, observation in enumerate(observations):
                location = f'unit_verdicts[{vi}].{check_key}[{ci}].observations[{oi}]'
                if not isinstance(observation,dict) or set(observation) != {'selector_id'}:
                    raise ValueError('Whole-unit observation must contain only selector_id: '+location)
                sid = observation['selector_id']
                if not isinstance(sid,str) or sid not in lookup:
                    raise ValueError('Unknown whole-unit selector: '+location)
                if sid in selected:raise ValueError('Duplicate whole-unit selector: '+location)
                selected.add(sid)
                unit = units.get(verdict.get('unit_id'), {})
                owner = lookup[sid][owner_key]
                if owner not in unit.get(owners_key, []):
                    raise ValueError('Whole-unit selector is outside this claim own declared references: '+location)
                observations[oi] = {owner_key:owner, 'quote':texts[sid]}
    return expanded


def selection_attestation_fields(bundle, raw):
    if not whole_unit_mode(bundle):return {}
    return {'observation_selection':{'schema':SELECTION_SCHEMA,
        'selector_index_sha256':bundle['wire']['selector_index_sha256'],
        'raw_tool_arguments':copy.deepcopy(raw)}}


def replay_selection_attestation(bundle, payload, *, normalize):
    """Fresh release replays the raw selectors, never trusting expanded quotes."""
    if not whole_unit_mode(bundle):
        if 'observation_selection' in payload:raise ValueError('Literal attestation cannot import selector metadata')
        return {}
    selection = payload.get('observation_selection')
    if (not isinstance(selection,dict) or set(selection) != {'schema','selector_index_sha256','raw_tool_arguments'}
            or selection.get('schema') != SELECTION_SCHEMA
            or selection.get('selector_index_sha256') != bundle['wire']['selector_index_sha256']):
        raise ValueError('Missing or stale whole-unit selection attestation')
    expanded = expand_selector_submission(bundle, selection['raw_tool_arguments'])
    if canonical(normalize(expanded['data'])) != canonical(payload['submission']):
        raise ValueError('Attested canonical observations differ from fresh whole-unit selector expansion')
    return {'observation_selection':copy.deepcopy(selection)}


SELECTOR_INSTRUCTION = (
    ' Explicit whole-unit-selectors/1 mode: base_wire contains ALL original scientific material and renders. '
    'selector_index maps sN to one COMPLETE original source part, or pN to one COMPLETE actual direct premise claim. '
    'The index contains identities/offsets/hashes only; the full text is already in base_wire. '
    'For every minimum-unit observation submit only {selector_id: assigned ID}; never retype quote or owner IDs. '
    'Select ONLY this claim own declared references. Runtime expands the exact complete text without changing punctuation. '
    'This is coarser source location, not stronger scientific proof: independently assess every factual component, '
    'relation, governing negation, qualifier and uncertainty against that full text. All existing duties and '
    'honest negative rules remain unchanged. Do not submit literal-mode observation objects in this mode.'
)
