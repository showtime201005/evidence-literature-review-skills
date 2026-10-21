"""Offline isolated local-claim protocol + actual 12-task SDK integration."""
import asyncio
import copy
from hashlib import sha256
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reports'))
import claim_entailment_prototype as prototype
prototype.bootstrap()
from litreview_core.hierarchical_proof import DIMENSIONS,payload_hash


def source_fixture(count=12):
    texts=[f'Original study {i:02d} measured quantity {i}; frequency remains unreported.\r\n' for i in range(1,count+1)]
    raw=''.join(texts).encode('utf-8');source_sha=sha256(raw).hexdigest()
    materials={'original/paper':raw.decode('utf-8')};coverage={dim:[] for dim in DIMENSIONS};start=0
    for index,text in enumerate(texts,1):
        cid=f'S/c{index:02d}';ref=f'paper/p{index:02d}'
        materials['claim/'+quote(cid,safe='')]={'claim_id':cid,
            'text':f'研究{index:02d}量值為{index}；頻率未報告。','evidence_refs':[ref]}
        materials['locator/'+quote(ref,safe='')]={'paper_id':'paper','part_id':f'p{index:02d}',
            'start_byte':start,'end_byte':start+len(text.encode('utf-8')),
            'source_sha256':source_sha,'text_sha256':sha256(text.encode('utf-8')).hexdigest()}
        coverage['claims'].append(cid);start+=len(text.encode('utf-8'))
    return {'schema':'hierarchical-proof-task/1','kind':'source','node_id':'source',
        'coverage':coverage,'materials':materials,'material_hashes':{mid:source_sha if mid=='original/paper' else payload_hash(value)
            for mid,value in materials.items()},'required_dependency_ids':[],'dependency_proofs':{}}


class FixtureCounter:
    identity={'method':'test-only coarse estimate; not scientific sizing'}
    def __call__(self,payload):return (len(prototype.canonical(payload))+3)//4+2048


class LocalClaimPrototypeTests(unittest.TestCase):
    def setUp(self):
        self.packet=source_fixture();self.locals=prototype.build_claim_inputs(self.packet)
        self.addCleanup(patch.stopall)
        patch.object(socket,'create_connection',side_effect=AssertionError('Network forbidden')).start()
        import httpx
        patch.object(httpx.Client,'send',side_effect=AssertionError('Network forbidden')).start()
        patch.object(httpx.AsyncClient,'send',side_effect=AssertionError('Network forbidden')).start()

    def test_projection_only_own_actual_claim_and_complete_version_bound_parts(self):
        before=copy.deepcopy(self.packet)
        self.assertEqual(len(self.locals),12)
        for index,value in enumerate(self.locals,1):
            self.assertEqual(value['claim_id'],f'S/c{index:02d}')
            self.assertEqual(value['declared_refs'],[f'paper/p{index:02d}'])
            self.assertEqual(len(value['parts']),1)
            self.assertIn(f'study {index:02d}',value['parts'][0]['text'])
            self.assertEqual(value['parts'][0]['source_sha256'],sha256(self.packet['materials']['original/paper'].encode('utf-8')).hexdigest())
            self.assertNotIn('reader',value);self.assertNotIn('other_claims',value)
            self.assertFalse(value['full_source_delivered'])
        self.assertEqual(self.packet,before)

    def test_minimum_units_do_not_claim_english_sentence_splitting(self):
        text='First sentence. Second sentence；Third;第四。'
        self.assertEqual([v['text'] for v in prototype.split_units(text)],['First sentence. Second sentence；','Third;','第四。'])

    def test_source_hash_tamper_and_extra_host_fields_rejected(self):
        value=copy.deepcopy(self.locals[0]);value['host_gold']='Must fail'
        with self.assertRaises(ValueError):prototype.check_input(value)
        value=copy.deepcopy(self.locals[0]);value['parts'][0]['text']='modified'
        with self.assertRaises(ValueError):prototype.check_input(value)
        packet=copy.deepcopy(self.packet);packet['materials']['original/paper']+='tampered'
        with self.assertRaises(ValueError):prototype.build_claim_inputs(packet)

    def test_complete_unresolved_protocol_preserves_negative_without_science_claim(self):
        value=prototype.fixture_submission(self.locals[0]);before=copy.deepcopy(value)
        result=prototype.validate_submission(self.locals[0],value)
        self.assertEqual(result['submission'],value['data'])
        self.assertFalse(result['semantic_entailment_proven']);self.assertFalse(result['component_atomicity_proven'])
        self.assertFalse(result['full_source_verified']);self.assertFalse(result['publication_verified'])
        self.assertEqual(value,before)

    def test_exact_unique_quote_and_original_byte_offset(self):
        packet=self.locals[1];value=prototype.fixture_submission(packet)
        component=value['data']['units'][0]['components'][0]
        text=packet['parts'][0]['text'];component['quotes']=[{'ref':'paper/p02','quote':text}]
        component['support_status']='explicit_support';value['data']['unsupported_components'].pop(0)
        result=prototype.validate_submission(packet,value)
        quote=result['resolved'][0]['quotes'][0]
        self.assertEqual(quote['start_byte'],packet['parts'][0]['start_byte'])
        self.assertEqual(quote['end_byte']-quote['start_byte'],len(text.encode('utf-8')))
        component['quotes'][0]['quote']=text.replace('\r\n','\n')
        with self.assertRaises(prototype.LocalError):prototype.validate_submission(packet,value)

    def test_unknown_ref_missing_component_and_malformed_negative_snapshot(self):
        packet=self.locals[0];value=prototype.fixture_submission(packet)
        value['data']['units'][0]['components'][0]['quotes']=[{'ref':'paper/p02','quote':self.locals[1]['parts'][0]['text']}]
        with self.assertRaises(prototype.LocalError) as caught:prototype.validate_submission(packet,value)
        self.assertTrue(caught.exception.semantic_negative_detected)
        self.assertEqual(caught.exception.original_submission,value)
        value=prototype.fixture_submission(packet);value['data']['units'].pop()
        with self.assertRaises(prototype.LocalError) as caught:prototype.validate_submission(packet,value)
        self.assertEqual(caught.exception.code,'LOCAL_UNIT_COVERAGE')
        value=prototype.fixture_submission(packet);value['data']['units'][0]['components'][0]['extra']='invalid'
        with self.assertRaises(prototype.LocalError) as caught:prototype.validate_submission(packet,value)
        saved=copy.deepcopy(value);value.clear()
        self.assertTrue(caught.exception.semantic_negative_detected)
        self.assertEqual(caught.exception.original_submission,saved)

    def test_pass_cannot_hide_unsupported_component_and_model_identity_forbidden(self):
        packet=self.locals[0];value=prototype.fixture_submission(packet);value['data']['status']='passed'
        with self.assertRaises(prototype.LocalError) as caught:prototype.validate_submission(packet,value)
        self.assertEqual(caught.exception.code,'LOCAL_PASS_CONTRADICTS_NEGATIVE')
        value['data']['producer']={'context_id':'forged'}
        with self.assertRaises(prototype.LocalError) as caught:prototype.validate_submission(packet,value)
        self.assertTrue(caught.exception.semantic_negative_detected)

    def local_literal_submission(self,text,fragments):
        packet=copy.deepcopy(self.locals[0]);packet['claim_text']=text;packet['units']=prototype.split_units(text)
        value=prototype.fixture_submission(packet)
        self.assertEqual(len(value['data']['units']),len(fragments))
        identifiers=[]
        for index,(unit,parts) in enumerate(zip(value['data']['units'],fragments),1):
            unit['components']=[]
            for number,fragment in enumerate(parts,1):
                cid=f'u{index}-c{number}';identifiers.append(cid)
                unit['components'].append({'component_id':cid,'text':fragment,'kind':'other_factual',
                    'support_status':'unresolved','quotes':[],'reason':'Offline literal coverage control, not science judgment.'})
        value['data']['unsupported_components']=identifiers
        return packet,value

    def test_runtime_records_only_whitelisted_delimiters_and_whitespace_exact_spans(self):
        text='😀數值為-0.10，\r\n頻率≤2 mg；條件未測。'
        packet,value=self.local_literal_submission(text,[['😀數值為-0.10','頻率≤2 mg'],['條件未測']])
        original=copy.deepcopy(value)
        result=prototype.validate_submission(packet,value)
        self.assertEqual(value,original);self.assertEqual(result['submission'],original['data'])
        binding=result['literal_gap_binding'];self.assertEqual(binding['allowed_nonwhitespace'],['，','；','。'])
        self.assertEqual([gap['text'] for gap in binding['gaps']],['，\r\n','；','。'])
        for gap in binding['gaps']:
            self.assertEqual(text[gap['start_char_in_claim']:gap['end_char_in_claim']],gap['text'])
            self.assertEqual(text.encode('utf-8')[gap['start_byte_in_claim']:gap['end_byte_in_claim']].decode('utf-8'),gap['text'])
            unit=next(u['text'] for u in packet['units'] if u['unit_id']==gap['unit_id'])
            self.assertEqual(unit.encode('utf-8')[gap['start_byte_in_unit']:gap['end_byte_in_unit']].decode('utf-8'),gap['text'])
        self.assertEqual(result['submission']['status'],'unresolved')
        self.assertFalse(result['semantic_entailment_proven'])

    def test_any_uncovered_scientific_character_or_nonwhitelisted_symbol_still_rejected(self):
        cases=[('數值-0.10。',['數值','0.10']),('數值0.10。',['數值0','10']),
            ('數值≤2。',['數值','2']),('數值>2。',['數值','2']),('數值<2。',['數值','2']),
            ('數值±2。',['數值','2']),('數值2 mg。',['數值2']),('條件不成立。',['條件','成立']),
            ('結果無效。',['結果','效']),('條件與結果。',['條件','結果']),
            ('結果：數值2。',['結果','數值2']),('條件、結果。',['條件','結果']),
            ('結果,條件。',['結果','條件'])]
        for text,fragments in cases:
            with self.subTest(text=text):
                packet,value=self.local_literal_submission(text,[fragments])
                original=copy.deepcopy(value)
                with self.assertRaises(prototype.LocalError) as caught:prototype.validate_submission(packet,value)
                self.assertEqual(caught.exception.code,'LOCAL_COMPONENT_GAP')
                self.assertTrue(caught.exception.semantic_negative_detected)
                self.assertEqual(caught.exception.original_submission,original)
                self.assertEqual(value,original)

    def test_whitelisted_gaps_do_not_allow_pass_to_erase_negative(self):
        packet,value=self.local_literal_submission('條件未測，結果未知。',[['條件未測','結果未知']])
        value['data']['status']='passed'
        with self.assertRaises(prototype.LocalError) as caught:prototype.validate_submission(packet,value)
        self.assertEqual(caught.exception.code,'LOCAL_PASS_CONTRADICTS_NEGATIVE')
        self.assertTrue(caught.exception.semantic_negative_detected)

    def test_whitelisted_gaps_do_not_relax_declared_ref_or_exact_quote_checks(self):
        packet,value=self.local_literal_submission('條件未測，結果未知。',[['條件未測','結果未知']])
        component=value['data']['units'][0]['components'][0]
        component['quotes']=[{'ref':'paper/foreign','quote':'Original study'}]
        with self.assertRaises(prototype.LocalError) as caught:prototype.validate_submission(packet,value)
        self.assertEqual(caught.exception.code,'LOCAL_UNDECLARED_REF')

    def test_actual_sdk_12_parallel_tasks_isolation_identity_and_receipts(self):
        with tempfile.TemporaryDirectory(prefix='local12-') as temporary:
            root=Path(temporary);skill=root/'skills/verify-citations';(skill/'references').mkdir(parents=True)
            (skill/'SKILL.md').write_text('---\nname: verify-citations\ndescription: Offline local fixture.\n---\n# Verify local claims\n',encoding='utf-8')
            (skill/'references/claim-entailment-local.md').write_text(prototype.REFERENCE,encoding='utf-8')
            stats=asyncio.run(prototype.offline_preflight(self.locals,root/'run',skill.parent,FixtureCounter()))
            self.assertTrue(stats['no_model_api']);self.assertTrue(stats['all_judgments_recorded'])
            self.assertEqual(stats['actual_parent_task_events'],12)
            self.assertEqual(stats['actual_worker_contexts'],12)
            self.assertEqual(stats['measured_peak_active_requests'],12)
            self.assertTrue(stats['all_initial_leaves_fit_active_token_limit'])
            report=prototype.read(root/'run/experiment.json')
            identities=report['actual_workers'];self.assertEqual(len({i['context_id'] for i in identities}),12)
            self.assertEqual({i['parent_model_message_id'] for i in identities},{'offline-parent-parallel-task-turn'})
            self.assertEqual(len({i['task_tool_call_id'] for i in identities}),12)
            self.assertTrue(all(i['model_id']=='offline-qwen-wire-capture-not-inference' for i in identities))
            self.assertEqual(report['model_status_counts']['unresolved'],12)
            self.assertIsNone(report['quality_pass']);self.assertFalse(report['native_proof_gate_executed'])
            artifacts=prototype.read(root/'run/local-results.json')
            for artifact in artifacts:
                self.assertEqual(artifact['scope'],prototype.SCOPE)
                self.assertFalse(artifact['publication_verified']);self.assertFalse(artifact['native_proof_gate_executed'])
                self.assertEqual(artifact['actual_worker_identity']['role'],'verifier')
            messages=prototype.read(root/'run/native/coordinator-messages.json')
            serialized=json.dumps(messages,ensure_ascii=False)
            for packet in self.locals:self.assertNotIn(packet['claim_text'],serialized)
            ready=json.loads(next(item['data']['content'] for item in messages
                if item['type']=='tool' and item['data'].get('name')=='ready_tasks'))
            descriptions={row['ticket']:row['description'] for row in ready['tickets']}
            self.assertEqual(len(descriptions),12)
            for ticket,description in descriptions.items():
                self.assertEqual(description,prototype.canonical({'ticket':ticket}).decode('utf-8'))
            task_calls=[call for item in messages if item['type']=='ai'
                for call in item['data'].get('tool_calls',[]) if call['name']=='task']
            self.assertEqual(len(task_calls),12)
            for call in task_calls:
                ticket=json.loads(call['args']['description'])['ticket']
                self.assertEqual(call['args']['description'],descriptions[ticket])
            captures=prototype.read(root/'run/complete-wire-captures.json')
            ready_schema=next(tool['function'] for entry in captures if entry['role']=='coordinator'
                for tool in entry['payload']['tools'] if tool['function']['name']=='ready_tasks')
            self.assertEqual(ready_schema['parameters']['type'],'object')
            self.assertIn('canonical JSON descriptions',ready_schema['description'])

    def test_actual_sdk_prose_description_still_rejected_without_broadening_factory(self):
        with tempfile.TemporaryDirectory(prefix='localbad-') as temporary:
            root=Path(temporary);skill=root/'skills/verify-citations';(skill/'references').mkdir(parents=True)
            (skill/'SKILL.md').write_text('---\nname: verify-citations\ndescription: Offline local fixture.\n---\n# Local\n',encoding='utf-8')
            (skill/'references/claim-entailment-local.md').write_text(prototype.REFERENCE,encoding='utf-8')
            stats=asyncio.run(prototype.offline_preflight(self.locals[:1],root/'run',skill.parent,
                FixtureCounter(),bad_description_fixture=True))
            self.assertFalse(stats['all_judgments_recorded']);self.assertEqual(stats['actual_worker_contexts'],0)
            report=prototype.read(root/'run/experiment.json')
            self.assertEqual(report['error']['type'],'JSONDecodeError')
            self.assertEqual(report['telemetry']['admitted_requests'],2)


if __name__=='__main__':unittest.main()
