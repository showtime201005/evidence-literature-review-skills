"""Whole workflow through real SDK delegation; scripted science is NOT quality evidence."""
import asyncio
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'skills/literature-review/scripts/runtime'))
sys.path.insert(0, str(ROOT/'tests'))
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from test_native_agent import ScriptedModel
from litreview_core.coordinator_frontier import run_frontiers
from litreview_core.delivery_export import export_review, save_review_attempt
from litreview_core.draft_wire import restore_draft_packet
from litreview_core.native_agent import ROLE_SKILLS, create_review_agent
from litreview_core.review_workflow import ReviewWorkflow
from litreview_core.scientific_records import FIELDS, source_packet
from litreview_core.task_store import ScopedTaskStore, TaskStore


def scripted_submission(role, packet):
    if role == 'reader':
        return {
            'observations': [{'part_id': p['part_id'], 'note': 'Failure persists'} for p in packet['parts']],
            'findings': [{'local_id': 'f', 'field': 'limitations', 'text': 'Failure persists',
                'attribution': 'author_limitation', 'evidence': [{'part_id': 'p0001'}],
                'obligations': ['persistent_failure']}],
            'fields': [{'field': f, 'status': 'extracted' if f == 'limitations' else 'not_reported',
                        'reason': 'Offline fixture'} for f in FIELDS],
            'questions': [{'question_id': 'q', 'status': 'addressed', 'reason': 'Failure',
                           'support': [], 'counterevidence': ['f']}],
        }
    if role in ('writer', 'comparer'):
        packet = restore_draft_packet(packet)
        claims = []
        for pid in packet['paper_ids']:
            premises = [s['section_id']+'/'+c['local_id'] for s in packet['premises']
                        for c in s['claims'] if pid in c['population_paper_ids']]
            claims.append({'local_id': pid, 'text': 'Failure persists',
                'evidence_refs': [pid+'/p0001'], 'question_ids': ['q'], 'attribution': 'source_finding',
                'scope': 'individual', 'population_paper_ids': [pid], 'premise_claim_ids': premises})
        return {'claims': claims,
            'retention_groups': [{'obligation_ids': [o['id']], 'status': 'included',
                'claim_ids': [o['source_refs'][0].split('/')[0]], 'reason': 'Failure retained'}
                for o in packet['obligations']],
            'cells': [{'paper_id': p, 'dimension': d, 'claim_ids': [p]}
                      for p in packet['paper_ids'] for d in packet['dimensions']]}
    coverage = packet['coverage']
    return {'checked': coverage, 'verdicts': [{'unit_id': uid, 'verdict': 'passed',
        'reason': 'Scripted mechanics only; no scientific judgment'}
        for uid in coverage['claims']+coverage['obligations']],
        'status': 'passed', 'reason': 'Scripted mechanics only', 'issues': []}


class NativeWorkflowTests(unittest.TestCase):
    def test_actual_task_graph_entire_workflow_and_export_without_network(self):
        self.exercise()

    def test_opt_in_merged_full_source_entire_sdk_workflow_and_export_without_network(self):
        self.exercise(merge_full_source=True)

    def test_entire_workflow_requires_and_exports_every_source_witness(self):
        self.exercise(witness=True)

    def test_merged_workflow_with_source_witnesses(self):
        self.exercise(merge_full_source=True,witness=True)

    def test_early_complete_card_proofs_are_reused_by_global_real_sdk_workflow(self):
        self.exercise(merge_full_source=True,early=True)

    def test_early_complete_card_gate_also_requires_source_witnesses(self):
        self.exercise(merge_full_source=True,witness=True,early=True)

    def test_actual_sdk_early_negative_is_revised_before_comparison(self):
        self.exercise(merge_full_source=True,witness=True,early=True,reject_early=True)

    def test_actual_sdk_repeated_early_negative_stops_before_comparison(self):
        with self.assertRaisesRegex(RuntimeError,'repair budget exhausted'):
            self.exercise(merge_full_source=True,witness=True,early=True,reject_early=True,reject_always=True)
        self.assertNotIn('comparison',self.last_stages)
        self.assertFalse(any(r['role']=='comparer' for r in self.last_rows))

    def test_actual_sdk_changed_source_requires_fresh_early_verification(self):
        with self.assertRaisesRegex(ValueError,'version changed'):
            self.exercise(merge_full_source=True,early=True,change_source=True)
        self.assertNotIn('comparison',self.last_stages)

    def exercise(self,merge_full_source=False,witness=False,early=False,reject_early=False,
                 reject_always=False,change_source=False):
        import httpx
        network_attempts = []

        def blocked(*args, **kwargs):
            network_attempts.append(True)
            raise AssertionError('Network forbidden in scripted workflow integration')

        with tempfile.TemporaryDirectory(prefix='whole-sdk-') as tmp, \
                patch.object(socket, 'create_connection', blocked), \
                patch.object(httpx.Client, 'send', blocked), \
                patch.object(httpx.AsyncClient, 'send', blocked):
            root = Path(tmp)
            skills = root/'skills'
            for name in set(ROLE_SKILLS.values()) | {'literature-review'}:
                folder = skills/name
                (folder/'references').mkdir(parents=True)
                (folder/'SKILL.md').write_text(
                    f'---\nname: {name}\ndescription: Offline mechanics fixture.\n---\nUse assigned tools.', encoding='utf-8')
                for reference in ('hierarchical-proof.md', 'scientific-records.md', 'mapped-drafts.md'):
                    (folder/'references'/reference).write_text('Scripted mechanics only.', encoding='utf-8')
            questions = [{'id': 'q', 'text': 'What limits the result?'}]
            packets = [source_packet('p'+str(i), b'Failure persists.', questions) for i in range(2)]
            store = TaskStore(root/'store')
            workflow = ReviewWorkflow(store, packets, questions, group_size=2,source_quote_witness=witness,
                                      merge_full_source=merge_full_source,early_card_verification=early)
            graphs, identities, stages = [], [], []
            rejected=[]
            proof_executions=[]
            deadline = time.monotonic()+120

            def model(role, script):
                return ScriptedModel(role=role, script=script,
                    profile={'tool_calling': True, 'max_input_tokens': 200000, 'max_output_tokens': 16384})

            async def dispatch(stage, factory, tickets=None):
                stages.append(stage)

                def agent_factory(ready_tasks, workspace):
                    assigned = {}
                    count = [0]

                    def parent(messages, role):
                        count[0] += 1
                        cid = 'parent-'+str(count[0])
                        results = [m for m in messages if isinstance(m, ToolMessage)]
                        if not results or results[-1].name == 'task':
                            return AIMessage(content='', id=cid, tool_calls=[
                                {'name': 'ready_tasks', 'args': {}, 'id': cid+'-ready'}])
                        ready = json.loads(results[-1].content)
                        if ready['frontier_complete']:
                            return AIMessage(content='Assigned frontier complete; science is scripted.')
                        return AIMessage(content='', id=cid, response_metadata={'id': cid+'-response'},
                            tool_calls=[{'name': 'task', 'args': item, 'id': cid+'-task-'+str(i)}
                                        for i, item in enumerate(ready['ready'])])

                    def worker_factory(identity, description):
                        # Called only by the actual DeepAgents task middleware.
                        task = factory(identity, description)
                        identities.append(identity)
                        assigned[identity.context_id] = dict(task.inputs)
                        packet=next(iter(task.inputs.values()))
                        if isinstance(packet,dict) and packet.get('schema')=='hierarchical-proof-task/1':
                            proof_executions.append((stage,packet['node_id']))
                        return task

                    def worker_model(identity):
                        def script(messages, role):
                            human = next(m for m in messages if isinstance(m, HumanMessage))
                            delivered = re.findall(r"<assigned_input path='/inputs/([^']+)'>\n(.*?)\n</assigned_input>",
                                                   human.content, flags=re.DOTALL)
                            expected = assigned[identity.context_id]
                            actual = {name: text if isinstance(expected[name], str) else json.loads(text)
                                      for name, text in delivered}
                            self.assertEqual(actual, expected)
                            for name, text in delivered:
                                if not isinstance(expected[name], str):
                                    self.assertEqual(text, json.dumps(expected[name], ensure_ascii=False,
                                        sort_keys=True, default=str, separators=(',', ':')))
                            packet = next(iter(actual.values()))
                            data = scripted_submission(role, packet)
                            if (reject_early and stage.startswith('early-card-proofs') and packet.get('coverage',{}).get('claims')
                                    and (not rejected or reject_always)):
                                rejected.append(packet['node_id'])
                                data['status']='needs_revision'
                                data['verdicts'][0]['verdict']='needs_revision'
                                data['issues']=[{'unit_ids':[packet['coverage']['claims'][0]],
                                    'description':'Scripted scientific rejection; preserve original negative.',
                                    'correction':'Revise the actual card and recheck before comparison.'}]
                            if witness and packet.get('kind')=='source':
                                rows={row['claim_id']:row for row in packet['citation_view']['claim_rows']}
                                aliases=packet['responsibility_aliases']
                                for verdict in data['verdicts']:
                                    row=rows.get(aliases.get(verdict['unit_id'],verdict['unit_id']))
                                    if row:
                                        part=row['declared_parts'][0]
                                        verdict['clause_checks']=[{'clause':row['text'],'relation':'not_reported' if verdict['verdict']!='passed' else 'explicit_support',
                                            'witnesses':[{'ref':part['ref'],'quote':part['text']}],
                                            'reason':'Scripted literal test, no semantic approval'}]
                            return AIMessage(content='', tool_calls=[{'name': 'submit_result',
                                'args': {'data': data}, 'id': identity.context_id+'-submit'}])
                        return model(identity.role, script)

                    graph = create_review_agent(model('coordinator', parent), workspace, skills,
                        worker_factory=worker_factory, worker_model_factory=worker_model,
                        coordinator_tools=[ready_tasks], max_concurrency=2)
                    graphs.append(graph)
                    return graph

                scoped = ScopedTaskStore(store, tickets) if tickets is not None else store
                report = await run_frontiers(scoped, agent_factory, root/'stages'/stage,
                                             deadline, frontier_size=2)
                self.assertTrue(report['passed'], report)
                self.assertFalse(report['publication_verified'])
                self.assertEqual(report['deadline_at_monotonic'],deadline)
                if change_source and stage.startswith('early-card-proofs'):
                    workflow.packets[0]['parts'][0]['text']+=' changed source version'

            try:
                result = asyncio.run(workflow.run(dispatch))
            finally:
                self.last_stages,self.last_rows=stages,store.status()
            self.assertEqual(result['gate']['status'], 'passed')
            self.assertEqual(result['bundle']['merge_full_source'],merge_full_source)
            self.assertEqual(set(result['nodes']), set(result['bundle']['node_specs']))
            self.assertEqual(len(result['records']), 2)
            self.assertIn('comparison', ' '.join(stages))
            self.assertEqual(len({i.context_id for i in identities}), len(identities))
            self.assertEqual(sum(e['event'] == 'task_delegated' for g in graphs for e in g.events), len(identities))
            self.assertTrue(all(i.task_tool_call_id and i.coordinator_context_id for i in identities))
            self.assertTrue(all(row['status'] == 'accepted' for row in store.status()) if not reject_early else
                            any(row['status']=='failed' for row in store.status()))
            if early:
                self.assertEqual(workflow.early_card_history[-1]['status'],'qualified')
                early_ids=set(workflow.early_proof_nodes)
                final_executed={nid for stage,nid in proof_executions if stage.startswith('independent-proofs')}
                self.assertFalse(early_ids&final_executed)
                for nid,node in workflow.early_proof_nodes.items():
                    self.assertIs(result['nodes'][nid],node)
                for row in store.status():
                    if row['role']=='comparer':
                        with store._transaction() as db:
                            dependencies={r['dependency'] for r in db.execute('SELECT dependency FROM dependencies WHERE task=?',(row['id'],))}
                        self.assertTrue({q['ticket'] for q in workflow._early_qualified.values()}<=dependencies)
                if reject_early:
                    self.assertEqual(result['repair_rounds_used'],1)
                    self.assertLess(stages.index('early-card-revision-0'),stages.index('comparison'))
                    failure=next(h for h in workflow.early_card_history if h['status']=='needs_revision')
                    saved=store.get(failure['snapshot_hash'])
                    self.assertTrue(saved['submissions'])
                    self.assertTrue(saved['mini_bundle_hashes'])
            export_review(result, root/'delivery')
            self.assertEqual(result['source_quote_witness_required'],witness)
            if witness:
                expected={nid for nid,spec in result['bundle']['node_specs'].items() if spec['kind']=='source'}
                self.assertEqual(set(result['source_witness_audit']['source_nodes']),expected)
                persisted=json.loads((root/'delivery/proof/submissions.json').read_text(encoding='utf-8'))
                self.assertTrue(all('quote_witness' in persisted[nid] for nid in expected))
                result['proof_submissions'][next(iter(expected))].pop('quote_witness')
                with self.assertRaisesRegex(ValueError,'Missing source quote witness'):
                    export_review(result,root/'tampered-delivery')
                self.assertFalse((root/'tampered-delivery').exists())
                failed=save_review_attempt(result,root/'failed-attempt')
                self.assertFalse(failed['publication_verified'])
                self.assertEqual(failed['gate']['error']['code'],'SOURCE_WITNESS_AUDIT_FAILED')
            for filename in ('review.md', 'evidence-cards.md', 'comparison-table.md', 'README.md'):
                self.assertTrue((root/'delivery'/filename).is_file(), filename)
            self.assertFalse(network_attempts)


if __name__ == '__main__':
    unittest.main()
