"""A comparison is an independently verifiable artifact, not report prose."""
import copy
from .artifacts import canonical,envelope,identifier
from .contracts import validate
from .review import draft_from_sections,verification_packet,gate
from .workflow import payload_hash,need


def comparison_draft(comparison):
    validate(comparison)
    need(comparison['artifact_type']=='ComparisonSet' and comparison['schema_version']=='2.0.0',
         'WRONG_ARTIFACT_TYPE','Independent comparison verification requires ComparisonSet v2')
    p=comparison['payload'];claims={c['claim_id']:c for c in p['claims']}
    sections=[{'heading':'Comparison assertions','claims':copy.deepcopy(p['claims'])}]
    # Verify all cell metadata too, not only a separate list of base claims.
    for cell in p['cells']:
        text=canonical({k:v for k,v in cell.items() if k!='verification_status'})
        refs=sorted({eid for cid in cell['material_refs'] for eid in claims[cid]['evidence_refs']}|set(cell['counterevidence_refs']))
        c=dict(claim_id=identifier('cell_assertion',[cell['cell_id'],text]),text=text,
               claim_type='synthesis',evidence_refs=refs,support_status='unverified')
        sections.append({'heading':'Cell '+cell['cell_id'],'claims':[c]})
    for conflict in p['contradiction_candidates']:
        text=canonical(conflict)
        refs=sorted({eid for cid in conflict['claim_refs'] for eid in claims[cid]['evidence_refs']})
        sections.append({'heading':'Disagreement','claims':[dict(claim_id=identifier('conflict',conflict),
            text=text,claim_type='synthesis',evidence_refs=refs,support_status='unverified')]})
    metadata={'question':p['question'],'paper_ids':p['paper_ids'],'dimensions':p['dimensions'],'unknowns':p['unknowns']}
    sections.append({'heading':'Scope and unresolved questions','claims':[dict(claim_id=identifier('comparison_scope',metadata),
        text=canonical(metadata),claim_type='synthesis',evidence_refs=sorted({e for c in p['claims'] for e in c['evidence_refs']}),support_status='unverified')]})
    context=comparison.get('producer',{}).get('context_id')
    need(context,'PROVENANCE_REQUIRED','Comparison producer.context_id is required before independent verification')
    return draft_from_sections(sections,context)


def comparison_packet(comparison,evidence,corpus,index,max_chars=100000):
    packet=verification_packet(comparison_draft(comparison),evidence,corpus,index,max_chars)
    packet['comparison_target']={'artifact_id':comparison['artifact_id'],'payload_hash':payload_hash(comparison)}
    packet['rules']+=' Check cell proposition, relation, numeric conditions, comparability and counterevidence; a cell status is a conclusion, not a verifier verdict. Return a VerificationSet targeting the projected draft. Do not set cell verification_status to verified.'
    need(len(canonical(packet))<=max_chars,'VERIFICATION_PACKET_TOO_LARGE','Comparison packet exceeds the requested character budget')
    return packet


def bind_verification(comparison,verification,evidence,corpus,index):
    result=envelope('ComparisonVerification',dict(target_artifact_id=comparison['artifact_id'],target_hash=payload_hash(comparison),
        review_verification=verification),producer=verification.get('producer'),schema_version='2.0.0')
    comparison_gate(comparison,evidence,corpus,index,result)
    return result


def comparison_gate(comparison,evidence,corpus,index,verification):
    draft=comparison_draft(comparison)
    need(verification is not None,'UNVERIFIED_MATRIX','Comparison needs its own independent verification record')
    validate(verification)
    need(verification['artifact_type']=='ComparisonVerification','WRONG_ARTIFACT_TYPE','Expected ComparisonVerification')
    p=verification['payload']
    need(p['target_artifact_id']==comparison['artifact_id'] and p['target_hash']==payload_hash(comparison),
         'STALE_VERIFICATION','Comparison metadata or content changed after verification')
    result=gate(draft,evidence,corpus,index,p['review_verification'])
    return dict(result,artifact_type='ComparisonSet',target_hash=payload_hash(comparison))
