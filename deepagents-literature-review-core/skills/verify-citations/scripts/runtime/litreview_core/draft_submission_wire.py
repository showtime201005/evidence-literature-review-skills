"""Reversible short obligation IDs and grouped retention tool arguments.

The runtime keeps the alias map; models still receive every actual obligation
definition. Grouping changes serialization only, never inclusion decisions.
"""
import copy
from typing import Literal
from pydantic import Field

from .scientific_records import StrictModel
from .review_artifacts import DraftClaim, ComparisonCell


class RetentionGroup(StrictModel):
    obligation_ids: list[str] = Field(min_length=1)
    status: Literal['included','excluded']
    claim_ids: list[str]
    reason: str = Field(min_length=1)


class GroupedDraftSubmission(StrictModel):
    claims: list[DraftClaim] = Field(min_length=1)
    retention_groups: list[RetentionGroup]
    cells: list[ComparisonCell]


def alias_obligations(packet):
    result=copy.deepcopy(packet)
    originals=[o['id'] for o in packet['obligations']]
    if len(originals)!=len(set(originals)):
        raise ValueError('Duplicate canonical obligation IDs')
    aliases={'o'+str(i+1):oid for i,oid in enumerate(originals)}
    inverse={oid:alias for alias,oid in aliases.items()}
    for obligation in result['obligations']:
        obligation['id']=inverse[obligation['id']]
    # Premise retention is historical evidence from a different responsibility
    # scope. Keep its canonical IDs; only this task's obligations use aliases.
    return result,aliases


def decode_grouped_submission(value,aliases):
    grouped=GroupedDraftSubmission.model_validate(value)
    retention=[]
    seen=set()
    for group in grouped.retention_groups:
        for alias in group.obligation_ids:
            if alias not in aliases:
                raise ValueError('Unknown obligation alias: '+alias)
            if alias in seen:
                raise ValueError('Duplicate obligation disposition: '+alias)
            seen.add(alias)
            retention.append({'obligation_id':aliases[alias],'status':group.status,
                              'claim_ids':list(group.claim_ids),'reason':group.reason})
    if seen!=set(aliases):
        raise ValueError('Missing obligation aliases: '+', '.join(sorted(set(aliases)-seen)))
    return {'claims':[c.model_dump() for c in grouped.claims],'retention':retention,
            'cells':[c.model_dump() for c in grouped.cells]}
