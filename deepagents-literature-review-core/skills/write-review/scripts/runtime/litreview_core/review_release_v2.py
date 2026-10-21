"""Host-only strict replay of the experimental v2 graph and exact delivery.

No model publication root, fabricated identities or v1 phase substitution.
Passed means the declared v2 protocol completed; quality validation stays false.
"""
from __future__ import annotations

import time
from urllib.parse import quote

from .hierarchical_proof import RuntimeIdentity,payload_hash
from .paper_review_v2 import verify_paper_review_v2
from .section_review_v2 import verify_section_review_v2
from .review_artifacts import render_section
from .task_store import canonical


def _target(entry):
    bundle=entry['bundle']
    if bundle.get('schema')=='paper-review-bundle/2':return bundle['payload']['card']
    if bundle.get('schema')=='section-review-bundle/2':return bundle['payload']['section']
    raise ValueError('Only actual v2 review bundles are admissible')


def verify_review_release_v2(result,*,deadline_at=None):
    from .review_workflow_v2 import source_scope_v2
    limit=deadline_at if deadline_at is not None else result.get('deadline_at')
    def deadline():
        if limit is not None and time.monotonic()>=limit:raise TimeoutError('Deadline reached before experimental release')
    deadline()
    if result.get('protocol')!='literature-review-v2':raise ValueError('Explicit experimental v2 protocol required')
    if result.get('publication_verified') is not False or result.get('quality_validated') is not False:
        raise ValueError('Experimental v2 cannot claim publication or quality validation')
    packets,records,sections=result['packets'],result['records'],result['sections']
    inventory=result['source_inventory']
    if inventory!=source_scope_v2(packets,result['questions']):raise ValueError('Original source inventory/version changed')
    pmap={p['paper_id']:p for p in packets};rmap={r['paper_id']:r for r in records}
    if len(rmap)!=len(records) or set(rmap)!=set(pmap):raise ValueError('Every original paper requires its actual complete reader')
    smap={s['section_id']:s for s in sections}
    if not sections or len(smap)!=len(sections):raise ValueError('Unique actual section inventory required')
    reviews=result['reviews']
    if set(reviews)!=set(smap):raise ValueError('Every actual delivered section needs exactly one v2 review')
    identities=result['identities']
    if not isinstance(identities,dict) or any(not isinstance(i,RuntimeIdentity) for i in identities.values()):
        raise ValueError('Release accepts only the actual runtime identity registry, never JSON identities')
    required=result.get('closed_checks_required',False)
    if type(required) is not bool:raise ValueError('Closed-check requirement must be a boolean')
    if required:
        from .closed_scientific_checks import plan_closed_checks,verify_closed_attestation
        closed=result.get('closed_checks',{})
        if set(closed)!=set(smap):raise ValueError('Every delivered section needs its exact closed local checks')
        for sid,entry in reviews.items():
            expected=plan_closed_checks(entry['bundle'],trusted_identities=identities)
            actual=closed[sid]
            if canonical([a['packet'] for a in actual])!=canonical(expected):
                raise ValueError('Closed-check inputs or original responsibility coverage changed')
            for item in actual:
                deadline()
                if not verify_closed_attestation(item['packet'],item['attestation'],trusted_identities=identities)['qualified_for_experiment']:
                    raise ValueError('A negative closed check cannot qualify delivery')
    cards=[s['paper_ids'][0] for s in sections if s['kind']=='paper_card']
    if len(cards)!=len(set(cards)) or set(cards)!=set(pmap):raise ValueError('Missing/duplicate paper card coverage')
    groups=[frozenset(inventory['paper_ids'][i:i+result['group_size']])
            for i in range(0,len(pmap),result['group_size'])]
    comparison_groups=[frozenset(s['paper_ids']) for s in sections if s['kind']=='comparison']
    if len(comparison_groups)!=len(groups) or set(comparison_groups)!=set(groups):raise ValueError('Comparison groups do not cover every assigned paper exactly once')
    if any(s['dimensions']!=result['dimensions'] for s in sections if s['kind']=='comparison'):
        raise ValueError('Comparison dimensions changed from the assigned scope')
    roots=result['root_section_ids']
    if not roots or len(roots)!=len(set(roots)) or not set(roots)<=set(smap):raise ValueError('Actual final roots required')
    if any(smap[r]['kind']!='synthesis' for r in roots):raise ValueError('Final scientific conclusions require actual independently reviewed synthesis')
    if {p for r in roots for p in smap[r]['paper_ids']}!=set(pmap):raise ValueError('Final roots omit original papers')
    edges={}
    for sid,entry in reviews.items():
        if set(entry)!={'bundle','attestation'} or canonical(_target(entry))!=canonical(smap[sid]):
            raise ValueError('Review target does not match its actual delivered artifact')
        children=entry['bundle'].get('children',[])
        child_ids=[_target(child)['section_id'] for child in children]
        if child_ids!=smap[sid]['premise_section_ids'] or len(child_ids)!=len(set(child_ids)):
            raise ValueError('Actual direct premise inventory changed')
        if not set(child_ids)<=set(smap):raise ValueError('Missing current-version premise section')
        edges[sid]=child_ids
    visited,active=set(),set()
    def visit(sid):
        if sid in active:raise ValueError('Cyclic v2 proof dependency')
        if sid in visited:return
        active.add(sid)
        for child in edges[sid]:visit(child)
        active.remove(sid);visited.add(sid)
    for root in roots:visit(root)
    if visited!=set(smap):raise ValueError('Orphan active section lacks a final-root scientific lineage')
    # DAG safety precedes canonical comparison, preventing cyclic JSON recursion.
    gates={}
    for sid in smap:
        deadline();entry=reviews[sid];bundle=entry['bundle']
        for child in bundle.get('children',[]):
            cid=_target(child)['section_id']
            if canonical(child)!=canonical(reviews[cid]):raise ValueError('Parent carries a stale or substituted child proof/version')
        if bundle['schema']=='paper-review-bundle/2':
            p=bundle['payload'];pid=p['source']['paper_id']
            if canonical(p['source'])!=canonical(pmap[pid]) or canonical(p['reader'])!=canonical(rmap[pid]):
                raise ValueError('Paper review omits the current complete original source/reader version')
            gate=verify_paper_review_v2(bundle,entry['attestation'],trusted_identities=identities)
        else:gate=verify_section_review_v2(bundle,entry['attestation'],trusted_identities=identities)
        if gate['status']!='passed' or not gate['qualified_for_experiment']:
            raise ValueError('Negative, unresolved or incomplete scientific review prevents release')
        gates[sid]={'review_id':bundle['review_id'],'bundle_sha256':bundle['payload_sha256'],
            'wire_sha256':bundle['wire_sha256'],'attestation_sha256':entry['attestation']['payload_sha256']}
    deadline()
    return {'schema':'review-v2-release-gate/1','status':'passed',
        'protocol_completed_experimental':True,'publication_verified':False,'quality_validated':False,
        'semantic_judgments_are_model_attestations_not_host_proofs':True,'no_model_publication_root':True,
        'source_inventory_sha256':payload_hash(inventory),'section_hashes':{sid:payload_hash(s) for sid,s in smap.items()},
        'root_section_ids':list(roots),'reviews':gates,'papers':len(pmap),'sections':len(sections)}


def delivery_projection_v2(result):
    """Only mechanical projections; callers must independently run release gate."""
    from .delivery_export import _renders,_source_index,_comparison_csv,_comparison_markdown,_card_projection
    materials={};sections=result.get('sections',[])
    scope={'schema':'review-v2-render-scope/1','paper_ids':[p['paper_id'] for p in result['packets']],
        'section_ids':[s['section_id'] for s in sections],'root_section_ids':result.get('root_section_ids',[]),
        'section_hashes':{s['section_id']:payload_hash(s) for s in sections},
        'source_versions':{p['paper_id']:p['source_sha256'] for p in result['packets']},
        'questions':{q['id']:q for q in result['questions']}}
    for packet in result['packets']:
        materials['original/'+quote(packet['paper_id'],safe='')]=b''.join(p['text'].encode('utf8') for p in packet['parts'])
    for record in result['records']:materials['reader/'+quote(record['paper_id'],safe='')]=record
    text=[];lines=[];offset=0
    for section in sections:
        sid=section['section_id'];render=render_section(section)
        materials['section/'+quote(sid,safe='')]=section
        materials['render/'+quote(sid,safe='')]=render
        text.append(render['text']+'\n\n')
        lines.extend({**line,'start_char':offset+line['start_char'],'end_char':offset+line['end_char']}
                     for line in render['lines'])
        offset+=len(render['text'])+2
    full={'text':''.join(text),'lines':lines}
    materials['delivery/render']=full
    scope['delivery_sha256']=payload_hash(full)
    materials['review/scope']=scope
    projection={'materials':materials}
    renders,full,main=_renders(projection)
    source_index=_source_index(projection,renders)
    table,table_map=_comparison_markdown(projection,source_index)
    cards,card_map=_card_projection(projection,renders)
    return {'scope':scope,'renders':renders,'full':full,'main':main,'source_index':source_index,
            'comparison_csv':_comparison_csv(projection),'comparison_markdown':table,'comparison_map':table_map,
            'cards_markdown':cards,'cards_map':card_map,'originals':
                {pid:materials['original/'+quote(pid,safe='')] for pid in scope['paper_ids']}}
