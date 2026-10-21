"""Offline source-scope CLI integration through real DeepAgents task graphs."""
import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'skills/literature-review/scripts/runtime'))
sys.path.insert(0, str(ROOT/'tests'))
from langchain_core.messages import AIMessage, ToolMessage
from test_native_agent import ScriptedModel
from litreview_core import native_task
from litreview_core.hierarchical_proof import DIMENSIONS
from litreview_core.proof_planner import plan_review
from litreview_core.review_artifacts import draft_packet, validate_draft
from litreview_core.scientific_records import FIELDS, source_packet, validate_reader
from litreview_core.task_store import TaskStore, canonical


def fixture():
    questions = [{'id': 'effect', 'text': 'What effect is measured?'},
                 {'id': 'conditions', 'text': 'Which conditions constrain it?'}]
    packet = source_packet('paper', b'# Synthetic\r\n\r\nContrast +0.01, CI [-0.02,+0.04], includes zero.\r\n\r\nFailure persists; monetary cost was not measured.\r\n', questions)
    findings = [
        {'local_id': 'result', 'field': 'results', 'text': 'The contrast remains uncertain.',
         'attribution': 'author_result', 'evidence': [{'part_id': packet['parts'][1]['part_id'], 'quote': None}],
         'obligations': ['null_result']},
        {'local_id': 'limit', 'field': 'limitations', 'text': 'Failure persists and monetary cost is unknown.',
         'attribution': 'author_limitation', 'evidence': [{'part_id': packet['parts'][2]['part_id'], 'quote': None}],
         'obligations': ['persistent_failure', 'missing_measurement']}]
    record = validate_reader(packet, {
        'observations': [{'part_id': part['part_id'], 'note': 'Read '+part['text'].strip()} for part in packet['parts']],
        'findings': findings,
        'fields': [{'field': field, 'status': 'extracted' if field in ('results', 'limitations') else 'unresolved',
                    'reason': 'Bounded synthetic fixture, no quality approval.'} for field in FIELDS],
        'questions': [{'question_id': question['id'], 'status': 'addressed', 'reason': 'Source-linked result and caveat.',
                       'support': ['result'], 'counterevidence': ['limit']} for question in questions]}, execution_id='original-reader')
    draft = draft_packet('paper_card', [packet], [record], questions)
    claims = [{'local_id': name, 'text': finding['text'],
        'evidence_refs': ['paper/'+packet['parts'][index+1]['part_id']],
        'question_ids': [questions[index]['id']], 'attribution': 'source_finding',
        'scope': 'individual', 'population_paper_ids': ['paper'], 'premise_claim_ids': []}
        for index,(name,finding) in enumerate(zip(('result', 'limit'), findings))]
    card = validate_draft(draft, {'claims': claims, 'cells': [],
        'retention': [{'obligation_id': item['id'], 'status': 'included',
                       'claim_ids': ['result' if item['kind'] == 'null_result' else 'limit'],
                       'reason': 'Actual claim preserves this qualification.'} for item in draft['obligations']]},
        execution_id='original-writer')
    bundle = plan_review([card], [packet], [record])
    node_id = next(key for key,spec in bundle['node_specs'].items()
                   if spec['kind'] == 'source' and spec['role'] == 'verifier' and not spec['dependencies'])
    return {'schema': 'native-proof-input/1', 'packets': [packet], 'records': [record],
            'sections': [card], 'node_id': node_id}, bundle


class FakeCounter:
    def __init__(self, path):
        self.identity = {'method': 'offline fixture, not actual Qwen usage'}
        self.tokenizer = SimpleNamespace(encode=lambda text, **kwargs: SimpleNamespace(ids=list(range(32))))

    def __call__(self, payload):
        return 32


class NativeTaskVerifierTests(unittest.TestCase):
    def setUp(self):
        self.value, self.bundle = fixture()
        self.temp = tempfile.TemporaryDirectory(prefix='source-task-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.network_attempts = []

        def blocked(*args, **kwargs):
            self.network_attempts.append(True)
            raise AssertionError('No network in native verifier fixture')
        self.addCleanup(patch.stopall)
        patch.object(socket, 'create_connection', blocked).start()
        import httpx
        patch.object(httpx.Client, 'send', blocked).start()
        patch.object(httpx.AsyncClient, 'send', blocked).start()

    def test_explicit_proof_unit_limit_is_bound_to_reconstruction(self):
        bundle=native_task.prepare_verifier_input(self.value,proof_max_units=32)
        self.assertEqual(bundle['max_scientific_units'],32)
        for limit in (0,129,True,1.5):
            with self.assertRaisesRegex(ValueError,'Proof unit limit'):
                native_task.prepare_verifier_input(self.value,proof_max_units=limit)

    def test_merge_option_is_rebuilt_from_original_inputs_not_an_external_proof(self):
        bundle=native_task.prepare_verifier_input(self.value,merge_full_source=True)
        spec=bundle['node_specs'][self.value['node_id']]
        self.assertTrue(bundle['merge_full_source'])
        self.assertTrue(spec['coverage']['claims'])
        self.assertTrue(any(bundle['materials'][uid]['definition']['kind']=='full_source_review'
                            for uid in spec['coverage']['obligations']))
        self.assertIn('original/paper',spec['input_ids'])
        self.assertEqual(spec['dependencies'],[])

    def test_rebuilds_actual_source_reader_draft_and_rejects_external_proof(self):
        rebuilt = native_task.prepare_verifier_input(self.value)
        self.assertEqual(rebuilt['plan'], self.bundle['plan'])
        for key in ('dependency_proofs', 'materials', 'producer', 'bundle'):
            value = {**self.value, key: {'status': 'passed'}}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'external dependency proofs'):
                native_task.prepare_verifier_input(value)

    def test_rejects_unknown_node_and_dependency_or_non_source_scope(self):
        value = {**self.value, 'node_id': 'unknown-source'}
        with self.assertRaisesRegex(ValueError, 'Unknown verifier node'):
            native_task.prepare_verifier_input(value)
        dependent = next(key for key,spec in self.bundle['node_specs'].items() if spec['dependencies'])
        with self.assertRaisesRegex(ValueError, 'dependency-free source'):
            native_task.prepare_verifier_input({**self.value, 'node_id': dependent})

    def test_rejects_source_reader_and_draft_tampering(self):
        for target in ('source', 'reader', 'draft'):
            value = copy.deepcopy(self.value)
            if target == 'source':
                value['packets'][0]['parts'][1]['text'] += ' changed'
            elif target == 'reader':
                value['records'][0]['evidence'][0]['quote'] = 'forged evidence'
            else:
                value['sections'][0]['claims'][0]['text'] = 'All queries benefit.'
            with self.subTest(target=target), self.assertRaises(ValueError):
                native_task.prepare_verifier_input(value)

    def test_lease_failed_on_preparation_and_incomplete_execution(self):
        store = TaskStore(self.root/'store')
        ticket = store.create('verifier', {**self.value, 'node_id': 'unknown'}, max_attempts=1)
        identity = SimpleNamespace(role='verifier', context_id='actual-verifier')
        with self.assertRaises(ValueError):
            native_task.source_proof_worker(store, identity, ticket)
        self.assertEqual(store.status()[0]['status'], 'failed')
        ticket = store.create('verifier', self.value, max_attempts=1)
        worker = native_task.source_proof_worker(store, identity, ticket)
        worker.on_finish(identity, {'error': 'Original provider failure'})
        self.assertEqual(store.status()[-1]['status'], 'failed')
        self.assertIn('Original provider failure', store.status()[-1]['error'])

    def args(self, name='run', role='verifier'):
        source = self.root/'input.json'
        source.write_text(json.dumps(self.value), encoding='utf-8')
        skills = self.root/'skills/verify-citations'
        (skills/'references').mkdir(parents=True, exist_ok=True)
        (skills/'SKILL.md').write_text('---\nname: verify-citations\ndescription: Offline source verifier.\n---\nRead original scientific materials.', encoding='utf-8')
        (skills/'references/hierarchical-proof.md').write_text('Inspect assigned units; honest negative findings are terminal.', encoding='utf-8')
        return argparse.Namespace(input=source, out=self.root/name, skills_root=self.root/'skills',
            tokenizer=self.root/'not-used-tokenizer', role=role, tool_choice='forced',
            provider=None, deadline=25., max_model_calls=3, reasoning='low')

    def model_factory(self, negative=False, witness=False):
        counts = [0]
        coverage = self.bundle['node_specs'][self.value['node_id']]['coverage']
        units = coverage['claims'] + coverage['obligations']
        submission = {'checked': coverage, 'verdicts': [{'unit_id': unit, 'verdict': 'passed',
            'reason': 'Offline scripted fixture only; no semantic inference.'} for unit in units],
            'status': 'passed', 'reason': 'Offline structurally valid source responsibility.', 'issues': []}
        if negative:
            submission['status'] = 'needs_revision'
            submission['verdicts'][0].update(verdict='needs_revision', reason='Synthetic fixture finding')
            submission['issues'] = [{'unit_ids': [units[0]], 'description': 'Synthetic fixture defect',
                                     'correction': 'Retain source uncertainty'}]
        if witness:
            from litreview_core.proof_planner import node_payload
            from litreview_core.proof_citation_view import build_citation_view
            packet=node_payload(self.bundle,self.value['node_id'],{})
            rows={row['claim_id']:row for row in build_citation_view(packet)['claim_rows']}
            for verdict in submission['verdicts']:
                if verdict['unit_id'] in rows:
                    row=rows[verdict['unit_id']]
                    part=row['declared_parts'][0]
                    verdict['clause_checks']=[{'clause':row['text'],
                        'relation':'topic_only' if verdict['verdict']!='passed' else 'explicit_support',
                        'witnesses':[{'ref':part['ref'],'quote':part['text']}],
                        'reason':'Scripted literal fixture, not semantic approval'}]

        def parent(messages, role):
            counts[0] += 1
            tools = [message for message in messages if isinstance(message, ToolMessage)]
            call_id = 'parent-'+str(counts[0])
            if not tools or tools[-1].name == 'task':
                return AIMessage(content='', id=call_id, tool_calls=[{'name': 'ready_tasks', 'args': {}, 'id': call_id+'-ready'}])
            ready = json.loads(tools[-1].content)
            if ready['frontier_complete']:
                return AIMessage(content='Assigned source responsibility ended; no publication approval.')
            return AIMessage(content='', id=call_id, response_metadata={'id': call_id+'-response'},
                tool_calls=[{'name': 'task', 'args': item, 'id': call_id+'-task'} for item in ready['ready']])

        def worker(messages, role):
            return AIMessage(content='', tool_calls=[{'name': 'submit_result', 'args': {'data': submission}, 'id': 'actual-source-submit'}])

        def factory(**kwargs):
            role = 'verifier' if kwargs['max_tokens'] in (16384,32768) else 'coordinator'
            return ScriptedModel(role=role, script=worker if role == 'verifier' else parent,
                profile={'tool_calling': True, 'max_input_tokens': 200000, 'max_output_tokens': kwargs['max_tokens']})
        return factory

    def run_native(self, *, negative=False, witness=False):
        args = self.args()
        args.quote_witness=witness
        with patch.object(native_task, 'QwenRequestCounter', FakeCounter), patch.object(native_task, 'create_model', self.model_factory(negative,witness)):
            code = asyncio.run(native_task.run(args))
        report = json.loads((args.out/'task-result.json').read_text(encoding='utf-8'))
        self.assertTrue((args.out/'proof-result.json').exists(), report)
        proof = json.loads((args.out/'proof-result.json').read_text(encoding='utf-8'))
        self.assertFalse(report['publication_verified'])
        self.assertFalse(report['full_review_cold_acceptance'])
        self.assertEqual(report['input_sha256'], hashlib.sha256(canonical(self.value)).hexdigest())
        self.assertEqual(proof['actual_worker_identity']['role'], 'verifier')
        self.assertEqual(proof['runtime_identity']['execution_id'], proof['actual_worker_identity']['context_id'])
        self.assertTrue(proof['runtime_identity']['task_call_id'])
        self.assertEqual(proof['input_sha256'], report['input_sha256'])
        self.assertEqual(self.network_attempts, [])
        self.assertEqual({path.name for path in (args.out/'native/rounds/round-0001/coordinator/skills').iterdir()}, {'verify-citations'})
        return code, report, proof, args

    def test_larger_output_reservation_is_forwarded_to_actual_worker_model(self):
        args=self.args('larger-output')
        args.max_output_tokens=32768
        with patch.object(native_task,'QwenRequestCounter',FakeCounter), \
                patch.object(native_task,'create_model',side_effect=self.model_factory()) as models:
            code=asyncio.run(native_task.run(args))
        self.assertEqual(code,0)
        self.assertEqual([call.kwargs['max_tokens'] for call in models.call_args_list],[4096,32768])
        report=json.loads((args.out/'task-result.json').read_text(encoding='utf-8'))
        self.assertEqual(report['worker_max_output_tokens'],32768)
        self.assertEqual(self.network_attempts,[])

    def test_actual_sdk_selected_verifier_delegation_persists_positive_and_receipt(self):
        code, report, proof, args = self.run_native()
        self.assertEqual(code, 0, report)
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['task']['status'], 'accepted')
        self.assertEqual(proof['node']['payload']['status'], 'passed')
        self.assertEqual(set(proof['node']['payload']['coverage']), set(DIMENSIONS))
        frontier = json.loads((args.out/'native/frontier-result.json').read_text(encoding='utf-8'))
        self.assertTrue(frontier['rounds'][0]['delegation_proofs'])
        self.assertEqual(json.loads((args.out/'artifact.json').read_text(encoding='utf-8')), proof)

    def test_actual_sdk_quote_witness_negative_keeps_full_audit(self):
        code,report,proof,args=self.run_native(negative=True,witness=True)
        self.assertEqual(code,1)
        self.assertTrue(report['quote_witness_experiment'])
        audit=proof['submission']['quote_witness']
        self.assertTrue(audit['literal_validation']['literal_checks_completed'])
        self.assertFalse(audit['semantic_entailment_proven'])
        self.assertEqual(audit['original_tool_arguments']['data']['status'],'needs_revision')
        self.assertEqual(proof['node']['payload']['status'],'needs_revision')

    def test_actual_sdk_negative_submission_is_retained_and_not_accepted(self):
        code, report, proof, args = self.run_native(negative=True)
        self.assertEqual(code, 1)
        self.assertFalse(report['passed'])
        self.assertEqual(report['task']['status'], 'failed')
        self.assertEqual(proof['node']['payload']['status'], 'needs_revision')
        self.assertEqual(proof['submission']['verdicts'][0]['verdict'], 'needs_revision')
        self.assertTrue(proof['submission']['issues'])
        self.assertFalse((args.out/'artifact.json').exists())
        self.assertTrue(list((args.out/'native').rglob('submission-*.json')))
        digest = report['source_verification']['attestation_hashes'][0]
        self.assertEqual(TaskStore(args.out/'artifacts').get(digest), proof)

    def test_preflight_unknown_node_and_wrong_role_create_no_output_or_model(self):
        self.value['node_id'] = 'unknown'
        args = self.args()
        with patch.object(native_task, 'QwenRequestCounter', FakeCounter), patch.object(native_task, 'create_model') as model:
            with self.assertRaisesRegex(ValueError, 'Unknown verifier node'):
                asyncio.run(native_task.run(args))
            self.assertFalse(args.out.exists())
            model.assert_not_called()
        args.role = 'writer'
        with patch.object(native_task, 'create_model') as model:
            with self.assertRaisesRegex(ValueError, 'only be used with --role verifier'):
                asyncio.run(native_task.run(args))
            self.assertFalse(args.out.exists())
            model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
