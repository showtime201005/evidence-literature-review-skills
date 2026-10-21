"""Determine revision closure and reuse only unchanged, passed proof executions."""
from .hierarchical_proof import payload_hash, _coverage


def revision_targets(bundle,nodes):
    direct={}
    for nid,node in nodes.items():
        p=node['payload']
        if p['status']=='passed' and not p['issues']:
            continue
        spec=bundle['node_specs'][nid]
        targets=[spec['section_id']] if spec['section_id'] else bundle['root_section_ids']
        for sid in targets:
            direct.setdefault(sid,[]).append({'node_id':nid,'kind':spec['kind'],
                'status':p['status'],'reason':p['reason'],'issues':p['issues']})
    if not direct:
        raise ValueError('No semantic rejection to revise; transport failures require separate handling')
    sections={s['section_id']:s for s in bundle['materials'].values()
              if isinstance(s,dict) and s.get('schema')=='review-section/1'}
    affected=set(direct)
    while True:
        more={sid for sid,s in sections.items() if set(s['premise_section_ids'])&affected}
        if more<=affected:
            break
        affected.update(more)
    return direct,affected


def reusable_nodes(bundle,old_nodes):
    """Reuse within this cold run only; never reseal or fabricate an execution."""
    reused={}
    pending=dict(bundle['node_specs'])
    while pending:
        progressed=False
        for nid,spec in list(pending.items()):
            if any(dep in pending for dep in spec['dependencies']):
                continue
            pending.pop(nid)
            progressed=True
            old=old_nodes.get(nid)
            if old is None:
                continue
            p=old['payload']
            # Sealed nodes canonicalize coverage order. Planner order is not a
            # scientific difference; validate and normalize the expected set
            # without dropping duplicate IDs or altering the original proof.
            expected_coverage=_coverage(spec['coverage'],'reusable node coverage')
            expected={dep:reused[dep]['payload_hash'] for dep in spec['dependencies'] if dep in reused}
            if (old['payload_hash']==payload_hash(p) and p['status']=='passed' and not p['issues']
                    and p['node_id']==nid and p['kind']==spec['kind']
                    and p['inputs']==spec['inputs'] and p['coverage']==expected_coverage
                    and set(expected)==set(spec['dependencies']) and p['dependencies']==expected):
                reused[nid]=old
        if not progressed:
            raise ValueError('Cyclic proof graph')
    return reused
