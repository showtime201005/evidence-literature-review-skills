"""Opt-in experimental v2 workflow through the existing real SDK dispatcher.

V1 is untouched. Every actual layer qualifies before a parent writer exists.
Only the supplied dispatcher invokes native agents; this host schedules tickets,
persists immutable attempts and replays mechanical release requirements.
"""
from __future__ import annotations

import copy
import json
import math
import time

from .draft_worker import draft_worker
from .reader_worker import reader_worker
from .hierarchical_proof import RuntimeIdentity, payload_hash
from .paper_review_v2 import plan_paper_review_v2, verify_paper_review_v2
from .paper_review_worker_v2 import make_paper_review_v2_worker, _has_negative
from .section_review_v2 import (section_draft_packet_v2, plan_section_review_v2,
                                verify_section_review_v2)
from .section_review_worker_v2 import make_section_review_v2_worker
from .review_artifacts import draft_packet
from .task_store import canonical
from .review_observation_selectors import QUOTES, validate_observation_mode


def source_scope_v2(packets, questions):
    ids=[p['paper_id'] for p in packets]
    if not ids or len(ids)!=len(set(ids)):
        raise ValueError('Unique nonempty source inventory required')
    return {'schema':'review-v2-source-scope/1','paper_ids':ids,
            'packet_hashes':{p['paper_id']:payload_hash(p) for p in packets},
            'source_versions':{p['paper_id']:p['source_sha256'] for p in packets},
            'questions':copy.deepcopy(questions)}


class ReviewWorkflowV2:
    def __init__(self,store,packets,questions,*,group_size=4,
                 dimensions=('研究設計與族群','主要結果與不確定性','適用條件與限制'),
                 token_counter=None,max_repairs=2,deadline_at,observation_mode=QUOTES,closed_checks=False):
        if not 2<=group_size<=8:raise ValueError('Group size must be 2..8')
        if type(max_repairs) is not int or not 0<=max_repairs<=2:raise ValueError('Shared repair rounds must be 0..2')
        if not isinstance(deadline_at,(int,float)) or not math.isfinite(deadline_at):raise ValueError('An absolute monotonic deadline is required')
        self.store,self.packets,self.questions=store,packets,questions
        self.group_size,self.dimensions=group_size,list(dimensions)
        self.token_counter,self.max_repairs,self.deadline_at=token_counter,max_repairs,float(deadline_at)
        self.observation_mode=validate_observation_mode(observation_mode)
        if type(closed_checks) is not bool:raise ValueError('closed_checks must be a boolean')
        self.closed_checks_required=closed_checks
        self.closed_checks,self.closed_tickets,self._closed_bindings={},{},{}
        self._closed_attestations,self._closed_attempts={},{}
        self.source_inventory=source_scope_v2(packets,questions)
        self.identities,self.reviews,self.review_tickets={},{},{}
        self.attempt_history,self.repair_history,self.qualification_history=[],[],[]
        self.repair_rounds_used=0
        self.records,self.sections,self.root_section_ids=[],[],[]
        self._current,self._job_order,self._bindings,self._attempts_by_ticket={},[],{},{}
        self._attestations,self.revisions={},{}
        self.protocol_completed_experimental=False
        for packet in packets:
            from .scientific_records import source_packet
            raw=b''.join(p['text'].encode('utf8') for p in packet['parts'])
            if canonical(source_packet(packet['paper_id'],raw,packet['questions']))!=canonical(packet) or packet['questions']!=questions:
                raise ValueError('Original source bytes/questions cannot be reconstructed')

    def _deadline(self):
        if time.monotonic()>=self.deadline_at:raise TimeoutError('Original cold-run deadline reached')

    def _check_sources(self):
        self._deadline()
        if source_scope_v2(self.packets,self.questions)!=self.source_inventory:
            raise ValueError('Original source/question versions changed during the run')

    def _counter(self,value):
        return self.token_counter(canonical(value).decode('utf8')) if self.token_counter else None

    def _outputs(self,tickets):
        rows={r['id']:r for r in self.store.status()}
        if any(rows[t]['status']!='accepted' for t in tickets):raise RuntimeError('Native research stage incomplete')
        return [self.store.get(rows[t]['output_hash']) for t in tickets]

    def _register(self,identity,ticket):
        row=next(r for r in self.store.status() if r['id']==ticket)
        self.identities[identity.context_id]=RuntimeIdentity(execution_id=identity.context_id,
            context_id=identity.context_id,role=identity.role,input_hashes={ticket:row['input_hash']},
            output_hashes={ticket:row['output_hash']},task_call_id=identity.task_tool_call_id,
            parent_context_id=identity.coordinator_context_id)

    def factory(self,identity,description):
        self._deadline()
        request=json.loads(description)
        if not isinstance(request,dict) or set(request)!={'ticket'}:raise ValueError('Delegate exactly one native ticket')
        ticket=request['ticket']
        if identity.role in ('reader','writer','comparer'):
            accepted=lambda t,a,r:self._register(identity,t)
            if identity.role=='reader':return reader_worker(self.store,identity,ticket,on_accepted=accepted)
            return draft_worker(self.store,identity,ticket,on_accepted=accepted,revision=self.revisions.get(ticket))
        if identity.role=='verifier' and ticket in self._closed_bindings:
            return self._closed_worker(identity,ticket)
        if identity.role!='verifier' or ticket not in self._bindings:raise ValueError('Unknown v2 review assignment')
        lease=self.store.claim(ticket,identity.role,identity.context_id)
        bundle=self._bindings[ticket]
        def save(attempt,execution):
            row=copy.deepcopy(attempt)
            row['semantic_negative_detected']=_has_negative(row.get('raw_tool_arguments'))
            digest=self.store.put(row)
            event={'ticket':ticket,'review_id':bundle['review_id'],'status':row['status'],
                   'attempt_hash':digest,'attempt':row}
            self.attempt_history.append(event)
            self._attempts_by_ticket.setdefault(ticket,[]).append(event)
            if execution is not None:
                self.identities[execution.context_id]=execution
                self._attestations[bundle['review_id']]=row['attestation']
            if row['status']=='passed':
                return self.store.accept(ticket,identity.context_id,lease['lease'],row['attestation'],validator=lambda p,a:None)
            if row['status']!='invalid' or row['semantic_negative_detected']:
                self.store.fail(ticket,identity.context_id,lease['lease'],{'code':'VERIFICATION_ISSUES','attempt_hash':digest})
        def finish(actual,receipt):
            state=next(r for r in self.store.status() if r['id']==ticket)
            if state['status']=='running':self.store.fail(ticket,identity.context_id,lease['lease'],
                {'reason':receipt.get('error',receipt.get('reason','No native acceptance'))})
        try:
            builder=make_paper_review_v2_worker if bundle['schema']=='paper-review-bundle/2' else make_section_review_v2_worker
            return builder(bundle,identity,trusted_identities=self.identities,save=save,on_finish=finish)
        except Exception as exc:
            self.store.fail(ticket,identity.context_id,lease['lease'],{'reason':str(exc)})
            raise

    def _child_ticket(self,entry):
        bundle,att=entry['bundle'],entry['attestation']
        verify=verify_paper_review_v2 if bundle['schema']=='paper-review-bundle/2' else verify_section_review_v2
        if not verify(bundle,att,trusted_identities=self.identities)['qualified_for_experiment']:
            raise ValueError('An unqualified version cannot feed a parent writer')
        ticket=self.review_tickets[bundle['review_id']]
        row=next(r for r in self.store.status() if r['id']==ticket)
        if row['status']!='accepted' or self.store.get(row['output_hash'])!=att:
            raise ValueError('Qualified premise lacks its exact native accepted review ticket')
        if self.closed_checks_required:
            from .closed_scientific_checks import plan_closed_checks,verify_closed_attestation
            section=bundle['payload'].get('card',bundle['payload'].get('section'))
            actual=self.closed_checks.get(section['section_id'],[])
            expected=plan_closed_checks(bundle,trusted_identities=self.identities)
            if canonical([a['packet'] for a in actual])!=canonical(expected):
                raise ValueError('Every exact local responsibility requires its own closed check')
            for item in actual:
                if not verify_closed_attestation(item['packet'],item['attestation'],trusted_identities=self.identities)['qualified_for_experiment']:
                    raise ValueError('Negative local check cannot feed a parent')
        return ticket

    def _closed_worker(self,identity,ticket):
        from .closed_scientific_checks import make_closed_check_worker
        binding=self._closed_bindings[ticket]
        packet=binding['packet']
        lease=self.store.claim(ticket,identity.role,identity.context_id)
        def save(attempt,execution):
            row=copy.deepcopy(attempt)
            row['semantic_negative_detected']=_has_negative(row.get('raw_tool_arguments'))
            row['closed_check']=copy.deepcopy(packet)
            digest=self.store.put(row)
            event={'ticket':ticket,'review_id':binding['review_id'],'status':row['status'],
                'attempt_hash':digest,'attempt':row}
            self.attempt_history.append(event)
            self._closed_attempts.setdefault(ticket,[]).append(event)
            if row['status'] in ('needs_revision','unresolved') or row['semantic_negative_detected']:
                self._attempts_by_ticket.setdefault(binding['review_ticket'],[]).append(event)
            if execution is not None:
                self.identities[execution.context_id]=execution
                self._closed_attestations[packet['check_id']]=row['attestation']
            if row['status']=='passed':
                return self.store.accept(ticket,identity.context_id,lease['lease'],row['attestation'],validator=lambda p,a:None)
            if row['status']!='invalid' or row['semantic_negative_detected']:
                self.store.fail(ticket,identity.context_id,lease['lease'],{'code':'VERIFICATION_ISSUES','attempt_hash':digest})
        def finish(actual,receipt):
            row=next(r for r in self.store.status() if r['id']==ticket)
            if row['status']=='running':self.store.fail(ticket,identity.context_id,lease['lease'],
                {'reason':receipt.get('error',receipt.get('reason','Incomplete closed check'))})
        return make_closed_check_worker(packet,identity,save=save,on_finish=finish)

    async def _closed_wave(self,stage,jobs,attempt,dispatch):
        from .closed_scientific_checks import plan_closed_checks
        for job in jobs:
            packets=plan_closed_checks(job['bundle'],trusted_identities=self.identities)
            job['closed_packets']=packets
            for packet in packets:
                cid=packet['check_id']
                if cid not in self.closed_tickets:
                    ticket=self.store.create('verifier',packet,dependencies=[job['writer_ticket']]+job['dependencies'],max_attempts=1)
                    self.closed_tickets[cid]=ticket
                    self._closed_bindings[ticket]={'packet':packet,'review_id':job['bundle']['review_id'],
                        'review_ticket':job['review_ticket']}
        rows={r['id']:r for r in self.store.status()}
        pending=[self.closed_tickets[p['check_id']] for j in jobs for p in j['closed_packets']
            if rows[self.closed_tickets[p['check_id']]]['status']=='pending']
        error=None
        if pending:
            try:await dispatch(stage+'-closed-'+str(attempt),self.factory,pending)
            except Exception as exc:error=exc
        self._check_sources()
        rows={r['id']:r for r in self.store.status()}
        ready=set();negative=False;operational=False
        for job in jobs:
            tickets=[self.closed_tickets[p['check_id']] for p in job['closed_packets']]
            history=[a for t in tickets for a in self._closed_attempts.get(t,[])]
            bad=any(a['attempt']['status'] in ('needs_revision','unresolved') or a['attempt'].get('semantic_negative_detected') for a in history)
            if bad:negative=True;continue
            if all(rows[t]['status']=='accepted' for t in tickets):
                section=self._current[job['key']]
                self.closed_checks[section['section_id']]=[{'packet':p,'attestation':self._closed_attestations[p['check_id']]}
                    for p in job['closed_packets']]
                ready.add(job['key'])
            elif any(rows[t]['status'] in ('failed','running') for t in tickets):operational=True
        if operational or (error is not None and not negative):
            if error:raise error
            raise RuntimeError('Operational closed-check failure; original attempts preserved')
        return ready

    def _snapshot_wave(self,stage,jobs,status):
        snapshot={'schema':'review-v2-qualification-wave/1','stage':stage,'status':status,
            'job_keys':[j['key'] for j in jobs],'current_sections':{j['key']:self._current[j['key']] for j in jobs},
            'bundle_hashes':{j['key']:self.store.put(j['bundle']) for j in jobs},
            'attempt_hashes':[a['attempt_hash'] for j in jobs for a in self._attempts_by_ticket.get(j['review_ticket'],[])],
            'repair_rounds_used':self.repair_rounds_used}
        row={'stage':stage,'status':status,'snapshot_hash':self.store.put(snapshot),
             'repair_rounds_used':self.repair_rounds_used}
        self.qualification_history.append(row)
        return row

    async def _draft_qualify(self,stage,jobs,dispatch):
        for job in jobs:
            self._deadline()
            if job['key'] in self._current:raise ValueError('Duplicate actual workflow job')
            self._job_order.append(job['key'])
            job['writer_ticket']=self.store.create('comparer' if job['packet']['kind']=='comparison' else 'writer',
                job['packet'],dependencies=job['dependencies'],max_attempts=1)
        await dispatch(stage+'-draft',self.factory,[j['writer_ticket'] for j in jobs])
        self._check_sources()
        for job,section in zip(jobs,self._outputs([j['writer_ticket'] for j in jobs])):
            self._current[job['key']]=section
        attempt=0
        while True:
            self._check_sources()
            for job in jobs:
                section=self._current[job['key']]
                if section['kind']=='paper_card':
                    bundle=plan_paper_review_v2(job['source'],job['record'],section,
                        wire_counter=self._counter if self.token_counter else None,
                        observation_mode=self.observation_mode)
                else:
                    bundle=plan_section_review_v2(section,job['children'],questions=self.questions,
                        trusted_identities=self.identities,wire_counter=self._counter if self.token_counter else None,
                        observation_mode=self.observation_mode)
                job['bundle']=bundle
                rid=bundle['review_id']
                if rid not in self.review_tickets:
                    local_dependencies=[]
                    if self.closed_checks_required:
                        from .closed_scientific_checks import plan_closed_checks
                        for packet in plan_closed_checks(bundle,trusted_identities=self.identities):
                            cid=packet['check_id']
                            local_ticket=self.store.create('verifier',packet,
                                dependencies=[job['writer_ticket']]+job['dependencies'],max_attempts=1)
                            self.closed_tickets[cid]=local_ticket
                            self._closed_bindings[local_ticket]={'packet':packet,'review_id':rid}
                            local_dependencies.append(local_ticket)
                    ticket=self.store.create('verifier',{'review_id':rid,'bundle_sha256':bundle['payload_sha256'],
                        'wire_sha256':bundle['wire_sha256']},dependencies=[job['writer_ticket']]+job['dependencies']+local_dependencies,max_attempts=1)
                    self.review_tickets[rid]=ticket
                    self._bindings[ticket]=bundle
                    for local_ticket in local_dependencies:self._closed_bindings[local_ticket]['review_ticket']=ticket
                elif canonical(self._bindings[self.review_tickets[rid]])!=canonical(bundle):
                    raise ValueError('An existing review ID changed its immutable delivered specification')
                job['review_ticket']=self.review_tickets[rid]
            rows={r['id']:r for r in self.store.status()}
            locally_ready=(await self._closed_wave(stage,jobs,attempt,dispatch) if self.closed_checks_required
                           else {j['key'] for j in jobs})
            pending=[j['review_ticket'] for j in jobs if j['key'] in locally_ready and rows[j['review_ticket']]['status']=='pending']
            error=None
            if pending:
                try:await dispatch(stage+'-review-'+str(attempt),self.factory,pending)
                except Exception as exc:error=exc
            self._check_sources()
            rows={r['id']:r for r in self.store.status()}
            negatives=[];operational=[]
            for job in jobs:
                ticket=job['review_ticket'];state=rows[ticket]['status']
                history=self._attempts_by_ticket.get(ticket,[])
                negative=any(a['attempt']['status'] in ('needs_revision','unresolved') or a['attempt'].get('semantic_negative_detected') for a in history)
                if state=='accepted' and not negative:continue
                if negative:negatives.append(job)
                elif state in ('failed','running'):operational.append(ticket)
            if operational or (error is not None and not negatives):
                self._snapshot_wave(stage,jobs,'operational_failure')
                if error:raise error
                raise RuntimeError('Operational v2 review failure; no scientific reroll authorized')
            if negatives:
                snapshot=self._snapshot_wave(stage,jobs,'needs_revision')
                self.repair_history.append({**snapshot,'targets':[j['key'] for j in negatives]})
                if self.repair_rounds_used>=self.max_repairs:raise RuntimeError('Shared semantic repair budget exhausted before downstream writing')
                self.repair_rounds_used+=1
                tickets=[]
                for job in negatives:
                    previous=self._current[job['key']]
                    ticket=self.store.create('comparer' if previous['kind']=='comparison' else 'writer',job['packet'],
                        dependencies=[job['writer_ticket']]+job['dependencies'],max_attempts=1)
                    self.revisions[ticket]={'previous_draft':previous,'independent_issues':
                        [a['attempt'] for a in self._attempts_by_ticket[job['review_ticket']]],
                        'instruction':'Revise against actual complete sources or qualified premises. Preserve honest negatives in history; no downstream writer has consumed this version.'}
                    job['writer_ticket']=ticket;tickets.append(ticket)
                await dispatch(stage+'-revision-'+str(attempt),self.factory,tickets)
                self._check_sources()
                for job,section in zip(negatives,self._outputs(tickets)):
                    previous=self._current[job['key']]
                    if canonical({k:section[k] for k in ('claims','retention','cells')})==canonical({k:previous[k] for k in ('claims','retention','cells')}):
                        raise RuntimeError('Revision made no actual scientific artifact change; review reroll refused')
                    self._current[job['key']]=section
                attempt+=1
                continue
            # Pending unaffected tickets after a parallel negative remain scoped
            # to this wave and are run on its next iteration, never resealed.
            if any(rows[j['review_ticket']]['status']!='accepted' for j in jobs):
                raise RuntimeError('V2 qualification incomplete')
            entries=[]
            for job in jobs:
                section=self._current[job['key']];bundle=job['bundle']
                entry={'bundle':bundle,'attestation':self._attestations[bundle['review_id']]}
                self._child_ticket(entry)
                self.reviews[section['section_id']]=entry
                entries.append(entry)
            self.sections=[self._current[k] for k in self._job_order]
            self._snapshot_wave(stage,jobs,'qualified_for_experiment')
            return entries

    async def run(self,dispatch):
        self._check_sources()
        if self.store.status():raise ValueError('Cold v2 workflow requires an empty TaskStore')
        readers=[self.store.create('reader',p,max_attempts=1) for p in self.packets]
        await dispatch('v2-reading',self.factory,readers)
        self._check_sources()
        self.records=self._outputs(readers)
        rmap={r['paper_id']:r for r in self.records}
        leafjobs=[{'key':'card/'+p['paper_id'],'packet':draft_packet('paper_card',[p],[rmap[p['paper_id']]],self.questions,
            include_reader_findings=True),
            'dependencies':[t],'source':p,'record':rmap[p['paper_id']]} for p,t in zip(self.packets,readers)]
        cards=await self._draft_qualify('v2-cards',leafjobs,dispatch)
        groups=[cards[i:i+self.group_size] for i in range(0,len(cards),self.group_size)]
        def derived(key,children,kind='synthesis'):
            deps=[self._child_ticket(e) for e in children]
            packet=section_draft_packet_v2(children,trusted_identities=self.identities,questions=self.questions,
                kind=kind,dimensions=self.dimensions if kind=='comparison' else ())
            return {'key':key,'packet':packet,'dependencies':deps,'children':children}
        comparisons=await self._draft_qualify('v2-comparison',
            [derived('comparison/'+str(i),group,'comparison') for i,group in enumerate(groups)],dispatch)
        current=await self._draft_qualify('v2-synthesis-0',
            [derived('synthesis/0/'+str(i),group+[comparison]) for i,(group,comparison) in enumerate(zip(groups,comparisons))],dispatch)
        level=1
        while len(current)>1:
            jobs=[derived('synthesis/'+str(level)+'/'+str(i//self.group_size),current[i:i+self.group_size])
                  for i in range(0,len(current),self.group_size)]
            current=await self._draft_qualify('v2-synthesis-'+str(level),jobs,dispatch)
            level+=1
        self.root_section_ids=[current[0]['bundle']['payload']['section']['section_id']]
        from .review_release_v2 import verify_review_release_v2
        result=self.partial_snapshot()
        gate=verify_review_release_v2(result,deadline_at=self.deadline_at)
        self.protocol_completed_experimental=True
        return {**self.partial_snapshot(),'gate':gate}

    def partial_snapshot(self):
        return {'schema':'review-workflow-result/2','protocol':'literature-review-v2',
            'observation_mode':self.observation_mode,
            'closed_checks_required':self.closed_checks_required,
            'closed_checks':copy.deepcopy({sid:items for sid,items in self.closed_checks.items()
                if sid in {s['section_id'] for s in self._current.values()}}),
            'protocol_completed_experimental':self.protocol_completed_experimental,
            'publication_verified':False,'quality_validated':False,'deadline_at':self.deadline_at,
            'source_inventory':copy.deepcopy(self.source_inventory),'packets':copy.deepcopy(self.packets),
            'questions':copy.deepcopy(self.questions),'group_size':self.group_size,'dimensions':list(self.dimensions),
            'records':copy.deepcopy(self.records),'sections':copy.deepcopy([self._current[k] for k in self._job_order if k in self._current]),
            'root_section_ids':list(self.root_section_ids),'reviews':copy.deepcopy(self.reviews),
            'identities':dict(self.identities),'attempt_history':copy.deepcopy(self.attempt_history),
            'qualification_history':copy.deepcopy(self.qualification_history),'repair_history':copy.deepcopy(self.repair_history),
            'repair_rounds_used':self.repair_rounds_used,'task_status':self.store.status(),
            'accepted_artifacts':[self.store.get(row['output_hash']) for row in self.store.status() if row['status']=='accepted']}
