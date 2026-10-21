"""Source-first experiment only: literal integrity, true SDK dependencies, no API."""
import asyncio
import copy
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'reports'))
import source_first_claim_prototype as sf
sf.local.bootstrap()


def packets_fixture(count=12):
    texts=[f'Study {i:02d} records event A before event B. Evidence suggests a possible relation. Rate is monthly.\r\n'
           for i in range(1,count+1)]
    raw=''.join(texts).encode();version=sha256(raw).hexdigest();packets=[];offset=0
    for i,text in enumerate(texts,1):
        ref=f'paper/p{i:03d}';claim=f'研究{i:02d}只報告可能關係；頻率未核。'
        part={'ref':ref,'text':text,'start_byte':offset,'end_byte':offset+len(text.encode()),
            'source_sha256':version,'text_sha256':sha256(text.encode()).hexdigest()}
        packets.append({'schema':'local-claim-entailment-input/1','scope':sf.local.SCOPE,'claim_id':f'card/c{i:02d}',
            'claim_text':claim,'declared_refs':[ref],'parts':[part],'units':sf.local.split_units(claim),
            'provenance':{'canonical_task_sha256':version,'canonical_claim_material_sha256':sf.local.digest(claim)},
            'full_source_delivered':False})
        offset=part['end_byte']
    if count>1:
        packets[1]['declared_refs'].append(packets[0]['declared_refs'][0])
        packets[1]['parts'].append(copy.deepcopy(packets[0]['parts'][0]))
    return packets


class FixtureCounter:
    identity={'method':'test-only coarse counter, not Qwen sizing'}
    def __call__(self,payload):return (len(sf.local.canonical(payload))+3)//4+2048


def fixture_skills(root):
    for name in ('analyze-paper','verify-citations'):
        skill=root/'skills'/name;(skill/'references').mkdir(parents=True)
        (skill/'SKILL.md').write_text(f'---\nname: {name}\ndescription: Source-first offline test.\n---\n# Experimental responsibility\n',encoding='utf-8')
        (skill/'references/source-first-local.md').write_text(sf.SOURCE_REFERENCE if name=='analyze-paper' else sf.VERIFY_REFERENCE,encoding='utf-8')
    return root/'skills'


class SourceFirstTests(unittest.TestCase):
    def setUp(self):
        self.packets=packets_fixture();self.source=sf.source_input(self.packets)
        self.ledger=sf.validate_ledger(self.source,sf.fixture_ledger(self.source))
        self.receipt={'ticket':'actual-source-ticket','output_hash':'a'*64}

    def test_source_input_deduplicates_complete_parts_without_claims(self):
        self.assertEqual(len(self.source['parts']),12)
        self.assertFalse(self.source['claim_text_delivered'])
        self.assertEqual(set(self.source),{'schema','scope','parts','claim_text_delivered','source_relation_index_is_proof'})
        text=json.dumps(self.source,ensure_ascii=False)
        for original in self.packets:self.assertNotIn(original['claim_text'],text);self.assertNotIn(original['claim_id'],text)
        for original in self.packets:
            for part in original['parts']:self.assertIn(part,self.source['parts'])
        bad=copy.deepcopy(self.packets);bad[1]['parts'][-1]['text']='altered'
        with self.assertRaises(ValueError):sf.source_input(bad)

    def test_source_ledger_exact_quote_endpoints_and_inventory(self):
        raw=sf.fixture_ledger(self.source);before=copy.deepcopy(raw)
        result=sf.validate_ledger(self.source,raw)
        self.assertEqual(raw,before);self.assertFalse(result['semantic_relations_proven'])
        self.assertTrue(result['derived_index_not_proven_facts'])
        for fact in result['resolved']:
            for quote in fact['quotes']:
                part=next(p for p in self.source['parts'] if p['ref']==quote['ref'])
                relative=quote['start_byte']-part['start_byte']
                self.assertEqual(part['text'].encode()[relative:relative+len(quote['quote'].encode())].decode(),quote['quote'])
        raw['data']['facts'][0]['relation_text']='invented edge'
        with self.assertRaises(sf.SourceFirstError) as caught:sf.validate_ledger(self.source,raw)
        self.assertEqual(caught.exception.code,'SF_SOURCE_ENDPOINT')
        self.assertIn(raw['data']['facts'][0]['fact_id'],str(caught.exception))
        self.assertIn('relation_text',str(caught.exception))
        self.assertEqual(caught.exception.original_submission,raw)

    def test_source_overflow_is_explicit_terminal_not_silent_128_selection(self):
        raw=sf.fixture_ledger(self.source);raw['data']['recording_status']='capacity_exceeded'
        raw['data']['unrecorded_reason']='More explicit relations than this output can preserve.'
        with self.assertRaises(sf.SourceFirstError) as caught:sf.validate_ledger(self.source,raw)
        self.assertEqual(caught.exception.code,'SF_LEDGER_INCOMPLETE')
        self.assertTrue(caught.exception.semantic_negative_detected)
        self.assertEqual(caught.exception.original_submission,raw)
        raw=sf.fixture_ledger(self.source);raw['data']['facts']=[copy.deepcopy(raw['data']['facts'][0]) for _ in range(129)]
        with self.assertRaises(sf.SourceFirstError) as caught:sf.validate_ledger(self.source,raw)
        self.assertEqual(caught.exception.code,'SF_LEDGER_CAPACITY')
        self.assertTrue(caught.exception.semantic_negative_detected)
        self.assertEqual(len(caught.exception.original_submission['data']['facts']),129)
        raw=sf.fixture_ledger(self.source);raw['data']['reviewed_refs'].pop()
        with self.assertRaises(sf.SourceFirstError) as caught:sf.validate_ledger(self.source,raw)
        self.assertEqual(caught.exception.code,'SF_REVIEWED_REFS')

    def test_projection_uses_only_wholly_own_refs_and_preserves_receipt_binding(self):
        projected=sf.project_ledger(self.packets[0],self.ledger,self.receipt)
        self.assertEqual(projected['local'],self.packets[0])
        self.assertEqual(projected['ledger']['source_output_hash'],'a'*64)
        self.assertEqual(len(projected['ledger']['facts']),1)
        for fact in projected['ledger']['facts']:
            self.assertTrue(set(q['ref'] for q in fact['quotes'])<=set(self.packets[0]['declared_refs']))
        changed=copy.deepcopy(self.ledger)
        changed['submission']['facts'][0]['quotes'].append(changed['submission']['facts'][1]['quotes'][0])
        projected=sf.project_ledger(self.packets[0],changed,self.receipt)
        self.assertEqual(projected['ledger']['facts'],[])

    def test_unit_ids_cover_original_text_without_retyping_all_characters(self):
        projected=sf.project_ledger(self.packets[0],self.ledger,self.receipt);raw=sf.fixture_verifier(projected)
        result=sf.validate_verifier(projected,raw)
        self.assertTrue(result['all_original_unit_ids_covered']);self.assertFalse(result['component_atomicity_proven'])
        self.assertFalse(result['semantic_entailment_proven']);self.assertEqual(result['submission']['status'],'unresolved')
        raw['data']['units'].pop()
        with self.assertRaises(sf.SourceFirstError) as caught:sf.validate_verifier(projected,raw)
        self.assertEqual(caught.exception.code,'SF_UNIT_COVERAGE');self.assertTrue(caught.exception.semantic_negative_detected)

    def test_foreign_fact_ref_and_target_endpoint_are_rejected(self):
        projected=sf.project_ledger(self.packets[0],self.ledger,self.receipt)
        for mode in ('fact','ref','endpoint'):
            with self.subTest(mode=mode):
                raw=sf.fixture_verifier(projected);check=raw['data']['units'][0]['assertions'][0]
                if mode=='fact':check['ledger_fact_ids']=['f999']
                elif mode=='ref':check['new_quotes']=[{'ref':'paper/p002','quote':self.packets[1]['parts'][0]['text']}]
                else:check['anchor_text']='not in actual unit'
                with self.assertRaises(sf.SourceFirstError) as caught:sf.validate_verifier(projected,raw)
                self.assertTrue(caught.exception.semantic_negative_detected)

    def test_malformed_negative_envelopes_preserve_raw_and_detection_boundary(self):
        projected=sf.project_ledger(self.packets[0],self.ledger,self.receipt);raw=sf.fixture_verifier(projected)
        for malformed in ({'data':json.dumps(raw['data'])},json.dumps(raw),{'status':'needs_revision','data':None}):
            with self.subTest(malformed=type(malformed).__name__):
                with self.assertRaises(sf.SourceFirstError) as caught:sf.validate_verifier(projected,malformed)
                self.assertTrue(caught.exception.semantic_negative_detected)
                self.assertEqual(caught.exception.original_submission,malformed)
        malformed='{"data":{"status":"needs_revision",'
        with self.assertRaises(sf.SourceFirstError) as caught:sf.validate_verifier(projected,malformed)
        self.assertFalse(caught.exception.semantic_negative_detected)
        self.assertEqual(caught.exception.original_submission,malformed)
        # Arbitrary malformed text is preserved, never interpreted by keyword guessing.

    def test_pass_cannot_hide_unit_or_assertion_negative(self):
        projected=sf.project_ledger(self.packets[0],self.ledger,self.receipt);raw=sf.fixture_verifier(projected)
        raw['data']['units'][0]['verdict']='passed'
        with self.assertRaises(sf.SourceFirstError) as caught:sf.validate_verifier(projected,raw)
        self.assertEqual(caught.exception.code,'SF_UNIT_PASS_NEGATIVE')

    def test_actual_sdk_two_stages_dependencies_isolation_and_negative_receipts(self):
        with tempfile.TemporaryDirectory(prefix='source-first-') as folder:
            root=Path(folder);skills=fixture_skills(root)
            stats=asyncio.run(sf.offline_preflight(self.packets,root/'run',skills,FixtureCounter()))
            self.assertTrue(stats['all_judgments_recorded']);self.assertTrue(stats['no_model_api'])
            self.assertEqual(stats['actual_workers'],13);self.assertEqual(stats['actual_role_counts'],{'reader':1,'verifier':12})
            self.assertEqual(stats['actual_task_delegations'],13);self.assertEqual(stats['parent_calls'],5)
            self.assertEqual(stats['peak_active_requests'],12)
            report=sf.local.read(root/'run/experiment.json');identities=report['actual_workers']
            self.assertEqual(len({i['context_id'] for i in identities}),13)
            self.assertEqual(len({i['parent_model_message_id'] for i in identities if i['role']=='verifier'}),1)
            events=report['stage_events'];source_accept=next(i for i,e in enumerate(events) if e['event']=='accepted' and e['role']=='reader')
            self.assertTrue(all(i>source_accept for i,e in enumerate(events) if e['event']=='worker_claimed' and e['role']=='verifier'))
            with closing(sqlite3.connect(root/'run/artifacts/tasks.sqlite3')) as db:
                edges=db.execute('SELECT task,dependency FROM dependencies').fetchall()
                self.assertEqual(len(edges),12);self.assertEqual(len({d for _,d in edges}),1)
            artifacts=sf.local.read(root/'run/artifacts-recorded.json')
            self.assertEqual(sum(a['validation']['submission'].get('status')=='unresolved' for a in artifacts),12)
            for artifact in artifacts:self.assertFalse(artifact['publication_verified']);self.assertFalse(artifact['native_proof_gate_executed'])
            captures=sf.local.read(root/'run/complete-wire-captures.json');reader=next(c for c in captures if c['role']=='reader')
            text=json.dumps(reader['payload'],ensure_ascii=False)
            for packet in self.packets:self.assertNotIn(packet['claim_text'],text)
            messages=sf.local.read(root/'run/native/coordinator-messages.json');serialized=json.dumps(messages,ensure_ascii=False)
            for packet in self.packets:self.assertNotIn(packet['claim_text'],serialized)

    def test_actual_sdk_reader_failure_does_not_publish_verifiers(self):
        with tempfile.TemporaryDirectory(prefix='source-first-fail-') as folder:
            root=Path(folder);skills=fixture_skills(root)
            stats=asyncio.run(sf.offline_preflight(self.packets,root/'run',skills,FixtureCounter(),reader_failure=True))
            self.assertFalse(stats['all_judgments_recorded']);self.assertEqual(stats['actual_role_counts'],{'reader':1,'verifier':0})
            report=sf.local.read(root/'run/experiment.json');self.assertEqual(len(report['tasks']),1)

    def test_actual_sdk_reader_off_wire_keeps_verifier_low_and_forced_tools(self):
        with tempfile.TemporaryDirectory(prefix='source-first-off-') as folder:
            root=Path(folder);skills=fixture_skills(root)
            stats=asyncio.run(sf.offline_preflight(self.packets[:2],root/'run',skills,FixtureCounter(),
                reader_output_tokens=32768,reader_reasoning_enabled=False,context_limit=65536,provider='cerebras/fp16'))
            self.assertTrue(stats['all_judgments_recorded']);self.assertEqual(stats['context_limit'],65536)
            captures=sf.local.read(root/'run/complete-wire-captures.json')
            reader=next(c for c in captures if c['role']=='reader')
            self.assertEqual(reader['payload']['reasoning'],{'enabled':False})
            self.assertEqual(reader['payload']['tool_choice'],{'type':'function','function':{'name':'submit_result'}})
            for capture in captures:
                if capture['role']=='verifier':
                    self.assertEqual(capture['payload']['reasoning'],{'enabled':True,'effort':'low'})
                    self.assertEqual(capture['payload']['tool_choice'],{'type':'function','function':{'name':'submit_result'}})

    def test_actual_sdk_malformed_negative_saved_once_without_reroll(self):
        with tempfile.TemporaryDirectory(prefix='source-first-neg-') as folder:
            root=Path(folder);skills=fixture_skills(root)
            stats=asyncio.run(sf.offline_preflight(self.packets,root/'run',skills,FixtureCounter(),malformed_negative=True))
            self.assertFalse(stats['all_judgments_recorded'])
            captures=sf.local.read(root/'run/complete-wire-captures.json')
            self.assertEqual(sum(c['role']=='verifier' for c in captures),12)
            errors=[sf.local.read(p) for p in (root/'run/native').rglob('source-first-error-*.json')]
            self.assertEqual(len(errors),12);self.assertTrue(all(e['semantic_negative_detected'] for e in errors))
            self.assertEqual(len(list((root/'run/native').rglob('submission-*.json'))),13)


if __name__=='__main__':unittest.main()
