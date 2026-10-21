"""Deterministic citation/disposition views of already delivered proof materials.

No new evidence, scientific judgment or dependency approval is produced. Raw
sources, canonical materials and their gate hashes stay in the task unchanged.
The derived view makes the exact permitted supporting excerpts readable beside
each claim, while full originals remain available for counterevidence/omissions.
"""
from __future__ import annotations

import copy
from hashlib import sha256
from urllib.parse import quote

from .hierarchical_proof import payload_hash


def _raw(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode('utf-8')
    raise ValueError('Delivered original source must be exact UTF-8 text or bytes')


def _checked_materials(packet):
    materials, hashes = packet.get('materials'), packet.get('material_hashes')
    if not isinstance(materials, dict) or not isinstance(hashes, dict) or set(materials) != set(hashes):
        raise ValueError('Citation view requires every and only the hash-bound delivered material')
    for mid, value in materials.items():
        expected = hashes[mid]
        if mid.startswith('original/'):
            matches = sha256(_raw(value)).hexdigest() == expected
        else:
            # node_payload decodes original byte materials for wire delivery;
            # their raw-byte hashes intentionally differ from JSON-string hashes.
            matches = payload_hash(value) == expected or (
                isinstance(value, str) and sha256(value.encode('utf-8')).hexdigest() == expected)
        if not matches:
            raise ValueError('Delivered material hash differs before citation view: ' + mid)
    return materials


def build_citation_view(packet):
    """Use only this packet; never fetch an absent original or another claim.

    Cross-group/assembly tasks can legitimately have no original bytes. Their
    rows explicitly say original_not_delivered and contain no invented excerpt;
    the original premise/child-proof contract still governs those tasks.
    """
    materials = _checked_materials(packet)
    coverage = packet.get('coverage', {})
    claims = {}
    for value in materials.values():
        if not isinstance(value, dict) or not isinstance(value.get('claim_id'), str):
            continue
        if not isinstance(value.get('text'), str) or not isinstance(value.get('evidence_refs'), list):
            continue
        cid = value['claim_id']
        if cid in claims and claims[cid] != value:
            raise ValueError('Conflicting delivered claim material: ' + cid)
        claims[cid] = value

    locators = {}
    required = {'paper_id', 'part_id', 'start_byte', 'end_byte', 'source_sha256', 'text_sha256'}
    for mid, value in materials.items():
        if not mid.startswith('locator/'):
            continue
        if not isinstance(value, dict) or not required <= set(value):
            raise ValueError('Incomplete delivered source locator: ' + mid)
        if any(not isinstance(value[key], str) or not value[key] for key in ('paper_id', 'part_id')):
            raise ValueError('Invalid delivered source locator identity: ' + mid)
        ref = value['paper_id'] + '/' + value['part_id']
        if ref in locators and locators[ref] != value:
            raise ValueError('Conflicting delivered source locator: ' + ref)
        locators[ref] = value

    def declared_part(ref):
        if not isinstance(ref, str) or len(ref.split('/')) != 2 or not all(ref.split('/')):
            raise ValueError('Malformed declared evidence reference')
        pid, part_id = ref.split('/')
        source_id = 'original/' + quote(pid, safe='')
        if source_id not in materials:
            return {'ref': ref, 'availability': 'original_not_delivered',
                    'text': None, 'source_material_id': source_id}
        locator = locators.get(ref)
        if locator is None:
            raise ValueError('Declared source part lacks a delivered locator: ' + ref)
        raw = _raw(materials[source_id])
        if sha256(raw).hexdigest() != locator['source_sha256']:
            raise ValueError('Locator names a different original source version: ' + ref)
        start, end = locator['start_byte'], locator['end_byte']
        if (type(start) is not int or type(end) is not int or start < 0
                or end <= start or end > len(raw)):
            raise ValueError('Locator escapes delivered original bytes: ' + ref)
        excerpt = raw[start:end]
        if sha256(excerpt).hexdigest() != locator['text_sha256']:
            raise ValueError('Locator text hash differs from actual original bytes: ' + ref)
        try:
            text = excerpt.decode('utf-8')
        except UnicodeError as exc:
            raise ValueError('Locator cuts a UTF-8 code point: ' + ref) from exc
        return {'ref': ref, 'availability': 'delivered_exact_part',
                'source_material_id': source_id, 'paper_id': pid, 'part_id': part_id,
                'start_byte': start, 'end_byte': end, 'text': text}

    def claim_row(cid):
        claim = claims.get(cid)
        if claim is None:
            return {'claim_id': cid, 'availability': 'claim_material_not_delivered',
                    'text': None, 'declared_evidence_refs': [], 'declared_parts': []}
        return {'claim_id': cid, 'availability': 'delivered_claim', 'text': claim['text'],
                'declared_evidence_refs': list(claim['evidence_refs']),
                'declared_parts': [declared_part(ref) for ref in claim['evidence_refs']]}

    targets = list(coverage.get('claims', []))
    dispositions = []
    for uid in coverage.get('obligations', []):
        value = materials.get(uid)
        if not isinstance(value, dict) or 'definition' not in value:
            dispositions.append({'unit_id': uid, 'availability': 'obligation_material_not_delivered'})
            continue
        disposition = value.get('disposition')
        named = []
        if value['definition'].get('kind') == 'full_source_review':
            for cid in value['definition'].get('claim_ids', []):
                if cid not in targets:
                    targets.append(cid)
        if disposition is not None:
            if not isinstance(disposition, dict) or not isinstance(disposition.get('claim_ids'), list):
                raise ValueError('Malformed delivered obligation disposition: ' + uid)
            sid = value.get('section_id')
            if not isinstance(sid, str) or not sid:
                raise ValueError('Named obligation prose lacks its section identity: ' + uid)
            for local_id in disposition['claim_ids']:
                if not isinstance(local_id, str) or not local_id:
                    raise ValueError('Invalid named claim in delivered obligation: ' + uid)
                cid = sid + '/' + local_id
                named.append({'claim_id': cid,
                    'availability': 'delivered_claim' if cid in claims else 'claim_material_not_delivered',
                    'text': claims[cid]['text'] if cid in claims else None,
                    'evidence_refs': list(claims[cid]['evidence_refs']) if cid in claims else []})
                if cid not in targets:
                    targets.append(cid)
        dispositions.append({'unit_id': uid, 'availability': 'delivered_obligation',
            'definition': copy.deepcopy(value['definition']),
            'original_finding': copy.deepcopy(value.get('original_finding')),
            'disposition': copy.deepcopy(disposition), 'named_claims': named})

    view = {'schema': 'proof-citation-view/1',
        'base_task_sha256': payload_hash(packet),
        'canonical_material_hashes_sha256': payload_hash(packet['material_hashes']),
        'support_policy': 'Only each claim row\'s declared parts may establish its local citation support. '
            'Other full-source/reader/premise materials can reveal contradictions, missing qualifications '
            'and omissions, but cannot repair an absent declared citation. Missing original text is '
            'explicitly unavailable; cross-group/assembly duties use their actual supplied premises '
            'and dependencies rather than pretending to reread originals.',
        'disposition_policy': 'An included obligation must survive in its own disposition\'s named_claims. '
            'Other card prose is context, not silently an additional named preservation claim. '
            'A null disposition does not waive the canonical complete-source/integration responsibility.',
        'claim_rows': [claim_row(cid) for cid in targets],
        'obligation_rows': dispositions}
    view['view_sha256'] = payload_hash(view)
    return view


def attach_citation_view(packet):
    """Add a deterministic view without changing canonical materials/coverage."""
    if 'citation_view' in packet:
        raise ValueError('Caller-supplied citation views are forbidden')
    result = copy.deepcopy(packet)
    result['citation_view'] = build_citation_view(packet)
    return result
