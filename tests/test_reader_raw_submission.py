"""Actual failed Qwen reader arguments replayed through strict zero-network gates."""
import asyncio
import copy
from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'skills/literature-review/scripts/runtime')]
from langchain_core.messages import AIMessage,HumanMessage,ToolMessage
from test_native_agent import ScriptedModel
from test_review_workflow_native_sdk import scripted_submission
from litreview_core import native_reading
from litreview_core.native_agent import ROLE_SKILLS,create_review_agent
from litreview_core.native_reading import reader_tool_schema,validate_reader_arguments
from litreview_core.reader_worker import reader_worker
from litreview_core.scientific_records import source_packet
from litreview_core.task_store import TaskStore

FIXTURES=ROOT/'tests/fixtures/reader_failed_20261020'
TOKENIZER=ROOT.parent/'.cache/qwen3.8-27b-tokenizer.json'


def fixture(name):return json.loads((FIXTURES/name).read_text(encoding='utf8'))


class RawReaderTests(unittest.TestCase):
    def test_two_actual_extra_field_submissions_rejected_without_echo_or_mutation(self):
        for pid in ('s01','s08'):
            with self.subTest(paper=pid):
                raw=fixture(pid+'-call-1.json');before=copy.deepcopy(raw)
                with self.assertRaises(ValueError) as raised:
                    validate_reader_arguments(fixture(pid+'-source.json'),raw,execution_id='offline')
                message=str(raised.exception)
                self.assertEqual(message,'Reader schema errors: [{"loc":["data","questions_note"],"type":"extra_forbidden"}]')
                self.assertEqual(raw,before)
                self.assertNotIn(raw['data']['findings'][0]['text'],message)
                self.assertLess(len(message),200)
        provenance=fixture('provenance.json')
        for name,item in provenance['files'].items():
            self.assertEqual(hashlib.sha256((FIXTURES/name).read_bytes()).hexdigest(),item['sha256'])

    def test_actual_field_mismatch_reports_all_conflicts_with_counts_and_ids(self):
        packet=fixture('s01-source.json');raw=fixture('s01-call-2.json')
        before=copy.deepcopy(raw)
        with self.assertRaisesRegex(ValueError,'Field status contradicts extracted findings: ') as raised:
            validate_reader_arguments(packet,raw,execution_id='offline')
        conflicts=json.loads(str(raised.exception).split(': ',1)[1])
        expected=[]
        for row in raw['data']['fields']:
            ids=[f['local_id'] for f in raw['data']['findings'] if f['field']==row['field']]
            if bool(ids)!=(row['status']=='extracted'):
                expected.append({'field':row['field'],'status':row['status'],'finding_count':len(ids),
                    'finding_ids':ids,'expected_status':['extracted'] if ids else ['not_reported','not_applicable','unresolved']})
        self.assertTrue(expected)
        self.assertEqual(conflicts,expected)
        self.assertEqual(raw,before)
        self.assertNotIn(raw['data']['findings'][0]['text'],str(raised.exception))

    def test_strings_extra_envelope_and_numeric_coercions_are_rejected(self):
        packet=source_packet('p',b'Failure persists.',[{'id':'q','text':'What limits the result?'}])
        good={'data':scripted_submission('reader',packet)}
        self.assertEqual(validate_reader_arguments(packet,good,execution_id='offline')['paper_id'],'p')
        bad=[{'data':json.dumps(good['data'])},{**copy.deepcopy(good),'extra':None}]
        numeric=copy.deepcopy(good);numeric['data']['findings'][0]['evidence'][0]['start_char']='0';bad.append(numeric)
        boolean=copy.deepcopy(good);boolean['data']['findings'][0]['evidence'][0]['start_char']=True;bad.append(boolean)
        for value in bad:
            with self.subTest(value_type=type(value['data']).__name__),self.assertRaisesRegex(ValueError,'Reader schema errors: '):
                validate_reader_arguments(packet,value,execution_id='offline')
        schema=reader_tool_schema()
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['properties']['data']['$ref'],'#/$defs/ReaderSubmission')

    def test_real_sdk_s08_first_invalid_raw_is_saved_and_second_actual_submission_accepts(self):
        self.exercise('s08')

    def test_real_sdk_s01_stops_at_original_three_calls_with_all_raw_preserved(self):
        self.exercise('s01')

    @unittest.skipUnless(TOKENIZER.is_file(),'Pinned tokenizer missing; never download in regression')
    def test_direct_native_reading_cli_uses_same_raw_validation_and_short_feedback(self):
        self.exercise('s08',direct_cli=True)

    def exercise(self,pid,*,direct_cli=False):
        import httpx
        packet=fixture(pid+'-source.json')
        expected=[fixture(pid+'-call-'+str(i)+'.json') for i in range(1,3 if pid=='s08' else 4)]
        calls=[];feedback=[];network=[];identities=[]
        def blocked(*a,**k):network.append(True);raise AssertionError('Zero-network actual reader regression')
        with tempfile.TemporaryDirectory(prefix='raw-reader-') as temporary,ExitStack() as stack:
            root=Path(temporary);skills=root/'skills'
            for name in set(ROLE_SKILLS.values())|{'literature-review'}:
                folder=skills/name;(folder/'references').mkdir(parents=True)
                (folder/'SKILL.md').write_text('---\nname: '+name+'\ndescription: Offline reader mechanics.\n---\nUse assigned tools.',encoding='utf8')
                (folder/'references/scientific-records.md').write_text('Scripted mechanics only.',encoding='utf8')
            for owner,method in ((socket,'create_connection'),(httpx.Client,'send'),(httpx.AsyncClient,'send')):
                stack.enter_context(patch.object(owner,method,blocked))
            def worker(messages,role):
                self.assertLess(len(calls),len(expected),'Original maximum call budget must not grow')
                tools=[m for m in messages if isinstance(m,ToolMessage)]
                if tools:feedback.append(tools[-1].content)
                value=copy.deepcopy(expected[len(calls)]);calls.append(value)
                return AIMessage(content='',tool_calls=[{'id':'submit-'+str(len(calls)),'name':'submit_result','args':value}])
            def model(role,script):return ScriptedModel(role=role,script=script,profile={
                'tool_calling':True,'max_input_tokens':200000,'max_output_tokens':16384})
            if direct_cli:
                papers=root/'papers';papers.mkdir()
                (papers/(pid+'.md')).write_bytes(b''.join(p['text'].encode('utf8') for p in packet['parts']))
                q=root/'questions.json';q.write_text(json.dumps(packet['questions']),encoding='utf8')
                def parent(messages,role):
                    tools=[m for m in messages if isinstance(m,ToolMessage)]
                    if not tools or tools[-1].name=='task':
                        return AIMessage(content='',tool_calls=[{'id':'ready-'+str(len(messages)),'name':'ready_tasks','args':{}}])
                    ready=json.loads(tools[-1].content)
                    if not ready['ready']:return AIMessage(content='Scripted reader mechanics only.')
                    return AIMessage(content='',tool_calls=[{'id':'delegate-'+str(i),'name':'task','args':x} for i,x in enumerate(ready['ready'])])
                stack.enter_context(patch.object(native_reading,'create_model',lambda **kw:model(
                    'reader' if kw.get('force_submit') else 'coordinator',worker if kw.get('force_submit') else parent)))
                args=SimpleNamespace(out=root/'run',sources=papers,questions=q,tokenizer=TOKENIZER,
                    workers=1,deadline=120.,skills_root=skills,verify_records=False)
                with redirect_stdout(io.StringIO()):code=asyncio.run(native_reading.run(args))
                self.assertEqual(code,0)
                self.assertTrue(json.loads((root/'run/reading-result.json').read_text(encoding='utf8'))['passed'])
                workspace=root/'run/agents'
            else:
                store=TaskStore(root/'store');ticket=store.create('reader',packet,max_attempts=1)
                def factory(identity,description):
                    identities.append(identity)
                    task=reader_worker(store,identity,json.loads(description)['ticket'])
                    self.assertTrue(task.raw_tool_arguments)
                    self.assertEqual(task.max_model_calls,3)
                    return task
                def parent(messages,role):
                    if any(isinstance(m,ToolMessage) for m in messages):return AIMessage(content='Honest task result received.')
                    return AIMessage(content='',tool_calls=[{'id':'actual-task','name':'task','args':{
                        'subagent_type':'reader','description':json.dumps({'ticket':ticket})}}])
                workspace=root/'agents'
                agent=create_review_agent(model('coordinator',parent),workspace,skills,worker_factory=factory,
                    worker_model_factory=lambda identity:model(identity.role,worker),max_concurrency=1)
                asyncio.run(agent.ainvoke({'messages':[HumanMessage(content='Delegate the exact supplied reader task.')]},
                                          {'recursion_limit':40}))
                rows=store.status();self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['status'],'accepted' if pid=='s08' else 'failed')
                self.assertTrue(identities[0].task_tool_call_id)
                self.assertTrue(identities[0].coordinator_context_id)
            self.assertEqual(calls,expected)
            self.assertEqual(network,[])
            self.assertTrue(feedback)
            first=json.loads(feedback[0])
            self.assertIn('questions_note',first['error'])
            self.assertIn('extra_forbidden',first['error'])
            self.assertLess(len(feedback[0]),1000)
            self.assertNotIn(expected[0]['data']['findings'][0]['text'],feedback[0])
            submissions=[json.loads(p.read_text(encoding='utf8')) for p in workspace.rglob('submission-*.json')]
            self.assertEqual(len(submissions),len(expected))
            for value in expected:self.assertIn(value,submissions)


if __name__=='__main__':unittest.main()
