"""Lossless responsibility aliases; preserve every per-unit scientific verdict.

Only typed identifier positions are translated. Scientific materials, reasons,
dependency attestations and immutable material hashes are never rewritten.
The runtime owns the mapping; no model-supplied alias dictionary is accepted.
"""
from __future__ import annotations

import copy

from .hierarchical_proof import DIMENSIONS


def alias_proof_packet(packet):
    units = sorted({uid for dim in DIMENSIONS for uid in packet['coverage'][dim]})
    # Avoid ambiguity even for externally supplied canonical IDs such as u1.
    reserved = set(units) | set(packet['material_hashes'])
    prefix = 'u'
    while any(prefix + str(i + 1) in reserved for i in range(len(units))):
        prefix = '_' + prefix
    aliases = {prefix + str(i + 1): uid for i, uid in enumerate(units)}
    inverse = {uid: alias for alias, uid in aliases.items()}
    wire = copy.deepcopy(packet)
    wire['coverage'] = {dim: [inverse[uid] for uid in packet['coverage'][dim]] for dim in DIMENSIONS}
    wire['responsibility_aliases'] = aliases.copy()
    wire['responsibility_encoding'] = 'proof-unit-aliases/1'
    return wire, aliases


def decode_proof_submission(value, aliases):
    """Decode already schema-validated fields; canonical IDs remain compatible.

    Unknown IDs and duplicates are intentionally retained for the unchanged
    canonical coverage/verdict validator to reject, including alias+canonical
    duplicates. Text is copied verbatim, never searched/replaced.
    """
    result = copy.deepcopy(value)
    resolve = lambda uid: aliases.get(uid, uid)
    result['checked'] = {dim: [resolve(uid) for uid in ids]
                         for dim, ids in result['checked'].items()}
    for verdict in result['verdicts']:
        verdict['unit_id'] = resolve(verdict['unit_id'])
    for issue in result['issues']:
        issue['unit_ids'] = [resolve(uid) for uid in issue['unit_ids']]
    return result
