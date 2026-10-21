"""Lossless source-table wire encoding for canonical native draft packets.

Scientific values, obligations, premises and original byte coordinates are not
summarized. A per-paper version dictionary removes repeated source hashes and
column rows remove repeated field names. Restore must reproduce the exact
canonical JSON hash. This encoding grants no scientific approval.
"""
from __future__ import annotations

import copy
from hashlib import sha256

from .task_store import canonical

SCHEMA = 'review-draft-wire/1'


def project_draft_packet(packet):
    if not isinstance(packet, dict) or packet.get('schema') != 'review-draft-packet/1':
        raise ValueError('Expected canonical review-draft-packet/1')
    versions, version_indices, tables = [], {}, {}
    for ref, unit in packet['sources'].items():
        if (not isinstance(unit, dict) or not isinstance(unit.get('paper_id'), str)
                or not isinstance(unit.get('part_id'), str)
                or ref != unit['paper_id'] + '/' + unit['part_id']):
            raise ValueError('Source table key must match its actual paper/part IDs')
        pair = (unit['paper_id'], unit['source_sha256'])
        if pair not in version_indices:
            version_indices[pair] = len(versions)
            versions.append(list(pair))
        columns = tuple(sorted(key for key in unit if key not in ('paper_id', 'source_sha256')))
        tables.setdefault(columns, []).append([version_indices[pair]] + [copy.deepcopy(unit[key]) for key in columns])
    result = {'schema': SCHEMA, 'canonical_sha256': sha256(canonical(packet)).hexdigest(),
        'packet': {key: copy.deepcopy(value) for key, value in packet.items() if key != 'sources'},
        'source_encoding': {'paper_version_columns': ['paper_id', 'source_sha256'],
            'paper_versions': versions,
            'tables': [{'columns': ['paper_version_index', *columns], 'rows': rows}
                       for columns, rows in tables.items()]}}
    if canonical(restore_draft_packet(result)) != canonical(packet):
        raise ValueError('Lossless draft projection failed canonical roundtrip')
    return result


def restore_draft_packet(wire):
    if not isinstance(wire, dict) or set(wire) != {'schema', 'canonical_sha256', 'packet', 'source_encoding'} or wire['schema'] != SCHEMA:
        raise ValueError('Unsupported or malformed draft wire encoding')
    packet = copy.deepcopy(wire['packet'])
    if not isinstance(packet, dict) or packet.get('schema') != 'review-draft-packet/1' or 'sources' in packet:
        raise ValueError('Wire packet must omit only the encoded sources field')
    encoding = wire['source_encoding']
    if (not isinstance(encoding, dict) or set(encoding) != {'paper_version_columns', 'paper_versions', 'tables'}
            or encoding['paper_version_columns'] != ['paper_id', 'source_sha256']):
        raise ValueError('Malformed source table dictionary')
    versions = encoding['paper_versions']
    if not isinstance(versions, list) or any(not isinstance(pair, list) or len(pair) != 2
            or any(not isinstance(value, str) or not value for value in pair) for pair in versions):
        raise ValueError('Malformed paper/version rows')
    if len({tuple(pair) for pair in versions}) != len(versions):
        raise ValueError('Duplicate paper/version dictionary entry')
    sources = {}
    for table in encoding['tables']:
        if not isinstance(table, dict) or set(table) != {'columns', 'rows'}:
            raise ValueError('Malformed source table')
        columns = table['columns']
        if (not isinstance(columns, list) or not columns or columns[0] != 'paper_version_index'
                or any(not isinstance(column, str) or not column for column in columns)
                or len(set(columns)) != len(columns) or 'part_id' not in columns
                or set(columns) & {'paper_id', 'source_sha256'}):
            raise ValueError('Malformed source table columns')
        if not isinstance(table['rows'], list):
            raise ValueError('Malformed source table rows')
        for row in table['rows']:
            if (not isinstance(row, list) or len(row) != len(columns) or type(row[0]) is not int
                    or not 0 <= row[0] < len(versions)):
                raise ValueError('Malformed source table row or version index')
            pid, version = versions[row[0]]
            unit = {'paper_id': pid, 'source_sha256': version, **dict(zip(columns[1:], row[1:]))}
            if not isinstance(unit['part_id'], str) or not unit['part_id']:
                raise ValueError('Malformed source part ID')
            ref = pid + '/' + unit['part_id']
            if ref in sources:
                raise ValueError('Duplicate source part in projection')
            sources[ref] = unit
    packet['sources'] = sources
    if sha256(canonical(packet)).hexdigest() != wire['canonical_sha256']:
        raise ValueError('Draft wire content does not reconstruct its exact canonical SHA256')
    return packet
