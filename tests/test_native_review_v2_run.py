"""Real native CLI/SDK v2 mechanics with local models, never a quality claim.

Only create_model is replaced on the successful and negative paths. The export
deadline test additionally injects an explicitly local exporter clock; the actual
exporter, workflow, dispatch, tokenizer, TaskStore and SDK remain in use. The
CLI run timer begins after Python imports; process-cold timing needs an external
launcher and is not measured by these tests.
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'skills/literature-review/scripts/runtime')]

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from test_native_agent import ScriptedModel
from test_paper_review_v2 import scripted_v2
from test_section_review_v2 import scripted_section
from test_review_workflow_native_sdk import scripted_submission
from litreview_core import native_review
from litreview_core.draft_wire import restore_draft_packet
from litreview_core.hierarchical_proof import payload_hash
from litreview_core.native_agent import ROLE_SKILLS
from litreview_core.paper_review_v2 import restore_paper_review_v2
from litreview_core.section_review_v2 import restore_section_review_v2
from litreview_core.task_store import TaskStore


TOKENIZER = ROOT.parent/'.cache/qwen3.8-27b-tokenizer.json'


@unittest.skipUnless(TOKENIZER.is_file(), 'Pinned local Qwen tokenizer is required; no download allowed')
class NativeReviewV2RunTests(unittest.TestCase):
    def test_cli_actual_sdk_four_deliveries_and_reader_off_factory_setting(self):
        self.exercise(reader_reasoning='off')

    def test_cli_exhausted_negative_preserves_partial_and_never_starts_comparison(self):
        self.exercise(always_negative=True)

    def test_cli_actual_export_honors_original_deadline_with_local_clock_injection(self):
        self.exercise(expire_during_export=True)

    def exercise(self, *, reader_reasoning='low', always_negative=False, expire_during_export=False):
        import httpx
        from litreview_core import delivery_export_v2

        network_attempts, model_calls, coordinator_calls, export_checks = [], [], [], []
        def blocked(*args, **kwargs):
            network_attempts.append(True)
            raise AssertionError('Network forbidden: native_review.run v2 offline integration')

        with tempfile.TemporaryDirectory(prefix='native-v2-cli-') as temporary, ExitStack() as stack:
            root = Path(temporary)
            sources, skills, output = root/'papers', root/'skills', root/'run'
            sources.mkdir()
            original = b'Failure persists.'
            for i in range(2):
                (sources/('p'+str(i)+'.md')).write_bytes(original)
            questions = root/'questions.json'
            questions.write_text(json.dumps([{'id':'q','text':'What limits the result?'}]), encoding='utf8')
            for skill in set(ROLE_SKILLS.values()) | {'literature-review'}:
                folder = skills/skill
                (folder/'references').mkdir(parents=True)
                (folder/'SKILL.md').write_text(
                    f'---\nname: {skill}\ndescription: Offline mechanics fixture.\n---\nUse assigned tools.',
                    encoding='utf8')
                for name in ('mapped-drafts.md','scientific-records.md','hierarchical-proof.md'):
                    (folder/'references'/name).write_text('Scripted mechanics; no scientific quality claim.',encoding='utf8')
            args = SimpleNamespace(sources=sources,questions=questions,out=output,skills_root=skills,
                tokenizer=TOKENIZER,workers=2,group_size=2,deadline=120.,review_protocol='v2',
                reviewer_max_output_tokens=16384,writer_reasoning='low',reviewer_reasoning='low',
                reader_reasoning=reader_reasoning,provider=None,coordinator_provider=None,
                proof_max_units=16,merge_full_source=False,source_quote_witness=False,
                early_card_verification=False,active_token_limit=1_000_000)

            def parent(messages, role):
                coordinator_calls.append(True)
                results = [m for m in messages if isinstance(m,ToolMessage)]
                if not results or results[-1].name == 'task':
                    return AIMessage(content='',tool_calls=[{
                        'id':'ready-'+str(len(messages)),'name':'ready_tasks','args':{}}])
                ready = json.loads(results[-1].content)
                if ready['frontier_complete']:
                    return AIMessage(content='Local scripted experimental protocol mechanics only.')
                return AIMessage(content='',tool_calls=[{
                    'id':'delegate-'+str(i),'name':'task','args':item}
                    for i,item in enumerate(ready['ready'])])

            def create_model(**options):
                if not options.get('force_submit'):
                    return ScriptedModel(role='coordinator',script=parent,profile={
                        'tool_calling':True,'max_input_tokens':200000,'max_output_tokens':4096})
                def worker(messages, unused_role):
                    human = next(m for m in messages if isinstance(m,HumanMessage))
                    inputs = {name:json.loads(text) for name,text in re.findall(
                        r"<assigned_input path='/inputs/([^']+)'>\n(.*?)\n</assigned_input>",human.content,re.S)}
                    self.assertTrue(inputs, 'SDK must deliver actual assigned input')
                    if 'source.json' in inputs:
                        role='reader'
                        value=scripted_submission(role,inputs['source.json'])
                    elif 'draft-packet.json' in inputs:
                        wire=inputs['draft-packet.json']
                        role='comparer' if restore_draft_packet(wire)['kind']=='comparison' else 'writer'
                        value=scripted_submission(role,wire)
                        if 'revision.json' in inputs:
                            # A revision changes the actual artifact; no reviewer reroll.
                            old=inputs['revision.json']['previous_draft']['claims'][0]['text']
                            value['claims'][0]['text']=old+'（修訂版）'
                    elif 'paper-review-v2.json' in inputs:
                        role='verifier-paper'
                        p=restore_paper_review_v2(inputs['paper-review-v2.json'])
                        value=scripted_v2({'payload':p},negative=always_negative and p['source']['paper_id']=='p0')
                    elif 'section-review-v2.json' in inputs:
                        role='verifier-section'
                        value=scripted_section({'payload':restore_section_review_v2(inputs['section-review-v2.json'])})
                    else:
                        raise AssertionError('Unrecognized actual native worker input: '+str(sorted(inputs)))
                    model_calls.append({'role':role,'options':options,'inputs':inputs})
                    return AIMessage(content='',tool_calls=[{
                        'id':'submit-local-'+str(len(model_calls)),'name':'submit_result','args':{'data':value}}])
                return ScriptedModel(role='worker',script=worker,profile={
                    'tool_calling':True,'max_input_tokens':200000,'max_output_tokens':32768})

            stack.enter_context(patch.object(native_review,'create_model',create_model))
            stack.enter_context(patch.object(socket,'create_connection',blocked))
            stack.enter_context(patch.object(httpx.Client,'send',blocked))
            stack.enter_context(patch.object(httpx.AsyncClient,'send',blocked))
            if expire_during_export:
                def expired_export_clock():
                    # Only this module sees the injected time. Real asyncio and
                    # the entire native workflow keep the real monotonic clock.
                    caller=sys._getframe(1)
                    self.assertEqual(caller.f_code.co_name,'deadline')
                    declared=caller.f_locals['deadline_at']
                    export_checks.append(declared)
                    return declared+1.
                stack.enter_context(patch.object(delivery_export_v2,'time',
                                                SimpleNamespace(monotonic=expired_export_clock)))
            stdout=io.StringIO()
            before=time.monotonic()
            with redirect_stdout(stdout):
                code=asyncio.run(native_review.run(args))
            after=time.monotonic()

            report=json.loads((output/'review-result.json').read_text(encoding='utf8'))
            summary=json.loads(stdout.getvalue().strip().splitlines()[-1])
            expected_failure=always_negative or expire_during_export
            self.assertEqual(code,1 if expected_failure else 0, report.get('error'))
            self.assertEqual(report['passed'],not expected_failure)
            self.assertEqual(summary['passed'],report['passed'])
            self.assertEqual(report['review_protocol'],'v2')
            self.assertFalse(report['publication_verified'])
            self.assertFalse(report['quality_validated'])
            self.assertEqual(report['protocol_completed_experimental'],not expected_failure)
            self.assertTrue(report['cold_run'])
            self.assertEqual(report['papers'],2)
            self.assertTrue(report['includes_retries_repairs_verification_delivery'])
            self.assertEqual(report['deadline_seconds'],args.deadline)
            self.assertGreaterEqual(report['elapsed_seconds'],0)
            self.assertLessEqual(report['elapsed_seconds'],after-before)
            self.assertEqual(network_attempts,[])
            self.assertTrue(coordinator_calls)
            self.assertEqual(report['reader_reasoning_mode'],reader_reasoning)
            self.assertTrue(all(c['options']['reasoning_enabled']==(reader_reasoning!='off')
                                for c in model_calls if c['role']=='reader'))
            self.assertTrue(all(c['options']['reasoning_enabled'] is True
                                for c in model_calls if c['role']!='reader'))
            self.assertTrue(all(c['options']['max_tokens']==16384 for c in model_calls))
            self.assertIsNone(report['proof_max_units'])
            self.assertFalse(report['merge_full_source'])
            self.assertFalse(report['source_quote_witness_experiment'])
            # Re-open the same actual database, rather than manufacturing task statuses.
            store=TaskStore(output/'artifacts')
            self.assertEqual(report['tasks'],store.status())
            for source in sources.iterdir():self.assertEqual(source.read_bytes(),original)

            if expected_failure:
                self.assertNotIn('archive_error',report['error'])
                manifest=json.loads((output/'unpublished-attempt/manifest.json').read_text(encoding='utf8'))
                self.assertEqual(manifest['status'],'unpublished_attempt')
                self.assertFalse(manifest['protocol_completed_experimental'])
                self.assertFalse(manifest['publication_verified'])
                self.assertFalse((output/'delivery/manifest.json').exists())
                attempts=json.loads((output/'unpublished-attempt/raw/review-attempts/index.json').read_text(encoding='utf8'))
                self.assertTrue(attempts)
                self.assertTrue((output/'unpublished-attempt/raw/native/index.json').is_file())
                if always_negative:
                    self.assertIn('repair budget exhausted',report['error']['message'])
                    self.assertEqual(report['repair_rounds_used'],2)
                    self.assertEqual(len(report['repair_history']),3)
                    self.assertFalse(any(c['role']=='comparer' for c in model_calls))
                    self.assertFalse(any(c['role']=='verifier-section' for c in model_calls))
                    archived=[json.loads((output/'unpublished-attempt'/p).read_text(encoding='utf8')) for p in attempts]
                    negative=[a for a in archived if a['attempt']['status']=='needs_revision']
                    self.assertEqual(len(negative),3)
                    self.assertEqual(len({a['review_id'] for a in negative}),3)
                    self.assertTrue(all(a['attempt']['raw_tool_arguments']['data']['issues'] for a in negative))
                else:
                    self.assertEqual(report['error']['type'],'TimeoutError')
                    self.assertIn('during experimental export',report['error']['message'])
                    self.assertTrue(export_checks)
                    # The original run deadline, not a fresh export allowance.
                    self.assertGreaterEqual(export_checks[0],before+args.deadline)
                    self.assertLessEqual(export_checks[0],after+args.deadline)
                    self.assertEqual(len(report['tasks']),10)
                    self.assertTrue(all(t['status']=='accepted' for t in report['tasks']))
                    self.assertTrue(report['within_deadline']) # host clock was not advanced
                return

            self.assertIsNone(report['error'])
            self.assertTrue(report['within_deadline'])
            self.assertEqual(len(report['tasks']),10)
            self.assertTrue(all(t['status']=='accepted' for t in report['tasks']))
            self.assertTrue(all(s['status']=='completed' for s in report['stages']))
            self.assertFalse((output/'unpublished-attempt').exists())
            manifest=json.loads((output/'delivery/manifest.json').read_text(encoding='utf8'))
            self.assertEqual(manifest['status'],'protocol_completed_experimental')
            self.assertFalse(manifest['publication_verified'])
            self.assertFalse(manifest['quality_validated'])
            for name in ('main-review.md','evidence-cards.md','comparison-table.md','comparison-cells.csv',
                         'citations.json','source-spans.json','raw/native/index.json'):
                self.assertTrue((output/'delivery'/name).is_file(),name)
            citations=json.loads((output/'delivery/citations.json').read_text(encoding='utf8'))
            self.assertEqual(set(citations['sources']),{'p0','p1'})
            for item in citations['sources'].values():
                self.assertEqual((output/'delivery'/item['path']).read_bytes(),original)
            for name,info in manifest['files'].items():
                self.assertEqual(payload_hash((output/'delivery'/name).read_bytes()),info['sha256'])
            provenance=json.loads((output/'delivery/audit/runtime-identities.json').read_text(encoding='utf8'))
            self.assertEqual(len(provenance['identities']),10)
            self.assertTrue(all(i['task_call_id'] and i['parent_context_id'] for i in provenance['identities'].values()))


if __name__=='__main__':unittest.main()
