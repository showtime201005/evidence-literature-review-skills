"""Versioned reversible metadata rows; scientific text/render stay unchanged."""
import copy
import re

SCHEMA = 'paper-review-wire/2.1'
_OPAQUE = re.compile(r'(?:[0-9a-f]{64}|e_[0-9a-f]{24}|s_[0-9a-f]{24}(?:/.*)?|[^/\s]+:f_[^/\s]+|(?:reader|writer)-[0-9a-f-]{36})\Z')


def _rows(value):
    if isinstance(value, dict):
        return {k: _rows(v) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) >= 3 and all(isinstance(v, dict) and set(v) == set(value[0]) for v in value):
            columns = sorted(value[0])
            return {'$columns': columns, '$rows': [[_rows(v[k]) for k in columns] for v in value]}
        return [_rows(v) for v in value]
    return copy.deepcopy(value)


def _restore_rows(value):
    if isinstance(value, dict):
        if '$columns' in value or '$rows' in value:
            if set(value) != {'$columns', '$rows'}:
                raise ValueError('Malformed row envelope')
            cols, rows = value['$columns'], value['$rows']
            if (not isinstance(cols, list) or not cols or any(not isinstance(k, str) for k in cols)
                    or len(cols) != len(set(cols))):
                raise ValueError('Duplicate or invalid row columns')
            if not isinstance(rows, list) or len(rows) < 3 or any(not isinstance(r, list) or len(r) != len(cols) for r in rows):
                raise ValueError('Malformed row lengths')
            return [{k: _restore_rows(v) for k, v in zip(cols, row)} for row in rows]
        return {k: _restore_rows(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_restore_rows(v) for v in value]
    return copy.deepcopy(value)


def compact_paper_wire_v21(legacy):
    if legacy.get('schema') != 'paper-review-wire/2':
        raise ValueError('Only the explicit text-table v2 format can be projected')
    values = set()
    def gather(v):
        if isinstance(v, dict):
            for k, x in v.items():
                values.add(k)
                gather(x)
        elif isinstance(v, list):
            for x in v: gather(x)
        elif isinstance(v, str): values.add(v)
    gather(legacy['objects'])
    prefix = '~i'
    while any(v.startswith(prefix) for v in values):
        prefix += '_'
    forward, inverse = {}, {}
    def alias(text):
        if not _OPAQUE.fullmatch(text): return text
        if text not in forward:
            key = prefix + str(len(forward) + 1)
            forward[text], inverse[key] = key, text
        return forward[text]
    def encode(v, path=()):
        if path == ('render', 'text'):
            return copy.deepcopy(v)  # Entire readable render, verbatim.
        if isinstance(v, dict): return {alias(k): encode(x, path + (k,)) for k, x in v.items()}
        if isinstance(v, list): return [encode(x, path) for x in v]
        return alias(v) if isinstance(v, str) else copy.deepcopy(v)
    return {'schema': SCHEMA, 'opaque_alias_prefix': prefix, 'opaque_id_index': inverse,
            'text_table': copy.deepcopy(legacy['text_table']), 'objects': _rows(encode(legacy['objects']))}


def expand_paper_wire_v21(wire):
    if not isinstance(wire, dict) or set(wire) != {'schema', 'opaque_alias_prefix', 'opaque_id_index', 'text_table', 'objects'} or wire['schema'] != SCHEMA:
        raise ValueError('Invalid metadata-row wire envelope')
    index, prefix = wire['opaque_id_index'], wire['opaque_alias_prefix']
    if not isinstance(prefix, str) or not prefix.startswith('~i') or not isinstance(index, dict):
        raise ValueError('Invalid opaque alias index')
    if (any(not isinstance(k, str) or not re.fullmatch(re.escape(prefix) + r'[1-9][0-9]*', k)
            or not isinstance(v, str) or not _OPAQUE.fullmatch(v) or v.startswith(prefix) for k, v in index.items())
            or len(set(index.values())) != len(index)):
        raise ValueError('Duplicate or invalid opaque aliases')
    used = set()
    def original(text):
        if text.startswith(prefix):
            if text not in index: raise ValueError('Unknown opaque alias reference')
            used.add(text)
            return index[text]
        return text
    def decode(v, path=()):
        if path == ('render', 'text'): return copy.deepcopy(v)
        if isinstance(v, dict):
            pairs = [(original(k), decode(x, path + (original(k),))) for k, x in v.items()]
            if len({k for k, _ in pairs}) != len(pairs): raise ValueError('Alias restoration collides with an existing key')
            return dict(pairs)
        if isinstance(v, list): return [decode(x, path) for x in v]
        return original(v) if isinstance(v, str) else copy.deepcopy(v)
    objects = decode(_restore_rows(wire['objects']))
    if used != set(index): raise ValueError('Unused opaque aliases')
    return {'schema': 'paper-review-wire/2', 'text_table': copy.deepcopy(wire['text_table']), 'objects': objects}
