"""Recheck optional literal witnesses for every final source proof.

This supplements the hierarchical proof gate; exact quotations do not establish
semantic entailment. Callers must still use trusted runtime identities and run
the full proof gate. JSON artifacts alone never establish runtime provenance.
"""
from .hierarchical_proof import payload_hash
from .proof_planner import node_payload
from .proof_quote_wire import (SourceWitnessWireSubmission, adapt_source_witness_wire,
                               unwrap_source_witness_tool_arguments)
from .proof_submission_wire import alias_proof_packet, decode_proof_submission


def verify_source_witness_audits(bundle, nodes, submissions):
    checked={}
    for node_id,spec in bundle['node_specs'].items():
        if spec['kind']!='source':
            continue
        if spec['dependencies']:
            raise ValueError('Source witness audit requires original dependency-free source nodes')
        if node_id not in nodes or node_id not in submissions:
            raise ValueError('Missing final source node or witness submission: '+node_id)
        submission=submissions[node_id]
        audit=submission.get('quote_witness')
        if not isinstance(audit,dict) or 'original_tool_arguments' not in audit:
            raise ValueError('Missing source quote witness audit: '+node_id)
        packet=node_payload(bundle,node_id,{})
        _,aliases=alias_proof_packet(packet)
        raw=audit['original_tool_arguments']
        wire=SourceWitnessWireSubmission.model_validate(
            unwrap_source_witness_tool_arguments(raw)).model_dump(exclude_none=True)
        decoded=decode_proof_submission(wire,aliases)
        expected=adapt_source_witness_wire(packet,decoded,expected_material_hashes=spec['inputs'])
        if audit!={**expected,'original_tool_arguments':raw}:
            raise ValueError('Source witness audit differs from original arguments and current materials: '+node_id)
        verdict=expected['literal_validation']['proof_submission']
        if {key:value for key,value in submission.items() if key!='quote_witness'}!=verdict:
            raise ValueError('Saved proof submission differs from literal witness verdict: '+node_id)
        payload=nodes[node_id]['payload']
        if (nodes[node_id]['payload_hash']!=payload_hash(payload) or payload['status']!='passed'
                or verdict['status']!='passed' or verdict['issues'] or expected['semantic_negative_detected']
                or payload['reason']!=verdict['reason'] or payload['issues']!=verdict['issues']
                or {key:set(ids) for key,ids in payload['coverage'].items()}!=
                   {key:set(ids) for key,ids in verdict['checked'].items()}):
            raise ValueError('Source node does not match its passed witness judgment: '+node_id)
        checked[node_id]={'proof_hash':nodes[node_id]['payload_hash'],'witness_hash':payload_hash(audit),
                          'literal_checks_completed':True}
    if not checked:
        raise ValueError('No source proofs available for required witness audit')
    return {'schema':'source-witness-delivery-audit/1','source_nodes':checked,
            'literal_checks_completed':True,'semantic_entailment_proven':False}
