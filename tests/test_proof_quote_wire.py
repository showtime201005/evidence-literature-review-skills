"""Unique-match adapter adversaries; zero API and no semantic pass claim."""
import copy
import json
from hashlib import sha256
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/literature-review/scripts/runtime'))
from litreview_core.hierarchical_proof import DIMENSIONS,payload_hash
from litreview_core.proof_quote_wire import (adapt_source_witness_wire,SourceWitnessWireSubmission,
    source_witness_tool_schema,unwrap_source_witness_tool_arguments)
from litreview_core.proof_quote_witness import WitnessValidationError,validate_source_witness_submission
from litreview_core.proof_submission_wire import alias_proof_packet,decode_proof_submission


class QuoteWireTests(unittest.TestCase):
    def setUp(self):
        self.a='原始😀來源：未測量成本。\r\n重複引文。 重複引文。\r\n'
        self.b='原始😀來源：未測量成本。\r\n第二段每月更新。\r\n'
        source=self.a+self.b
        self.packet={'schema':'hierarchical-proof-task/1','node_id':'source','kind':'source',
            'coverage':{dim:[] for dim in DIMENSIONS}, 'materials':{}, 'material_hashes':{},
            'required_dependency_ids':[],'dependency_proofs':{}}
        self.packet['coverage'].update(claims=['S/c1','S/c2'],obligations=['o1'])
        materials=self.packet['materials']
        materials['original/paper']=source
        materials['claim/S%2Fc1']={'claim_id':'S/c1','text':'成本未測量😀。更新頻率未報告。','evidence_refs':['paper/p1']}
        materials['claim/S%2Fc2']={'claim_id':'S/c2','text':'第二段每月更新。','evidence_refs':['paper/p2']}
        materials['o1']={'section_id':'S','definition':{'id':'o1','kind':'applicability'},
            'original_finding':{'text':'Actual unmeasured scope.'},
            'disposition':{'status':'included','claim_ids':['c1'],'reason':'Preserved named claim.'}}
        for pid,start,text in [('p1',0,self.a),('p2',len(self.a.encode('utf-8')),self.b)]:
            materials['locator/'+quote('paper/'+pid,safe='')]={'paper_id':'paper','part_id':pid,
                'start_byte':start,'end_byte':start+len(text.encode('utf-8')),
                'source_sha256':sha256(source.encode('utf-8')).hexdigest(),
                'text_sha256':sha256(text.encode('utf-8')).hexdigest()}
        self.rehash()
        self.value={'checked':copy.deepcopy(self.packet['coverage']),'verdicts':[
            {'unit_id':'S/c1','verdict':'passed','reason':'Per-unit reason one.','clause_checks':[
                self.clause('成本未測量😀。','paper/p1','原始😀來源：未測量成本。\r\n'),
                self.clause('更新頻率未報告。','paper/p1','原始😀來源：未測量成本。\r\n')]},
            {'unit_id':'S/c2','verdict':'passed','reason':'Per-unit reason two.','clause_checks':[
                self.clause('第二段每月更新。','paper/p2','第二段每月更新。')]},
            {'unit_id':'o1','verdict':'passed','reason':'Per-obligation original reason.'}],
            'status':'passed','reason':'Literal fixture only, not scientific approval.','issues':[]}
        self.addCleanup(patch.stopall)
        patch.object(socket,'create_connection',side_effect=AssertionError('No network in adapter tests')).start()
        import httpx
        patch.object(httpx.Client,'send',side_effect=AssertionError('No API in adapter tests')).start()
        patch.object(httpx.AsyncClient,'send',side_effect=AssertionError('No API in adapter tests')).start()

    @staticmethod
    def clause(text,ref,quote_text):
        return {'clause':text,'relation':'explicit_support','witnesses':[{'ref':ref,'quote':quote_text}],
                'reason':'This preserves the clause reason without asserting entailment.'}

    def rehash(self):
        self.packet['material_hashes']={key:(sha256(value.encode('utf-8')).hexdigest()
            if isinstance(key,str) and key.startswith('original/') else payload_hash(value))
            for key,value in self.packet['materials'].items()}

    def adapt(self,value=None,packet=None,**kwargs):
        return adapt_source_witness_wire(self.packet if packet is None else packet,
            self.value if value is None else value,**kwargs)

    def first(self,value=None):return (self.value if value is None else value)['verdicts'][0]['clause_checks'][0]
    def witness(self,value=None):return self.first(value)['witnesses'][0]

    def reject(self,code,value=None,packet=None,**kwargs):
        with self.assertRaises(WitnessValidationError) as caught:
            self.adapt(value,packet,**kwargs)
        self.assertEqual(caught.exception.code,code,caught.exception.as_dict())
        return caught.exception

    def test_unique_exact_coordinates_schema_hashes_and_immutable_inputs(self):
        before=copy.deepcopy(self.packet),copy.deepcopy(self.value)
        SourceWitnessWireSubmission.model_validate(self.value)
        result=self.adapt(expected_material_hashes=self.packet['material_hashes'])
        self.assertEqual(result['wire_submission'],self.value)
        self.assertEqual(result['wire_submission_sha256'],payload_hash(self.value))
        self.assertNotEqual(result['wire_submission_sha256'],result['canonical_witness_submission_sha256'])
        self.assertEqual(result['uniquely_resolved_clauses'],3)
        self.assertEqual(result['uniquely_resolved_quotes'],3)
        self.assertFalse(result['semantic_entailment_proven']);self.assertFalse(result['publication_verified'])
        canonical=result['canonical_witness_submission']
        first=canonical['verdicts'][0]['clause_checks'][0]
        self.assertEqual((first['start_char'],first['end_char']),(0,len('成本未測量😀。')))
        second=canonical['verdicts'][1]['clause_checks'][0]['witnesses'][0]
        expected_start=len(self.a.encode('utf-8'))+self.b.encode('utf-8').index('第二段每月更新。'.encode('utf-8'))
        self.assertEqual(second['start_byte'],expected_start)
        self.assertEqual(second['end_byte']-second['start_byte'],len('第二段每月更新。'.encode('utf-8')))
        self.assertEqual(validate_source_witness_submission(self.packet,canonical),result['literal_validation'])
        self.assertEqual((self.packet,self.value),before)

    def test_chinese_emoji_coordinates_are_codepoints_not_utf8_or_utf16(self):
        clause=self.adapt()['canonical_witness_submission']['verdicts'][0]['clause_checks'][0]
        text=clause['clause']
        self.assertEqual(clause['end_char'],len(text))
        self.assertNotEqual(clause['end_char'],len(text.encode('utf-8')))
        self.assertNotEqual(clause['end_char'],len(text.encode('utf-16-le'))//2)

    def test_crlf_is_exact_and_not_normalized(self):
        self.adapt()
        self.witness()['quote']=self.witness()['quote'].replace('\r\n','\n')
        self.reject('WIRE_QUOTE_NOT_FOUND')

    def test_repeated_quote_within_part_is_ambiguous(self):
        self.witness()['quote']='重複引文。'
        error=self.reject('WIRE_QUOTE_AMBIGUOUS')
        self.assertEqual(error.details['match_count'],2)

    def test_overlapping_quote_occurrences_are_not_missed(self):
        self.packet['materials']['original/paper']=self.packet['materials']['original/paper'].replace('重複引文。 重複引文。','aaa')
        raw=self.packet['materials']['original/paper'].encode('utf-8')
        a=self.a.replace('重複引文。 重複引文。','aaa')
        for part_id,start,text in [('p1',0,a),('p2',len(a.encode('utf-8')),self.b)]:
            loc=self.packet['materials']['locator/'+quote('paper/'+part_id,safe='')]
            loc.update(start_byte=start,end_byte=start+len(text.encode('utf-8')),
                source_sha256=sha256(raw).hexdigest(),text_sha256=sha256(text.encode('utf-8')).hexdigest())
        self.rehash();self.witness()['quote']='aa'
        self.assertEqual(self.reject('WIRE_QUOTE_AMBIGUOUS').details['match_count'],2)

    def test_same_quote_in_different_parts_resolves_only_within_named_part(self):
        self.value['verdicts'][1]['clause_checks'][0]['witnesses'][0]['quote']='原始😀來源：未測量成本。\r\n'
        canonical=self.adapt()['canonical_witness_submission']
        a=canonical['verdicts'][0]['clause_checks'][0]['witnesses'][0]
        b=canonical['verdicts'][1]['clause_checks'][0]['witnesses'][0]
        self.assertEqual(a['start_byte'],0)
        self.assertEqual(b['start_byte'],len(self.a.encode('utf-8')))

    def test_other_actual_part_cannot_repair_undeclared_ref(self):
        self.witness()['ref']='paper/p2'
        self.reject('WIRE_UNDECLARED_REF')

    def test_unknown_ref_and_nonexistent_quote_reject(self):
        self.witness()['ref']='other/unknown';self.reject('WIRE_UNDECLARED_REF')
        self.witness()['ref']='paper/p1';self.witness()['quote']='A fabricated quote.'
        self.reject('WIRE_QUOTE_NOT_FOUND')

    def test_repeated_clause_is_ambiguous_even_if_future_list_could_disambiguate(self):
        self.packet['materials']['claim/S%2Fc1']['text']='成本。成本。';self.rehash()
        self.value['verdicts'][0]['clause_checks']=[self.clause('成本。','paper/p1','原始😀來源：未測量成本。\r\n')]*2
        self.assertEqual(self.reject('WIRE_CLAUSE_AMBIGUOUS').details['match_count'],2)
        self.value['verdicts'][0]['clause_checks']=[self.clause('成本。成本。','paper/p1','原始😀來源：未測量成本。\r\n')]
        self.adapt()  # Longer exact context removes ambiguity, not an entailment proof.

    def test_reversed_clause_order_rejects(self):
        self.value['verdicts'][0]['clause_checks'].reverse()
        self.reject('WIRE_CLAUSE_NOT_FOUND')

    def test_claim_gap_and_missing_qualifier_still_fail_canonical_coverage(self):
        self.value['verdicts'][0]['clause_checks'].pop()
        self.value['status']='needs_revision'
        error=self.reject('WITNESS_UNCOVERED_CLAIM_TEXT')
        self.assertEqual(error.details['stage'],'canonical_validation')
        self.assertEqual(error.original_submission,self.value)
        self.assertTrue(error.semantic_negative_detected)

    def test_valid_negative_and_every_unit_reason_remain_unchanged(self):
        self.value['status']='needs_revision';self.value['verdicts'][0]['verdict']='needs_revision'
        self.first()['relation']='not_reported';self.first()['witnesses']=[]
        self.value['issues']=[{'unit_ids':['S/c1'],'description':'Scientific negative is retained.',
                               'correction':'Revise the actual science; no automatic pass retry.'}]
        result=self.adapt()
        self.assertTrue(result['semantic_negative_detected'])
        self.assertEqual(result['wire_submission'],self.value)
        existing=result['literal_validation']['proof_submission']
        self.assertEqual(existing['issues'],self.value['issues'])
        self.assertEqual([v['reason'] for v in existing['verdicts']],[v['reason'] for v in self.value['verdicts']])
        self.assertEqual(existing['status'],'needs_revision')

    def test_negative_and_schema_error_keep_deep_raw_snapshot(self):
        self.value['status']='needs_revision';self.witness()['start_byte']=0
        before=copy.deepcopy(self.value)
        error=self.reject('WIRE_SCHEMA_INVALID')
        self.value['status']='passed';self.witness()['quote']='mutated later'
        self.assertTrue(error.semantic_negative_detected)
        self.assertEqual(error.original_submission,before)
        exported=error.as_dict();exported['original_submission'].clear()
        self.assertEqual(error.original_submission,before)

    def test_negative_relation_plus_ambiguous_quote_is_terminal_preserved(self):
        self.first()['relation']='contradicted';self.witness()['quote']='重複引文。'
        error=self.reject('WIRE_QUOTE_AMBIGUOUS')
        self.assertTrue(error.semantic_negative_detected)
        self.assertEqual(error.original_submission,self.value)

    def test_passed_global_with_negative_unit_still_rejects_after_adaptation(self):
        self.value['verdicts'][0]['verdict']='needs_revision'
        self.assertTrue(self.reject('WITNESS_PASSED_CONTRADICTS_NEGATIVE').semantic_negative_detected)

    def test_model_supplied_coordinates_and_unknown_fields_forbidden(self):
        for target,key in [(self.first(),'start_char'),(self.witness(),'end_byte')]:
            target[key]=0;self.reject('WIRE_SCHEMA_INVALID');target.pop(key)
        self.value['producer']={'model':'not trusted'};self.reject('WIRE_SCHEMA_INVALID')

    def test_stale_source_version_and_trusted_expected_hash_fail_closed(self):
        expected=copy.deepcopy(self.packet['material_hashes'])
        self.packet['materials']['locator/paper%2Fp1']['source_sha256']='0'*64;self.rehash()
        self.reject('WIRE_SOURCE_CONTEXT_INVALID')
        self.reject('WIRE_INPUT_BINDING_MISMATCH',expected_material_hashes=expected)

    def test_no_original_does_not_borrow_context_or_reader_text(self):
        del self.packet['materials']['original/paper'];self.rehash()
        self.reject('WIRE_ORIGINAL_NOT_DELIVERED')

    def test_aliases_require_explicit_caller_decode_and_no_prose_rewriting(self):
        aliased_packet,aliases=alias_proof_packet(self.packet)
        self.reject('WIRE_NONCANONICAL_INPUT',packet=aliased_packet)
        inverse={uid:alias for alias,uid in aliases.items()};wire=copy.deepcopy(self.value)
        wire['checked']={dim:[inverse[uid] for uid in ids] for dim,ids in wire['checked'].items()}
        for verdict in wire['verdicts']:verdict['unit_id']=inverse[verdict['unit_id']]
        decoded=decode_proof_submission(wire,aliases)
        self.assertEqual(self.adapt(decoded)['wire_submission'],self.value)

    def test_nonclaim_clause_and_malformed_context_keep_negative_snapshot(self):
        self.value['verdicts'][-1]['clause_checks']=[copy.deepcopy(self.first())]
        self.value['issues']=[{'unit_ids':['o1'],'description':'Negative.','correction':'Revise.'}]
        self.assertTrue(self.reject('WIRE_CLAUSES_WRONG_SCOPE').semantic_negative_detected)
        del self.value['verdicts'][-1]['clause_checks']
        self.packet['materials'][7]={'bad':'material identity'};self.rehash()
        self.assertTrue(self.reject('WIRE_SOURCE_CONTEXT_INVALID').semantic_negative_detected)

    def test_outer_tool_schema_has_resolvable_full_contract(self):
        schema=source_witness_tool_schema()
        self.assertEqual(schema['required'],['data'])
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['properties']['data']['required'],['checked','verdicts','status','reason','issues'])
        def check(node):
            if isinstance(node,dict):
                if '$ref' in node:
                    self.assertIn(node['$ref'].removeprefix('#/$defs/'),schema['$defs'])
                for value in node.values():check(value)
            elif isinstance(node,list):
                for value in node:check(value)
        check(schema)

    def test_unwrap_exact_envelope_returns_copy_and_rejects_extra_missing_or_wrong_type(self):
        args={'data':copy.deepcopy(self.value)}
        unwrapped=unwrap_source_witness_tool_arguments(args)
        self.assertEqual(unwrapped,self.value);unwrapped['status']='unresolved'
        self.assertEqual(args['data']['status'],'passed')
        for value in ({}, {'data':self.value,'extra':1},{'data':[]}, {'data':json.dumps(self.value)}):
            with self.subTest(value_type=type(value.get('data')).__name__):
                with self.assertRaises(WitnessValidationError) as caught:
                    unwrap_source_witness_tool_arguments(value)
                self.assertEqual(caught.exception.code,'WIRE_TOOL_ARGUMENTS_INVALID')
                self.assertEqual(caught.exception.original_submission,value)

    def test_malformed_outer_negative_and_json_string_negative_are_retained(self):
        negative=copy.deepcopy(self.value);negative['status']='needs_revision'
        args_cases=[negative, {'data':self.value,'status':'needs_revision'},
            {'data':negative,'extra':True}, {'data':json.dumps(negative)},
            {'data':{'issues':{'description':'Malformed singleton negative issue.'}}},
            {'data':{'verdicts':{'verdict':'needs_revision'}}},
            {'data':{'verdicts':[{'clause_checks':{'relation':'contradicted'}}]}}]
        for args in args_cases:
            with self.subTest(args=args):
                # A valid outer envelope is unwrapped; its strict inner adapter
                # error still preserves the same scientific-negative flag.
                try:
                    data=unwrap_source_witness_tool_arguments(args)
                except WitnessValidationError as exc:
                    error=exc
                else:
                    with self.assertRaises(WitnessValidationError) as caught:
                        self.adapt(data)
                    error=caught.exception
                self.assertTrue(error.semantic_negative_detected,error.as_dict())

    def test_real_sdk_json_schema_dict_delivers_malformed_negative_to_callback(self):
        from langchain_core.tools import tool
        received=[]
        @tool(args_schema=source_witness_tool_schema())
        def submit_result(**arguments):
            """Capture raw arguments before strict witness validation."""
            raw=arguments;received.append(copy.deepcopy(raw))
            return self.adapt(unwrap_source_witness_tool_arguments(raw))
        negative=copy.deepcopy(self.value);negative['status']='needs_revision'
        negative['verdicts'][0]['clause_checks'][0]['witnesses'][0]['start_byte']=False
        with self.assertRaises(WitnessValidationError) as caught:
            submit_result.invoke({'data':negative})
        self.assertTrue(caught.exception.semantic_negative_detected)
        self.assertEqual(received,[{'data':negative}])
        with self.assertRaises(WitnessValidationError) as caught:
            submit_result.invoke({'status':'needs_revision'})
        self.assertTrue(caught.exception.semantic_negative_detected)
        self.assertEqual(received[-1],{'status':'needs_revision'})

    def test_real_native_selected_verifier_raw_arguments_preserve_terminal_negative(self):
        from langchain_core.messages import AIMessage,ToolMessage
        from litreview_core.native_agent import WorkerTask,create_review_agent
        from test_native_agent import ScriptedModel,Ancestry
        negative=copy.deepcopy(self.value);negative['status']='needs_revision'
        negative['verdicts'][0]['clause_checks'][0]['witnesses'][0]['start_byte']=False
        cases=[{'data':negative},{'status':'needs_revision'},
               {'data':None,'status':'needs_revision'},{'data':json.dumps(negative)}]
        for index,raw in enumerate(cases):
            with self.subTest(index=index),tempfile.TemporaryDirectory(prefix='qw-native-') as temporary:
                root=Path(temporary);skill=root/'skills/verify-citations';skill.mkdir(parents=True)
                (skill/'SKILL.md').write_text('---\nname: verify-citations\ndescription: Offline witness verifier fixture.\n---\n# Witness fixture\nPreserve independent negatives.\n',encoding='utf-8')
                identities,received=[],[];parent_calls=[0];worker_calls=[0]
                def parent(messages,role):
                    parent_calls[0]+=1
                    if parent_calls[0]==1:
                        return AIMessage(content='',id='actual-parent',tool_calls=[{'name':'task','id':'actual-task',
                            'args':{'subagent_type':'verifier','description':json.dumps({'ticket':'source-witness'})}}])
                    return AIMessage(content='The actual verifier requires revision; do not reroll it.')
                def worker(messages,role):
                    worker_calls[0]+=1
                    self.assertEqual(worker_calls[0],1,'Malformed science negative cannot prompt an ordinary retry')
                    return AIMessage(content='',tool_calls=[{'name':'submit_result','id':'actual-witness-submit','args':copy.deepcopy(raw)}])
                def model(role,script):
                    return ScriptedModel(role=role,script=script,profile={'tool_calling':True,
                        'max_input_tokens':200000,'max_output_tokens':16384})
                def factory(identity,description):
                    identities.append(identity)
                    self.assertEqual(identity.role,'verifier')
                    def accept(arguments,actual):
                        self.assertIs(actual,identity);received.append(copy.deepcopy(arguments))
                        return self.adapt(unwrap_source_witness_tool_arguments(arguments))
                    return WorkerTask('Return the complete independent source witness result.',{'proof-task.json':self.packet},
                        accept,submission_schema=source_witness_tool_schema(),raw_tool_arguments=True,max_model_calls=3)
                graph=create_review_agent(model('coordinator',parent),root/'run',skill.parent,worker_factory=factory,
                    worker_model_factory=lambda identity:model('verifier',worker),roles=('verifier',),coordinator_skill='verify-citations')
                self.assertEqual(identities,[],'No host worker dispatch before actual parent task')
                ancestry=Ancestry()
                result=graph.invoke({'messages':[{'role':'user','content':'Delegate this source ticket.'}]},
                                    {'callbacks':[ancestry]})
                receipt=json.loads(next(message.content for message in result['messages']
                    if isinstance(message,ToolMessage) and message.name=='task'))
                self.assertEqual(received,[raw]);self.assertEqual(worker_calls[0],1)
                self.assertEqual(receipt['status'],'needs_revision');self.assertFalse(receipt['accepted'])
                self.assertEqual(receipt['producer']['context_id'],identities[0].context_id)
                self.assertEqual(len(ancestry.task_runs),1)
                self.assertTrue(any(ancestry.below_task(run) for run in ancestry.model_runs))
                saved=list(identities[0].workspace.glob('submission-*.json'))
                self.assertEqual(len(saved),1)
                self.assertEqual(json.loads(saved[0].read_text(encoding='utf-8')),raw)


if __name__=='__main__':unittest.main()
