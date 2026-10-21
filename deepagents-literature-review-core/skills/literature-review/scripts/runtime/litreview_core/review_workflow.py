"""Complete research DAG driven through an injected native task coordinator.

Infrastructure assigns bounded memberships, versions and dependencies. Scientific
content is produced and checked by skill-loaded native workers. ``dispatch`` must
run the real native coordinator; this module never invokes a worker graph itself.
Semantic repairs are bounded and preserve all earlier adverse attestations.
"""
from __future__ import annotations

import json

from .draft_worker import draft_worker
from .reader_worker import reader_worker
from .proof_worker import proof_worker
from .review_artifacts import draft_packet, inference_packet
from .proof_planner import plan_review
from .hierarchical_proof import RuntimeIdentity, payload_hash, verify_dependency_closure, verify_proof
from .review_repair import revision_targets, reusable_nodes


class ReviewWorkflow:
    def __init__(self, store, packets, questions, *, group_size=4,
                 dimensions=('研究設計與族群','主要結果與不確定性','適用條件與限制'),
                 token_counter=None, max_repairs=2, proof_max_units=16, merge_full_source=False,
                 source_quote_witness=False, early_card_verification=False):
        if not 2 <= group_size <= 8:
            raise ValueError('Native review group size must be 2..8')
        self.store,self.packets,self.questions=store,packets,questions
        self.group_size,self.dimensions=group_size,dimensions
        self.token_counter=token_counter
        if type(source_quote_witness) is not bool:
            raise ValueError('source_quote_witness must be boolean')
        self.source_quote_witness=source_quote_witness
        if type(early_card_verification) is not bool:
            raise ValueError('early_card_verification must be boolean')
        self.early_card_verification=early_card_verification
        if type(proof_max_units) is not int or not 1 <= proof_max_units <= 128:
            raise ValueError('Proof unit limit must be an integer in 1..128')
        self.proof_max_units=proof_max_units
        if type(merge_full_source) is not bool:
            raise ValueError('merge_full_source must be an explicit boolean')
        self.merge_full_source=merge_full_source
        self.identities,self.nodes,self.submissions={},{},{}
        self.bundle=None
        self.proof_tickets={}
        if not 0<=max_repairs<=2:
            raise ValueError('Semantic repair rounds must be 0..2')
        self.max_repairs=max_repairs
        self.revisions={}
        self.repair_history=[]
        self.repair_rounds_used=0
        self.early_card_history=[]
        self.early_card_bundles={}
        self.early_proof_nodes={}
        self._proof_ticket_bundles={}
        self._proof_node_tickets={}
        self._early_qualified={}

    def _register_writer(self, identity, ticket):
        row=next(r for r in self.store.status() if r['id']==ticket)
        self.identities[identity.context_id]=RuntimeIdentity(
            execution_id=identity.context_id,context_id=identity.context_id,role=identity.role,
            input_hashes={ticket:row['input_hash']},output_hashes={ticket:row['output_hash']},
            task_call_id=identity.task_tool_call_id,parent_context_id=identity.coordinator_context_id)

    def factory(self, identity, description):
        request=json.loads(description)
        if set(request)!= {'ticket'}:
            raise ValueError('Delegate exactly one supplied ticket')
        ticket=request['ticket']
        if identity.role in ('reader','writer','comparer'):
            def accepted(ticket, artifact, receipt):
                self._register_writer(identity,ticket)
            if identity.role=='reader':
                return reader_worker(self.store,identity,ticket,on_accepted=accepted)
            return draft_worker(self.store,identity,ticket,on_accepted=accepted,
                                revision=self.revisions.get(ticket))
        lease=self.store.claim(ticket,identity.role,identity.context_id)
        node_id=lease['payload']['node_id']
        try:
            # Early papers have different mini plans. A running task must stay
            # bound to its ticket's plan, never a shared mutable self.bundle.
            bundle=self._proof_ticket_bundles.get(ticket,self.bundle)
            if bundle is None:
                raise ValueError('Proof ticket has no runtime-bound bundle')
            spec=bundle['node_specs'][node_id]
            dependencies={dep:self.nodes[dep] for dep in spec['dependencies']}
            def save(node,execution,submission):
                self.nodes[node_id]=node
                self.identities[execution.execution_id]=execution
                self.submissions[node_id]=submission
                digest=self.store.put({'node':node,'submission':submission})
                if node['payload']['status']=='passed':
                    return self.store.accept(ticket,identity.context_id,lease['lease'],node,
                                      validator=lambda a,b:None)
                else:
                    self.store.fail(ticket,identity.context_id,lease['lease'],
                                    {'code':'VERIFICATION_ISSUES','attestation_hash':digest})
            def finish(actual_identity,receipt):
                row=next(r for r in self.store.status() if r['id']==ticket)
                if row['status']=='running':
                    self.store.fail(ticket,identity.context_id,lease['lease'],
                                    {'reason':receipt.get('error',receipt.get('reason','incomplete'))})
            builder=proof_worker
            if self.source_quote_witness and spec['kind']=='source':
                from .proof_quote_worker import source_witness_worker
                builder=source_witness_worker
            return builder(bundle,node_id,dependencies,identity,save=save,on_finish=finish,
                proof_nodes={nid:node for nid,node in self.nodes.items() if nid in bundle['node_specs']},
                proof_identities=self.identities)
        except Exception as exc:
            self.store.fail(ticket,identity.context_id,lease['lease'],{'reason':str(exc)})
            raise

    def _outputs(self,tickets):
        rows={r['id']:r for r in self.store.status()}
        if any(rows[t]['status']!='accepted' for t in tickets):
            raise RuntimeError('Research stage incomplete; rejected scientific work requires revision')
        return [self.store.get(rows[t]['output_hash']) for t in tickets]

    def _early_snapshot(self,bundles,cards,*,attempt,status,failed_papers=(),error=None):
        """Content-address complete mini contexts and every actual submission.

        UTF-8 encoding wrappers preserve raw source bytes exactly. These host
        archives are provenance, never authenticated identities to import.
        """
        mini_hashes={}
        current={nid for b in bundles.values() for nid,s in b['node_specs'].items() if s['kind']!='root'}
        for pid,bundle in bundles.items():
            capsule={key:value for key,value in bundle.items() if key!='materials'}
            capsule['material_encoding']='raw-utf8-wrapper/1; all other values are canonical JSON'
            capsule['materials']={mid:{'kind':'raw_utf8','text':value.decode('utf-8'),'sha256':payload_hash(value)}
                if isinstance(value,bytes) else {'kind':'json','value':value,'sha256':payload_hash(value)}
                for mid,value in bundle['materials'].items()}
            mini_hashes[pid]=self.store.put(capsule)
        identities={eid:{'execution_id':i.execution_id,'context_id':i.context_id,'role':i.role,
            'input_hashes':dict(i.input_hashes),'dependency_hashes':dict(i.dependency_hashes),
            'output_hashes':dict(i.output_hashes),'task_call_id':i.task_call_id,
            'parent_context_id':i.parent_context_id,
            'ancestor_context_ids':list(i.ancestor_context_ids),'run_id':i.run_id,
            'delivered_dependency_receipt_hashes':dict(i.delivered_dependency_receipt_hashes)}
            for eid,i in self.identities.items()}
        snapshot=self.store.put({'schema':'early-card-proof-snapshot/1','attempt':attempt,
            'status':status,'mini_bundle_hashes':mini_hashes,'cards':cards,
            'nodes':{nid:self.nodes[nid] for nid in current if nid in self.nodes},
            'submissions':{nid:self.submissions[nid] for nid in current if nid in self.submissions},
            'runtime_identity_provenance':{'trust':'Unauthenticated archive; never import as runtime trust','identities':identities},
            'failed_paper_ids':sorted(failed_papers),'error':error})
        row={'phase':'early_cards','attempt':attempt,'status':status,'snapshot_hash':snapshot,
            'mini_bundle_hashes':mini_hashes,'failed_paper_ids':sorted(failed_papers),
            'repair_rounds_used':self.repair_rounds_used}
        self.early_card_history.append(row)
        return row

    def _early_tickets(self,bundle):
        """Reuse real passed nodes or existing unstarted tickets; no approvals."""
        reused=reusable_nodes(bundle,self.nodes)
        remaining={nid:s for nid,s in bundle['node_specs'].items() if s['kind']!='root' and nid not in reused}
        rows={row['id']:row for row in self.store.status()}
        current={}
        while remaining:
            known=set(reused)|set(current)
            ready=[nid for nid,s in remaining.items() if set(s['dependencies'])<=known]
            if not ready:
                raise ValueError('Early proof task dependency cycle')
            for nid in ready:
                spec=remaining.pop(nid)
                old=self._proof_node_tickets.get(nid)
                if old is not None:
                    if self._proof_ticket_bundles[old]['node_specs'][nid]!=spec:
                        raise ValueError('An existing early proof ticket changed its immutable specification')
                    if rows[old]['status']!='pending':
                        raise RuntimeError('Early proof has no reusable accepted execution or unstarted ticket: '+nid)
                    ticket=old
                else:
                    dependencies=[current[d] if d in current else self._proof_node_tickets[d]
                        for d in spec['dependencies'] if d in current or d in self._proof_node_tickets]
                    ticket=self.store.create(spec['role'],{'node_id':nid},dependencies=dependencies,max_attempts=1)
                    self._proof_node_tickets[nid]=ticket
                    self._proof_ticket_bundles[ticket]=bundle
                current[nid]=ticket
        return current

    async def _qualify_cards(self,dispatch,cards,writer_tickets,records):
        """Early complete-card closure; the original caller deadline is shared."""
        rmap={r['paper_id']:r for r in records}
        pmap={p['paper_id']:p for p in self.packets}
        ordered=[p['paper_id'] for p in self.packets]
        current={card['paper_ids'][0]:card for card in cards}
        writers={pid:ticket for pid,ticket in zip(ordered,writer_tickets)}
        attempt=0
        while True:
            bundles={pid:plan_review([current[pid]],[pmap[pid]],[rmap[pid]],
                token_counter=self.token_counter,max_scientific_units=self.proof_max_units,
                merge_full_source=self.merge_full_source) for pid in ordered}
            versions={pid:(payload_hash(current[pid]),payload_hash(pmap[pid]),payload_hash(rmap[pid])) for pid in ordered}
            self.early_card_bundles=bundles
            tickets={nid:ticket for bundle in bundles.values() for nid,ticket in self._early_tickets(bundle).items()}
            error=None
            if tickets:
                try:
                    await dispatch('early-card-proofs-'+str(attempt),self.factory,list(tickets.values()))
                except Exception as exc:
                    error=exc
            changed=[pid for pid in ordered if versions[pid]!=(payload_hash(current[pid]),payload_hash(pmap[pid]),payload_hash(rmap[pid]))]
            if changed:
                self._early_snapshot(bundles,[current[p] for p in ordered],attempt=attempt,
                    status='operational_failure',failed_papers=changed,
                    error={'message':'Card/source/reader version changed during early verification'})
                raise ValueError('Early card/source/reader version changed; fresh verification is required')
            negatives={}
            current_ids={nid for bundle in bundles.values() for nid,s in bundle['node_specs'].items() if s['kind']!='root'}
            for pid,bundle in bundles.items():
                for nid in bundle['node_specs']:
                    node=self.nodes.get(nid)
                    if node and (node['payload']['status']!='passed' or node['payload']['issues']):
                        negatives.setdefault(pid,[]).append({'node_id':nid,'kind':node['payload']['kind'],
                            'status':node['payload']['status'],'reason':node['payload']['reason'],
                            'issues':node['payload']['issues']})
            rows={row['id']:row for row in self.store.status()}
            negative_ids={issue['node_id'] for issues in negatives.values() for issue in issues}
            operational=[nid for nid,ticket in tickets.items()
                if ((rows[ticket]['status'] in ('failed','running') and nid not in negative_ids)
                    or (not negatives and rows[ticket]['status']!='accepted'))]
            if operational or (error is not None and not negatives):
                self._early_snapshot(bundles,[current[p] for p in ordered],attempt=attempt,
                    status='operational_failure',failed_papers=negatives,
                    error={'message':str(error),'unresolved_execution_node_ids':operational})
                if error is not None:
                    raise error
                raise RuntimeError('Early card proof execution incomplete; no scientific repair is authorized')
            if negatives:
                row=self._early_snapshot(bundles,[current[p] for p in ordered],attempt=attempt,
                    status='needs_revision',failed_papers=negatives,error={'message':str(error)} if error else None)
                self.repair_history.append(row)
                if self.repair_rounds_used>=self.max_repairs:
                    raise RuntimeError('Semantic repair budget exhausted during early card verification; comparison was not created')
                self.repair_rounds_used+=1
                revisions=[]
                targets=list(negatives)
                for pid in targets:
                    packet=draft_packet('paper_card',[pmap[pid]],[rmap[pid]],self.questions)
                    ticket=self.store.create('writer',packet,max_attempts=1)
                    self.revisions[ticket]={'previous_draft':current[pid],
                        'independent_issues':negatives[pid],
                        'upstream_revised':False,'instruction':'Revise the rejected card against the complete original. No comparison has been written from this version.'}
                    revisions.append(ticket)
                await dispatch('early-card-revision-'+str(attempt),self.factory,revisions)
                for pid,ticket,card in zip(targets,revisions,self._outputs(revisions)):
                    if card['paper_ids']!=[pid]:
                        raise ValueError('Early revision changed card paper identity')
                    current[pid],writers[pid]=card,ticket
                attempt+=1
                continue
            if tickets:
                self._outputs(list(tickets.values()))
            for pid,bundle in bundles.items():
                terminal=bundle['section_assembly_nodes'][current[pid]['section_id']]
                scoped={nid:self.nodes[nid] for nid in bundle['node_specs'] if nid in self.nodes}
                verify_dependency_closure(bundle['plan'],scoped,bundle['materials'],self.identities,[terminal])
                if self.source_quote_witness:
                    from .source_witness_audit import verify_source_witness_audits
                    verify_source_witness_audits(bundle,scoped,self.submissions)
                ticket=self._proof_node_tickets[terminal]
                if next(r for r in self.store.status() if r['id']==ticket)['status']!='accepted':
                    raise RuntimeError('Early terminal proof ticket was not natively accepted')
                self._early_qualified[pid]={'card_hash':payload_hash(current[pid]),
                    'packet_hash':payload_hash(pmap[pid]),'record_hash':payload_hash(rmap[pid]),
                    'terminal_node_id':terminal,'terminal_hash':self.nodes[terminal]['payload_hash'],'ticket':ticket}
            self.early_proof_nodes={nid:self.nodes[nid] for nid in current_ids}
            self._early_snapshot(bundles,[current[p] for p in ordered],attempt=attempt,status='qualified')
            return [current[p] for p in ordered],[writers[p] for p in ordered]

    def _qualification_ticket(self,card,packet,record):
        pid=packet['paper_id']
        proof=self._early_qualified.get(pid)
        if (not proof or proof['card_hash']!=payload_hash(card) or proof['packet_hash']!=payload_hash(packet)
                or proof['record_hash']!=payload_hash(record)
                or self.nodes[proof['terminal_node_id']]['payload_hash']!=proof['terminal_hash']):
            raise ValueError('Early card/source qualification changed before comparison; fresh verification is required')
        return proof['ticket']

    async def run(self,dispatch):
        """dispatch(stage_name, worker_factory) must finish native task delegation.

        Each call shares the caller's original wall-clock deadline. No accepted
        records are imported from a previous run; store must initially be empty.
        """
        if self.store.status():
            raise ValueError('Cold workflow requires an empty task store')
        readers=[self.store.create('reader',p,max_attempts=1) for p in self.packets]
        await dispatch('reading',self.factory)
        records=self._outputs(readers)
        rmap={r['paper_id']:r for r in records}
        rdep={p['paper_id']:t for p,t in zip(self.packets,readers)}
        cards=[self.store.create('writer',draft_packet('paper_card',[p],[rmap[p['paper_id']]],self.questions),
                                 dependencies=[rdep[p['paper_id']]],max_attempts=1) for p in self.packets]
        await dispatch('cards',self.factory)
        card_sections=self._outputs(cards)
        if self.early_card_verification:
            card_sections,cards=await self._qualify_cards(dispatch,card_sections,cards,records)
        cardmap={s['paper_ids'][0]:(s,t) for s,t in zip(card_sections,cards)}
        groups=[self.packets[i:i+self.group_size] for i in range(0,len(self.packets),self.group_size)]
        comparisons=[]
        for group in groups:
            members=[cardmap[p['paper_id']] for p in group]
            qualification=[self._qualification_ticket(cardmap[p['paper_id']][0],p,rmap[p['paper_id']])
                           for p in group] if self.early_card_verification else []
            comparisons.append(self.store.create('comparer',inference_packet([s for s,t in members],group,
                [rmap[p['paper_id']] for p in group],self.questions,kind='comparison',dimensions=self.dimensions),
                dependencies=[t for s,t in members]+qualification,max_attempts=1))
        # A repaired early failure remains immutable in the store. Later
        # stages must inspect only their actual current-version tickets.
        await dispatch('comparison',self.factory,comparisons)
        comparisons_sections=self._outputs(comparisons)
        sections=card_sections+comparisons_sections
        current=[]
        for group,comparison,ct in zip(groups,comparisons_sections,comparisons):
            members=[cardmap[p['paper_id']] for p in group]
            packet=inference_packet([s for s,t in members]+[comparison],group,
                                    [rmap[p['paper_id']] for p in group],self.questions)
            current.append(self.store.create('writer',packet,dependencies=[t for s,t in members]+[ct],max_attempts=1))
        level=0
        while True:
            await dispatch('synthesis-'+str(level),self.factory,current)
            results=self._outputs(current)
            sections.extend(results)
            if len(results)==1:
                root=results[0]['section_id']
                break
            following=[]
            for start in range(0,len(results),self.group_size):
                premises=results[start:start+self.group_size]
                members={p for s in premises for p in s['paper_ids']}
                selected=[p for p in self.packets if p['paper_id'] in members]
                packet=inference_packet(premises,selected,[rmap[p['paper_id']] for p in selected],self.questions)
                following.append(self.store.create('writer',packet,
                    dependencies=current[start:start+self.group_size],max_attempts=1))
            current=following
            level+=1
        old_nodes=dict(self.early_proof_nodes)
        for attempt in range(self.max_repairs+1):
            self.bundle=plan_review(sections,self.packets,records,root_section_ids=[root],
                                   token_counter=self.token_counter,max_scientific_units=self.proof_max_units,
                                   merge_full_source=self.merge_full_source)
            self.nodes=reusable_nodes(self.bundle,old_nodes)
            self.proof_tickets={}
            remaining={nid:s for nid,s in self.bundle['node_specs'].items() if nid not in self.nodes}
            while remaining:
                known=set(self.proof_tickets)|set(self.nodes)
                ready=[nid for nid,s in remaining.items() if set(s['dependencies'])<=known]
                if not ready:
                    raise ValueError('Proof task dependency cycle')
                for nid in ready:
                    spec=remaining.pop(nid)
                    self.proof_tickets[nid]=self.store.create(spec['role'],{'node_id':nid},
                        dependencies=[self.proof_tickets[d] for d in spec['dependencies'] if d in self.proof_tickets],
                        max_attempts=1)
                    self._proof_ticket_bundles[self.proof_tickets[nid]]=self.bundle
                    self._proof_node_tickets[nid]=self.proof_tickets[nid]
            dispatch_error=None
            try:
                await dispatch('independent-proofs-'+str(attempt),self.factory,list(self.proof_tickets.values()))
                self._outputs(list(self.proof_tickets.values()))
            except Exception as exc:
                dispatch_error=exc
            negative=[n for n in self.nodes.values() if n['payload']['status']!='passed' or n['payload']['issues']]
            if not negative:
                if dispatch_error:
                    raise dispatch_error
                gate=verify_proof(self.bundle['plan'],self.nodes,self.bundle['materials'],self.identities)
                break
            snapshot=self.store.put({'plan':self.bundle['plan'],'nodes':self.nodes,
                                     'attempt':attempt,'sections':sections})
            self.repair_history.append({'attempt':attempt,'snapshot_hash':snapshot})
            if self.repair_rounds_used>=self.max_repairs:
                raise RuntimeError('Semantic repair budget exhausted; report remains unverified')
            self.repair_rounds_used+=1
            direct,affected=revision_targets(self.bundle,self.nodes)
            old_nodes=dict(self.nodes)
            replaced={s['section_id']:s for s in sections if s['section_id'] not in affected}
            pending={s['section_id']:s for s in sections if s['section_id'] in affected}
            wave=0
            while pending:
                ready=[sid for sid,s in pending.items() if set(s['premise_section_ids'])<=set(replaced)]
                if not ready:
                    raise ValueError('Revision premise dependency cycle')
                tickets=[]
                for sid in ready:
                    old=pending.pop(sid)
                    selected=[p for p in self.packets if p['paper_id'] in old['paper_ids']]
                    selected_records=[rmap[p['paper_id']] for p in selected]
                    if old['kind']=='synthesis' or (old['kind']=='comparison' and old['premise_section_ids']):
                        premises=[replaced[p] for p in old['premise_section_ids']]
                        packet=inference_packet(premises,selected,selected_records,self.questions,
                                                kind=old['kind'],dimensions=old['dimensions'])
                    else:
                        packet=draft_packet(old['kind'],selected,selected_records,self.questions,
                                            dimensions=old['dimensions'])
                    ticket=self.store.create('comparer' if old['kind']=='comparison' else 'writer',packet,max_attempts=1)
                    self.revisions[ticket]={'previous_draft':old,'independent_issues':direct.get(sid,[]),
                        'upstream_revised':any(p in affected for p in old['premise_section_ids']),
                        'instruction':'Re-evaluate changed premises and retain important qualifications.'}
                    tickets.append(ticket)
                await dispatch('revision-'+str(attempt)+'-'+str(wave),self.factory,tickets)
                replaced.update(zip(ready,self._outputs(tickets)))
                wave+=1
            sections=[replaced[s['section_id']] for s in sections]
            root=replaced[root]['section_id']
        witness_audit=None
        if self.source_quote_witness:
            from .source_witness_audit import verify_source_witness_audits
            witness_audit=verify_source_witness_audits(self.bundle,self.nodes,self.submissions)
        return {'bundle':self.bundle,'nodes':self.nodes,'identities':self.identities,
                'source_quote_witness_required':self.source_quote_witness,
                'early_card_verification':self.early_card_verification,
                'early_card_history':list(self.early_card_history),'repair_rounds_used':self.repair_rounds_used,
                'source_witness_audit':witness_audit,
                'proof_submissions':{nid:self.submissions[nid] for nid in self.nodes if nid in self.submissions},
                'gate':gate,'records':records,'sections':sections,'repair_history':self.repair_history}
